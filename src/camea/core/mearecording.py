"""mearecording.py — reading a MaxWell HD-MEA recording (``data.raw.h5``). CORE. Feature-agnostic.

WHAT THIS IS FOR
----------------
Camea's slice of the science is optical: pictures -> coordinates -> electrode ids. This module adds
the *other half of the pair* — the **electrical** record — so that a clicked electrode in the mosaic
can show what that electrode actually measured. See ``utils/knowledge/mea-calcium-goal.md``: the
deliverable is a correspondence, and a correspondence you cannot inspect is not trustworthy.

A recording folder written by MaxLab Live looks like::

    <MEA>/<plate>/<assay>/<run_id>/data.raw.h5      e.g. .../P003658/Network/000690/data.raw.h5

Inside, the parts this module reads::

    data_store/data0000/settings/mapping     (channel, electrode, x_um, y_um) for the ROUTED set
    data_store/data0000/settings/{sampling,lsb,gain,hpf}
    data_store/data0000/groups/routed/raw    (n_channels, n_samples) uint16   <- needs the plugin
    data_store/data0000/groups/routed/frame_nos
    data_store/data0000/spikes               (frameno, channel, amplitude)    <- plain, no plugin

⭐ **ONLY A FEW HUNDRED OF THE CHIP'S ELECTRODES ARE EVER RECORDED.** A MaxOne can route ~1024
channels at a time out of tens of thousands of pads, and which ones were routed is a choice the
experimenter made at acquisition. So *most electrodes in a mosaic have no trace at all*, and that is
normal, not an error. Callers must render "not recorded" as a fact, never as a zero trace.

⛔ NO DEVICE NUMBER IS WRITTEN DOWN HERE (the R45.8 rule, extended)
------------------------------------------------------------------
The array's long axis is **220** on a MaxOne — and that number appears nowhere in this file. The
``mapping`` dataset carries BOTH the electrode id and the electrode's µm position, which means the
file states its own layout::

    electrode = ey * stride + ex        ex = x_um / pitch,  ey = y_um / pitch

so ``stride`` is *derived* from the file and then **verified exactly against every routed
electrode** (:func:`derive_stride`). A file that does not satisfy the relation is refused rather
than guessed at. Same spirit as ``electrodegrid``: the lattice is measured, never assumed.

⛔ AND NO DATASET KNOWLEDGE. Nothing here knows which plate, which run, how many spikes to expect,
or which electrodes matter. It opens a folder and reports what is in it.

🔴 THE RAW STREAM NEEDS A PROPRIETARY DECODER, AND IT MAY BE WRONG
------------------------------------------------------------------
``raw`` is compressed with MaxWell's own HDF5 filter (id **401**, ``mxw-data``) plus deflate. HDF5
loads that filter from a plug-in library at read time; it is not part of the file and not open
source. Two copies exist: the one MaxWell publishes (which ``spikeinterface`` auto-downloads to
``~/hdf5_plugin_path_maxwell``) and the one that ships inside MaxLab Live.

**On SOME of this project's files the published plug-in does not reconstruct the stream.** Where it
fails, ~98% of samples come back as the constant 1023; around a spike the stored samples are a
*comb* of isolated points rather than the ~20-40 consecutive samples a real extracellular waveform
occupies; and the implied amplitudes are ~13x the amplitudes MaxWell's own on-chip detector wrote
into the same file. The file's own ``assay/inputs/spike_only`` is ``false``, i.e. a FULL continuous
trace was recorded — so 98% absent is a decode failure, not a recording mode.

⚠️ **IT IS PARTICULAR RECORDINGS, NOT THE DECODER — corrected 2026-08-15.** This paragraph used to
say "these files" without qualification, from two files measured on 2026-08-13. Re-measured exactly,
per channel, over the whole of each of the five recordings in his project: **000688 sits at 1.1% and
000689 at 4.4% — they decode cleanly** — while 000690/691/692 sit at 96.5%, 100.0% and 93.9%. So the
rail is a property of those three recordings and NOT of the plug-in, this machine, or the format.
⛔ Do not restate it as a general fact; that is how a future session ends up designing around a
problem most of the data does not have. :meth:`trace_health` answers it per window, per channel,
every time, which is why nothing here has to hold an opinion.

Consequences, and they are deliberate:

* :meth:`MeaRecording.spikes` is **trustworthy** — the spike table needs no proprietary filter.
* :meth:`MeaRecording.trace` returns what the decoder gives, alongside
  :meth:`MeaRecording.trace_health`, which measures the fill fraction so a caller can *say so on the
  screen*. ⛔ Never present a trace as clean without consulting it. Silently drawing a flat rail as
  a voltage is exactly the laundered machine answer this project refuses.
* If a correct decoder is installed later, nothing here changes: the health numbers simply come back
  clean and the caveat stops being shown.

⭐ THE LAMP EPISODES ARE A SYNC SIGNAL, NOT A DEFECT (his account, 2026-08-13)
------------------------------------------------------------------------------
*"the people who collected this data turned on and off the 2P lamp a lot to cause artifacts on the
MEA trace, that way the calcium trace and the MEA traces could be synced."* Confirmed in the data:
hundreds of channels leave the rail **simultaneously** for seconds at a time (P003693/000692 spends
54% of its 300 s that way, in 70 separate episodes). :meth:`MeaRecording.sync_episodes` finds them.
They are the intended bridge between the electrical clock and the optical one — treat them as
signal, and never "clean" them away.

This module is pure: numpy + h5py, no camea imports, no I/O outside the paths it is handed.
"""

from __future__ import annotations

import dataclasses
import os
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

import numpy as np

__all__ = [
    "ENVELOPE_FILENAME",
    "ENVELOPE_VERSION",
    "MEA_FILENAME",
    "Envelope",
    "MeaError",
    "MeaRecording",
    "NoRecordingsFound",
    "Orientation",
    "RawUndecodable",
    "RecordingInfo",
    "SyncEpisode",
    "TraceHealth",
    "TtlPulse",
    "derive_geometry",
    "derive_stride",
    "find_recordings",
    "health_of",
    "load_envelope",
    "minmax_columns",
    "plugin_dir",
    "plugin_present",
    "save_envelope",
    "suggest_recordings",
]

MEA_FILENAME = "data.raw.h5"

#: The HDF5 filter id MaxWell registers for its raw stream. Read-only fact about the format.
_MXW_FILTER_ID = 401

#: Where ``spikeinterface`` puts the published plug-in. We only ever *read* this location.
_DEFAULT_PLUGIN_DIR = Path.home() / "hdf5_plugin_path_maxwell"

_STORE = "data_store/data0000"


class MeaError(RuntimeError):
    """Anything wrong with an MEA recording folder or file."""


class NoRecordingsFound(MeaError):
    """A folder was searched and held no ``data.raw.h5``."""


class RawUndecodable(MeaError):
    """The raw stream could not be read — almost always the missing/mismatched MaxWell plug-in."""


# ── the decoder plug-in ─────────────────────────────────────────────────────────────────────────
# HDF5 resolves dynamic filters from HDF5_PLUGIN_PATH at read time, so this must be set BEFORE the
# first read (setting it before opening is simplest). We never download anything: a decoder is a
# licensed artefact of the user's acquisition software, and fetching one silently is not our call.


def plugin_dir() -> Path:
    """Where we expect the MaxWell decoder to live (``HDF5_PLUGIN_PATH`` wins if already set)."""
    env = os.environ.get("HDF5_PLUGIN_PATH")
    return Path(env) if env else _DEFAULT_PLUGIN_DIR


def plugin_present() -> bool:
    """True when *a* decoder library is in place. Says nothing about whether it decodes correctly —
    only :meth:`MeaRecording.trace_health` can tell you that."""
    d = plugin_dir()
    return any((d / n).is_file() for n in ("compression.dll", "libcompression.so",
                                           "libcompression.dylib"))


def _arm_plugin() -> None:
    """Point HDF5 at the decoder if the caller has not already."""
    if not os.environ.get("HDF5_PLUGIN_PATH"):
        os.environ["HDF5_PLUGIN_PATH"] = str(_DEFAULT_PLUGIN_DIR)


def _undecodable() -> RawUndecodable:
    """The one wording for a missing decoder, so every reader says the same thing."""
    return RawUndecodable(
        "the raw stream could not be decoded. MaxWell compresses it with a proprietary "
        f"HDF5 filter (id {_MXW_FILTER_ID}); the matching decoder library must be present "
        f"in {plugin_dir()}. It ships with MaxLab Live."
    )


# ── what a recording is ─────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class RecordingInfo:
    """The facts about one ``data.raw.h5``, cheap to obtain (no raw decode)."""

    path: Path
    run_id: str
    assay: str
    n_channels: int
    n_samples: int
    sampling_hz: float
    lsb_uv: float
    gain: float
    hpf_hz: float
    n_spikes: int

    @property
    def duration_s(self) -> float:
        return self.n_samples / self.sampling_hz if self.sampling_hz else 0.0

    @property
    def label(self) -> str:
        """What a human calls this recording — ``Network/000690``. Not an id; ``run_id`` is."""
        return f"{self.assay}/{self.run_id}" if self.assay else self.run_id

    def as_dict(self) -> dict:
        d = dataclasses.asdict(self)
        d["path"] = str(self.path).replace("\\", "/")
        d["duration_s"] = round(self.duration_s, 3)
        d["label"] = self.label
        return d


@dataclass(frozen=True)
class TraceHealth:
    """How much of a trace window actually decoded.

    ``fill_fraction`` is the share of samples equal to the single most common value. On a healthy
    recording every electrode carries thermal noise, so this sits low; the broken decoder measured
    on this project's data puts it near 1.0. ``flat`` is the blunt verdict a UI should surface.
    """

    n_samples: int
    fill_value: int
    fill_fraction: float
    distinct_values: int

    @property
    def flat(self) -> bool:
        """True when the window is dominated by one repeated value — i.e. not a usable waveform."""
        return self.fill_fraction >= 0.5 or self.distinct_values <= 2

    def as_dict(self) -> dict:
        return {**dataclasses.asdict(self), "flat": self.flat}


def health_of(counts: np.ndarray) -> TraceHealth:
    """:class:`TraceHealth` for raw counts already in hand — no read, no file.

    Exists so a caller that has just read a window (or a whole recording) can measure it without
    paying for the decompression a second time. Identical arithmetic to
    :meth:`MeaRecording.trace_health`.
    """
    if counts.size == 0:
        return TraceHealth(0, 0, 0.0, 0)
    vals, cnts = np.unique(counts, return_counts=True)
    k = int(np.argmax(cnts))
    return TraceHealth(
        n_samples=int(counts.size),
        fill_value=int(vals[k]),
        fill_fraction=float(cnts[k] / counts.size),
        distinct_values=int(vals.size),
    )


def minmax_columns(values: np.ndarray, n_columns: int) -> tuple[np.ndarray, np.ndarray]:
    """Reduce ``values`` to at most ``n_columns`` ``(min, max)`` pairs — the honest thinning.

    ⭐ Min/max, never every n-th value. A spike is 5-16 samples wide at 20 kHz, so sub-sampling a
    long window would land on one roughly never and draw a calm line over a burst. Each column keeps
    the true extent of what is under it, so a spike of any width forces its column tall.
    """
    if values.size == 0:
        return values.astype(np.float64), values.astype(np.float64)
    if n_columns < 1 or values.size <= n_columns:
        return values.astype(np.float64), values.astype(np.float64)
    cut = np.linspace(0, values.size, n_columns + 1, dtype=np.int64)[:-1]
    return np.minimum.reduceat(values, cut), np.maximum.reduceat(values, cut)


#: Bumped whenever the on-disk envelope layout changes. A cache written by an older Camea is
#: rebuilt rather than reinterpreted — a stale shape served as a current one is worse than a wait.
ENVELOPE_VERSION = 1

#: What :func:`save_envelope` writes, beside the recording it describes.
ENVELOPE_FILENAME = "envelope.npz"

#: Channels tallied per `bincount` call while building an envelope. A tuning constant about memory
#: bandwidth, not about any recording — see the comment at its use.
_TALLY_STRIP = 128


@dataclass(frozen=True)
class Envelope:
    """Every routed channel's whole recording, reduced to ``n_buckets`` min/max pairs.

    ⭐ **A CACHE, NOT DATA.** Deleting it costs a rebuild and nothing else; nothing a user authored
    is in here. It exists because reading one channel's full length out of a MaxWell file costs
    almost as much as reading all of them (see :meth:`MeaRecording.build_envelope`).

    ``lo``/``hi`` are raw counts, in the file's own dtype, ``(n_channels, n_buckets)``. Multiply by
    :attr:`lsb_uv` for microvolts — stored unscaled so the cache is half the size and exactly
    reversible. Rows are in ``groups/routed/channels`` order; :meth:`row_of` resolves a channel id.
    """

    version: int
    channels: np.ndarray
    lo: np.ndarray
    hi: np.ndarray
    n_samples: int
    sampling_hz: float
    lsb_uv: float
    fill_value: np.ndarray
    fill_fraction: np.ndarray
    distinct_values: np.ndarray

    @property
    def n_buckets(self) -> int:
        return int(self.lo.shape[1])

    @property
    def duration_s(self) -> float:
        return self.n_samples / self.sampling_hz if self.sampling_hz else 0.0

    def row_of(self, channel: int) -> int | None:
        """The row carrying ``channel``, or None when it was never routed."""
        hit = np.nonzero(self.channels == int(channel))[0]
        return int(hit[0]) if hit.size else None

    def health_of(self, channel: int) -> TraceHealth | None:
        """That channel's **whole-recording** health — never a window's. See ``build_envelope``."""
        row = self.row_of(channel)
        if row is None:
            return None
        return TraceHealth(
            n_samples=self.n_samples,
            fill_value=int(self.fill_value[row]),
            fill_fraction=float(self.fill_fraction[row]),
            distinct_values=int(self.distinct_values[row]),
        )

    def window(
        self, channel: int, t0: float, t1: float, max_points: int
    ) -> tuple[np.ndarray, np.ndarray, float, float] | None:
        """``(min_uv, max_uv, t0, t1)`` for ``[t0, t1)``, further reduced to ``max_points`` columns.

        The returned times are the **bucket edges actually covered**, not what was asked for — a
        caller must label its axis from these, because the buckets are the finest thing this cache
        can honestly report.
        """
        row = self.row_of(channel)
        if row is None:
            return None
        dur = self.duration_s
        if dur <= 0 or self.n_buckets == 0:
            return None
        a = max(0, min(self.n_buckets - 1, int(np.floor(t0 / dur * self.n_buckets))))
        b = max(a + 1, min(self.n_buckets, int(np.ceil(t1 / dur * self.n_buckets))))
        lo = self.lo[row, a:b].astype(np.float64)
        hi = self.hi[row, a:b].astype(np.float64)
        if max_points >= 1 and lo.size > max_points:
            # Fold whole buckets together — still min/max, so a spike still cannot be lost.
            cut = np.linspace(0, lo.size, max_points + 1, dtype=np.int64)
            lo = np.minimum.reduceat(lo, cut[:-1])
            hi = np.maximum.reduceat(hi, cut[:-1])
        return (
            lo * self.lsb_uv,
            hi * self.lsb_uv,
            a / self.n_buckets * dur,
            b / self.n_buckets * dur,
        )


def save_envelope(path: Path, env: Envelope) -> None:
    """Write ``env`` to ``path``. The caller chooses where — this module never picks a location."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".part")
    with tmp.open("wb") as fh:
        np.savez(
            fh,
            version=np.int64(env.version),
            channels=env.channels,
            lo=env.lo,
            hi=env.hi,
            n_samples=np.int64(env.n_samples),
            sampling_hz=np.float64(env.sampling_hz),
            lsb_uv=np.float64(env.lsb_uv),
            fill_value=env.fill_value,
            fill_fraction=env.fill_fraction,
            distinct_values=env.distinct_values,
        )
    # ⚠️ Atomic: a half-written cache that loads is worse than no cache. The rename is the commit.
    tmp.replace(path)


def load_envelope(path: Path) -> Envelope | None:
    """Read an envelope back, or None when it is absent, unreadable, or of an older version."""
    if not path.exists():
        return None
    try:
        with np.load(path) as z:
            version = int(z["version"])
            if version != ENVELOPE_VERSION:
                return None
            return Envelope(
                version=version,
                channels=z["channels"],
                lo=z["lo"],
                hi=z["hi"],
                n_samples=int(z["n_samples"]),
                sampling_hz=float(z["sampling_hz"]),
                lsb_uv=float(z["lsb_uv"]),
                fill_value=z["fill_value"],
                fill_fraction=z["fill_fraction"],
                distinct_values=z["distinct_values"],
            )
    except Exception:  # noqa: BLE001
        # ⭐ **DELIBERATELY EVERYTHING, AND THAT IS THE POINT OF THIS FUNCTION.** A cache that will
        # not load is a cache miss; the caller rebuilds it. Anything that escapes here becomes a 500
        # on a screen whose whole design is to say "not read yet" honestly instead.
        # ⚠️ This used to be `(OSError, KeyError, ValueError)` and that was not enough: a file
        # truncated mid-write — a killed process, a full disk, a half-copied project folder — makes
        # numpy hand the file to `zipfile`, which raises `zipfile.BadZipFile`, a plain `Exception`.
        # Reproduced, and caught in review. Do not narrow this again.
        return None


@dataclass(frozen=True)
class SyncEpisode:
    """One stretch where many channels left the rail together — a 2P lamp artefact (see header)."""

    start_s: float
    end_s: float
    peak_channels: int

    @property
    def duration_s(self) -> float:
        return self.end_s - self.start_s

    def as_dict(self) -> dict:
        return {**dataclasses.asdict(self), "duration_s": round(self.duration_s, 4)}


@dataclass(frozen=True)
class TtlPulse:
    """One digital-input pulse from the rig's own time-stamp — the top-level ``bits`` group.

    ⭐ **Sample-accurate and decoder-free** (docs/MAXWELL.md § 5.6): written by the acquisition
    system into plain HDF5, so it needs neither the proprietary plug-in nor the raw stream —
    everything issue 003 says the lamp episodes are not. ``bits`` is the line value while the
    pulse was high, reported as the file states it; nothing here decodes which line means what.
    """

    start_s: float
    end_s: float
    bits: int

    @property
    def duration_s(self) -> float:
        return self.end_s - self.start_s

    def as_dict(self) -> dict:
        return {**dataclasses.asdict(self), "duration_s": round(self.duration_s, 6)}


# ── the chip's own layout, derived not assumed ──────────────────────────────────────────────────


def derive_stride(electrode: np.ndarray, ex: np.ndarray, ey: np.ndarray) -> int:
    """Recover the array's row stride (the long-axis length) from already-indexed electrodes.

    MaxWell numbers electrodes ``electrode = ey * stride + ex``. Given the triples we solve for
    ``stride`` and then *check it on every electrode*, which is what makes this safe to do instead
    of writing ``220`` down somewhere.

    Prefer :func:`derive_geometry`, which recovers the pitch too; this is the second half of it.
    Raises :class:`MeaError` when no single stride explains the mapping — better a refusal than a
    silently transposed chip, which would pair every electrode with the wrong neuron.
    """
    electrode = np.asarray(electrode, dtype=np.int64)
    ex = np.asarray(ex, dtype=np.int64)
    ey = np.asarray(ey, dtype=np.int64)
    if electrode.size == 0:
        raise MeaError("empty electrode mapping — cannot derive the array layout")

    if np.unique(ey).size < 2:
        # Everything on one row: stride is unconstrained by the data. Refuse rather than invent.
        raise MeaError(
            "the routed electrodes all sit on one array row, so the chip's layout cannot be "
            "derived from this file"
        )
    # electrode - ex == ey * stride exactly, so stride is the common ratio.
    resid = electrode - ex
    nz = ey != 0
    cands = np.unique(resid[nz] // ey[nz])
    for stride in cands:
        if stride > 0 and np.array_equal(ey * int(stride) + ex, electrode):
            return int(stride)
    raise MeaError(
        "the file's electrode ids are not a consistent (row x stride + column) numbering; "
        "refusing to guess the chip layout"
    )


def derive_geometry(electrode: np.ndarray, x_um: np.ndarray,
                    y_um: np.ndarray) -> tuple[float, int]:
    """Recover ``(pitch_um, stride)`` from the file's own mapping, then verify both exactly.

    ⭐ **WHY NOT JUST MEASURE THE SPACING.** The obvious move — take the smallest gap between routed
    electrodes — is wrong, and real data caught it: in one of this project's recordings only every
    *other* pad was routed, so the smallest routed gap is 35 µm and the true pitch is 17.5. Routing
    is an experimenter's choice, so no property of the routed *subset* can be trusted to reveal the
    chip.

    What is always true is the numbering identity itself. With ``electrode = ey*stride + ex``,
    ``x = ex*pitch`` and ``y = ey*pitch``::

        pitch * electrode  -  stride * y  =  x

    which is **linear in the two unknowns** and holds for every routed electrode at once. Least
    squares over all of them recovers both, and the result is then checked exactly — a file that
    does not satisfy it is refused rather than guessed at.
    """
    el = np.asarray(electrode, dtype=np.float64)
    x = np.asarray(x_um, dtype=np.float64)
    y = np.asarray(y_um, dtype=np.float64)
    if el.size < 2:
        raise MeaError("need at least two routed electrodes to derive the chip layout")
    if np.unique(y).size < 2:
        raise MeaError(
            "the routed electrodes all sit on one array row, so the chip's layout cannot be "
            "derived from this file"
        )

    a = np.column_stack([el, -y])
    sol, *_ = np.linalg.lstsq(a, x, rcond=None)
    pitch, stride_f = float(sol[0]), float(sol[1])
    stride = int(round(stride_f))
    if not np.isfinite(pitch) or pitch <= 0 or stride <= 0:
        raise MeaError("the file's mapping does not describe a positive pitch and stride")
    if abs(stride_f - stride) > 1e-3:
        raise MeaError(
            f"the file's mapping implies a non-integer array stride ({stride_f:.4f}); "
            "refusing to guess the chip layout"
        )

    ex = np.rint(x / pitch).astype(np.int64)
    ey = np.rint(y / pitch).astype(np.int64)
    if not (np.allclose(ex * pitch, x, atol=pitch * 1e-3)
            and np.allclose(ey * pitch, y, atol=pitch * 1e-3)):
        raise MeaError("the file's electrode positions are not whole multiples of one pitch")
    if not np.array_equal(ey * stride + ex, np.asarray(electrode, dtype=np.int64)):
        raise MeaError(
            "the file's electrode ids are not a consistent (row x stride + column) numbering; "
            "refusing to guess the chip layout"
        )
    return pitch, stride


@dataclass(frozen=True)
class Orientation:
    """How the chip's own axes sit in the mosaic image.

    The chip half of the pairing is settled by the file (see :func:`derive_stride`). The other half
    — *which corner of the mosaic the chip's origin landed in* — is a fact about the microscope, not
    about the chip, and no file records it. Four seatings are possible once the transpose is fixed
    by the two shapes; this is that choice, held explicitly so it is always visible and never a
    hidden default.

    ⛔ ``flip_x``/``flip_y`` must be *chosen or measured*, never assumed. Camea determines them by
    aligning the lamp episodes with the calcium video and testing spike/calcium coincidence.
    """

    flip_x: bool = False
    flip_y: bool = False
    #: True once something actually established this seating (a test, or the user saying so).
    confirmed: bool = False
    #: Free text recording HOW it was established, for provenance.
    source: str = ""

    def as_dict(self) -> dict:
        return dataclasses.asdict(self)

    def to_grid(self, ex: np.ndarray, ey: np.ndarray, *, cols: int, rows: int,
                stride: int) -> tuple[np.ndarray, np.ndarray]:
        """Map chip indices ``(ex, ey)`` to Camea 1-based ``(col, row)`` grid coordinates.

        The transpose is *derived*: Camea's grid is described by ``cols x rows`` measured off the
        image, the chip by ``stride`` x (n/stride). When ``cols != stride`` the image shows the chip
        turned a quarter turn, which is the normal case for a portrait mosaic of a landscape chip.
        """
        ex = np.asarray(ex, dtype=np.int64)
        ey = np.asarray(ey, dtype=np.int64)
        long_axis, short_axis = (ex, ey) if cols != stride else (ey, ex)
        # long_axis runs along the grid's longer side (rows), short along the shorter (cols).
        col = (short_axis if not self.flip_y else (max(cols, 1) - 1 - short_axis)) + 1
        row = (long_axis if not self.flip_x else (max(rows, 1) - 1 - long_axis)) + 1
        return col, row

    def from_grid(self, col: int, row: int, *, cols: int, rows: int,
                  stride: int) -> tuple[int, int]:
        """The inverse of :meth:`to_grid`: a clicked 1-based ``(col, row)`` back to chip ``(ex, ey)``.

        This is the direction the UI actually needs — the user clicks a pad in the mosaic and we
        must say which MaxWell channel that is. Kept as the literal inverse so the round trip is
        testable, because an error here is silent and pairs the wrong neuron with the wrong voltage.
        """
        short_axis = (cols - col) if self.flip_y else (col - 1)
        long_axis = (rows - row) if self.flip_x else (row - 1)
        return (long_axis, short_axis) if cols != stride else (short_axis, long_axis)

    def chip_electrode(self, col: int, row: int, *, cols: int, rows: int, stride: int) -> int:
        """MaxWell's own electrode id under a clicked Camea ``(col, row)``."""
        ex, ey = self.from_grid(col, row, cols=cols, rows=rows, stride=stride)
        return ey * stride + ex


# ── discovery ───────────────────────────────────────────────────────────────────────────────────


def find_recordings(root: str | Path, *, limit: int = 64) -> list[Path]:
    """Every ``data.raw.h5`` under ``root``, in a stable order. Cheap: a filename walk, no opens."""
    root = Path(root)
    if not root.is_dir():
        return []
    found = sorted(p for p in root.rglob(MEA_FILENAME) if p.is_file())
    return found[:limit]


def suggest_recordings(data_dir: str | Path, name: str = "", *, max_up: int = 4,
                       limit: int = 200) -> list[Path]:
    """Guess which recordings belong to a project whose *imaging* lives at ``data_dir``.

    A session is normally laid out with the optical and electrical halves as siblings::

        <session>/Imaging/<plate>/imaging/mosaic.mp4     <- data_dir points in here
        <session>/MEA/<plate>/<assay>/<run>/data.raw.h5  <- what we are looking for

    so we climb from ``data_dir`` and take the first level that has any recordings beneath it,
    preferring those whose path mentions ``name`` (the project's name, which the user chose — a
    label, not knowledge about the data).

    ⭐ **THIS ONLY EVER PROPOSES.** The result is shown to the user and saved solely on their
    confirmation; nothing here decides that a recording belongs to a project. A wrong attachment
    would pair one culture's voltages with another's neurons, which is the whole failure this
    project exists to prevent.
    """
    start = Path(data_dir)
    if start.is_file():
        start = start.parent
    climbed = 0
    if not start.exists():
        # ⭐ The recorded data_dir may be stale — a mirror can be reorganised long after a project
        # was made (observed on this project's own data: a folder gained an extra level). Fall back
        # to the nearest ancestor that still exists rather than reporting "nothing found", which
        # would be a lie about the disk.
        for depth, parent in enumerate(start.parents, start=1):
            if parent.exists():
                start, climbed = parent, depth
                break
        else:
            return []
    # ⛔ The climb is BUDGETED, and the fallback above spends from the same budget. Without that a
    # stale path could walk up to a drive root and propose recordings from an unrelated session —
    # which the user might well confirm, because the dialog looks the same either way.
    budget = max_up - climbed
    if budget < 0:
        return []
    needle = name.strip().lower()
    seen: set[Path] = set()
    for up in range(budget + 1):
        try:
            root = start if up == 0 else start.parents[up - 1]
        except IndexError:
            break
        if root in seen:
            continue
        seen.add(root)
        hits = find_recordings(root, limit=limit)
        if not hits:
            continue
        if needle:
            preferred = [p for p in hits if needle in str(p).lower()]
            if preferred:
                return preferred
        return hits
    return []


# ── the reader ──────────────────────────────────────────────────────────────────────────────────


class MeaRecording:
    """One ``data.raw.h5``, opened lazily.

    Cheap on construction; every accessor reads only what it needs. Use as a context manager, or
    call :meth:`close`. Safe to build for a file whose raw stream cannot be decoded — everything
    except :meth:`trace` still works, which is the point (see the header).
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        if not self.path.is_file():
            raise NoRecordingsFound(f"no MEA recording at {self.path}")
        _arm_plugin()
        self._h5 = None
        self._info: RecordingInfo | None = None
        self._mapping: np.ndarray | None = None
        self._geometry: tuple[float, int] = (0.0, 0)

    # -- lifecycle ------------------------------------------------------------------------------

    def __enter__(self) -> MeaRecording:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        if self._h5 is not None:
            self._h5.close()
            self._h5 = None

    @property
    def _f(self):
        if self._h5 is None:
            import h5py

            try:
                self._h5 = h5py.File(self.path, "r")
            except OSError as e:  # pragma: no cover - depends on the file on disk
                raise MeaError(f"cannot open {self.path}: {e}") from e
        return self._h5

    def _grp(self):
        f = self._f
        if _STORE in f:
            return f[_STORE]
        raise MeaError(f"{self.path} has no {_STORE} group — not a MaxLab recording?")

    # -- facts ----------------------------------------------------------------------------------

    def info(self) -> RecordingInfo:
        """Header facts. Does not touch the raw stream, so it works without the decoder."""
        if self._info is not None:
            return self._info
        g = self._grp()
        s = g["settings"]

        def scalar(name: str, default: float = 0.0) -> float:
            return float(s[name][0]) if name in s else default

        raw = g["groups/routed/raw"]
        n_ch, n_s = int(raw.shape[0]), int(raw.shape[1])
        run_id, assay = self._identity()
        self._info = RecordingInfo(
            path=self.path,
            run_id=run_id,
            assay=assay,
            n_channels=n_ch,
            n_samples=n_s,
            sampling_hz=scalar("sampling"),
            lsb_uv=scalar("lsb") * 1e6,
            gain=scalar("gain"),
            hpf_hz=scalar("hpf"),
            n_spikes=int(g["spikes"].shape[0]) if "spikes" in g else 0,
        )
        return self._info

    def _identity(self) -> tuple[str, str]:
        """``(run_id, assay)`` — from the file if it says, else from the folder names that hold it."""
        f = self._f
        run_id = ""
        if "assay/run_id" in f:
            raw = f["assay/run_id"][0]
            run_id = raw.decode() if isinstance(raw, bytes) else str(raw)
        if not run_id:
            run_id = self.path.parent.name
        assay = self.path.parent.parent.name if self.path.parent.parent != self.path.parent else ""
        return run_id, assay

    def mapping(self) -> np.ndarray:
        """The routed set as a structured array with the chip indices derived and attached.

        Fields: ``channel``, ``electrode``, ``x_um``, ``y_um``, ``ex``, ``ey``. ``ex``/``ey`` are the
        chip's own integer column/row, recovered from the µm positions and the measured pitch.
        """
        if self._mapping is not None:
            return self._mapping
        m = np.asarray(self._grp()["settings/mapping"][:])
        pitch, stride = derive_geometry(m["electrode"], m["x"], m["y"])
        self._geometry = (pitch, stride)
        ex = np.rint(np.asarray(m["x"], dtype=np.float64) / pitch).astype(np.int64)
        ey = np.rint(np.asarray(m["y"], dtype=np.float64) / pitch).astype(np.int64)
        out = np.empty(
            m.shape,
            dtype=[("channel", "<i4"), ("electrode", "<i8"), ("x_um", "<f8"),
                   ("y_um", "<f8"), ("ex", "<i8"), ("ey", "<i8")],
        )
        out["channel"] = m["channel"]
        out["electrode"] = m["electrode"]
        out["x_um"] = m["x"]
        out["y_um"] = m["y"]
        out["ex"] = ex
        out["ey"] = ey
        self._mapping = out
        return out

    def stride(self) -> int:
        """The array's long-axis length, derived from this file and verified (:func:`derive_geometry`)."""
        self.mapping()
        return self._geometry[1]

    def pitch_um(self) -> float:
        """The electrode pitch this file's own numbering implies. Derived and verified, never a
        datasheet number and never the routed spacing (see :func:`derive_geometry`)."""
        self.mapping()
        return self._geometry[0]

    def channel_of_electrode(self, electrode: int) -> int | None:
        """The routed channel carrying ``electrode``, or None when it was never recorded."""
        m = self.mapping()
        hit = np.nonzero(m["electrode"] == int(electrode))[0]
        return int(m["channel"][hit[0]]) if hit.size else None

    def _row_of_channel(self, channel: int) -> int:
        ch = np.asarray(self._grp()["groups/routed/channels"][:])
        hit = np.nonzero(ch == int(channel))[0]
        if not hit.size:
            raise MeaError(f"channel {channel} is not in this recording's routed set")
        return int(hit[0])

    # -- the trustworthy half: spikes ------------------------------------------------------------

    def spikes(self) -> np.ndarray:
        """Every detected spike as ``(t_s, channel, amplitude_uv)``.

        ⭐ Written by MaxWell's on-chip detector at acquisition and stored **uncompressed**, so this
        needs no plug-in and is unaffected by the raw-decode problem in the header. Times are
        seconds from the first stored sample.
        """
        g = self._grp()
        if "spikes" not in g:
            return np.empty(0, dtype=[("t_s", "<f8"), ("channel", "<i4"), ("amplitude_uv", "<f4")])
        sp = np.asarray(g["spikes"][:])
        fs = self.info().sampling_hz or 1.0
        first = int(np.asarray(g["groups/routed/frame_nos"][0]))
        out = np.empty(sp.shape, dtype=[("t_s", "<f8"), ("channel", "<i4"),
                                        ("amplitude_uv", "<f4")])
        out["t_s"] = (np.asarray(sp["frameno"], dtype=np.int64) - first) / fs
        out["channel"] = sp["channel"]
        out["amplitude_uv"] = sp["amplitude"]
        return out

    def spikes_of_channel(self, channel: int) -> np.ndarray:
        sp = self.spikes()
        return sp[sp["channel"] == int(channel)]

    def ttl_events(self) -> list[TtlPulse]:
        """Digital-input pulses the rig itself wrote — the top-level ``bits`` group.

        ⭐ Plain HDF5: no proprietary plug-in, no raw stream, so this is trustworthy on every
        machine the spike table is (docs/MAXWELL.md § 5.6). An empty list is the ordinary answer —
        most recordings carry no digital input at all.

        ⚠️ **TWO LAYOUTS EXIST AND BOTH ARE READ.** On this project's files ``bits`` is a *group*
        keyed ``'0000'`` whose members are ``(frameno, bits)`` records; the layout spikeinterface's
        ``MaxwellEventExtractor`` expects is a flat *dataset* with the same fields. A ``bits`` in
        neither shape raises :class:`MeaError` rather than being silently read as "no signal" —
        an earlier pass concluded exactly that from reading the wrong location, and it was wrong.

        Times are seconds from the first stored sample — the same origin as :meth:`spikes` — and
        **can be negative**: the rig logs during the pre-roll too (§ 5.6). Report them; do not
        clamp. A record sequence still high at its end is closed at the recording's end, the most
        it can honestly claim.
        """
        import h5py  # noqa: PLC0415

        f = self._f
        if "bits" not in f:
            return []
        node = f["bits"]
        parts: list[np.ndarray] = ([np.asarray(node[key][:]) for key in sorted(node.keys())]
                                   if isinstance(node, h5py.Group) else [np.asarray(node[:])])
        parts = [p for p in parts if p.size]
        if not parts:
            return []
        for p in parts:
            if p.dtype.names is None or not {"frameno", "bits"} <= set(p.dtype.names):
                raise MeaError(
                    f"{self.path} carries a top-level `bits` in a layout this reader does not "
                    f"know (fields {p.dtype.names}) — refusing to guess what its records mean"
                )
        rec = np.concatenate(parts) if len(parts) > 1 else parts[0]
        rec = rec[np.argsort(np.asarray(rec["frameno"], dtype=np.int64), kind="stable")]

        info = self.info()
        fs = info.sampling_hz or 1.0
        first = int(np.asarray(self._grp()["groups/routed/frame_nos"][0]))
        t = (np.asarray(rec["frameno"], dtype=np.int64) - first) / fs
        vals = np.asarray(rec["bits"], dtype=np.int64)

        out: list[TtlPulse] = []
        open_t: float | None = None
        open_v = 0
        for ti, v in zip(t, vals):
            if open_t is None:
                if v != 0:
                    open_t, open_v = float(ti), int(v)
            elif v == 0:
                out.append(TtlPulse(start_s=open_t, end_s=float(ti), bits=open_v))
                open_t = None
            elif int(v) != open_v:
                # The line changed value while high: two pulses, split where the record says.
                out.append(TtlPulse(start_s=open_t, end_s=float(ti), bits=open_v))
                open_t, open_v = float(ti), int(v)
        if open_t is not None:
            out.append(TtlPulse(start_s=open_t, end_s=info.duration_s, bits=open_v))
        return out

    def activity(self, t0: float | None = None, t1: float | None = None) -> np.ndarray:
        """How much happened on each routed pad — ``(channel, n_spikes, rate_hz)``, in
        :meth:`mapping` order so the two zip together without a join.

        ⭐ **With ``t0``/``t1`` (seconds), the tally covers only ``[t0, t1)``** and ``rate_hz``
        divides by that window's length — the chip map's "colours follow the view" mode. The
        window arrives from the caller and nothing about it is assumed or remembered (I1);
        docs/MAXWELL.md §7.3 is why the window length must then be shown beside any silent
        count. ⛔ With neither given, the whole-recording behaviour is exactly what it always
        was — same spikes, same divisor.

        ⭐ **THIS LIVES IN CORE, NOT IN THE FEATURE, BECAUSE IT IS A FACT ABOUT THE FILE.** It is a
        pure function of the spike table and the routed set — the same tally whoever asks — and the
        screen that draws it is only the first caller. (Plan 003 § Open put the question; this is the
        answer, and :func:`tests.unit.test_mearecording` holds it to it.)

        ⭐ **AND IT NEEDS NO PROPRIETARY DECODER.** The spike table is written uncompressed by
        MaxWell's on-chip detector, so this is trustworthy on every machine — including all of the
        ones where :meth:`trace` comes back as a rail (see the header). That is what makes a chip map
        coloured by *this* worth drawing before the decoder problem is solved.

        ⛔ **A ROUTED PAD THAT HEARD NOTHING COMES BACK AS 0, NOT AS ABSENT.** Silence is a
        measurement: the amplifier was on that pad for the whole recording and detected nothing. A
        caller must be able to tell it apart from a pad that was never routed at all — the second is
        simply not in :meth:`mapping` — so every routed channel gets a row, always.

        ⛔ No threshold, no expected rate, no "is this chip healthy" verdict (I1). It counts what the
        detector wrote and divides by the duration the header states.
        """
        m = self.mapping()
        ch = np.asarray(m["channel"], dtype=np.int64)
        counts = np.zeros(ch.size, dtype=np.int64)

        sp = self.spikes()
        if t0 is None and t1 is None:
            dur = self.info().duration_s
        else:
            lo = 0.0 if t0 is None else float(t0)
            hi = self.info().duration_s if t1 is None else float(t1)
            dur = hi - lo
            if sp.size:
                sp = sp[(sp["t_s"] >= lo) & (sp["t_s"] < hi)]
        if sp.size and ch.size:
            # A lookup by sorted position rather than a Python dict: ~1k pads against a few hundred
            # thousand spikes, and the dict version measured ~40x slower on the real recordings.
            order = np.argsort(ch, kind="stable")
            sorted_ch = ch[order]
            want = np.asarray(sp["channel"], dtype=np.int64)
            at = np.searchsorted(sorted_ch, want)
            at = np.clip(at, 0, sorted_ch.size - 1)
            # ⚠️ `searchsorted` returns an insertion point, not a match. A spike on a channel that is
            # NOT in the routed mapping would otherwise be credited to whichever pad happens to sit
            # at that insertion point — i.e. silently added to an innocent electrode. Confirm the hit.
            hit = sorted_ch[at] == want
            np.add.at(counts, order[at[hit]], 1)

        out = np.empty(ch.size, dtype=[("channel", "<i4"), ("n_spikes", "<i8"),
                                       ("rate_hz", "<f8")])
        out["channel"] = ch
        out["n_spikes"] = counts
        out["rate_hz"] = counts / dur if dur > 0 else np.zeros(ch.size, dtype=np.float64)
        return out

    # -- the half that needs the decoder ---------------------------------------------------------

    def trace(self, channel: int, t0: float = 0.0, t1: float | None = None) -> np.ndarray:
        """The stored waveform for ``channel`` over ``[t0, t1)`` seconds, in microvolts.

        ⚠️ Consult :meth:`trace_health` on the same window before presenting this as a voltage. On
        this project's data the published decoder returns a rail with a comb of isolated samples;
        drawing that unlabelled would be a laundered answer, which is exactly what this project
        refuses. Raises :class:`RawUndecodable` when HDF5 cannot run the filter at all.
        """
        info = self.info()
        fs = info.sampling_hz or 1.0
        a = max(0, int(round(t0 * fs)))
        b = info.n_samples if t1 is None else min(info.n_samples, int(round(t1 * fs)))
        if b <= a:
            return np.empty(0, dtype=np.float64)
        row = self._row_of_channel(channel)
        raw = self._grp()["groups/routed/raw"]
        try:
            counts = np.asarray(raw[row, a:b], dtype=np.float64)
        except OSError as e:
            raise RawUndecodable(
                "the raw stream could not be decoded. MaxWell compresses it with a proprietary "
                f"HDF5 filter (id {_MXW_FILTER_ID}); the matching decoder library must be present "
                f"in {plugin_dir()}. It ships with MaxLab Live."
            ) from e
        return counts * info.lsb_uv

    def trace_health(self, channel: int, t0: float = 0.0, t1: float | None = None) -> TraceHealth:
        """How much of that window is a single repeated value — see :class:`TraceHealth`."""
        info = self.info()
        fs = info.sampling_hz or 1.0
        a = max(0, int(round(t0 * fs)))
        b = info.n_samples if t1 is None else min(info.n_samples, int(round(t1 * fs)))
        if b <= a:
            return TraceHealth(0, 0, 0.0, 0)
        row = self._row_of_channel(channel)
        raw = self._grp()["groups/routed/raw"]
        try:
            counts = np.asarray(raw[row, a:b])
        except OSError as e:
            raise RawUndecodable(str(e)) from e
        vals, cnts = np.unique(counts, return_counts=True)
        k = int(np.argmax(cnts))
        return TraceHealth(
            n_samples=int(counts.size),
            fill_value=int(vals[k]),
            fill_fraction=float(cnts[k] / counts.size),
            distinct_values=int(vals.size),
        )

    def _bounds(self, t0: float, t1: float | None) -> tuple[int, int]:
        """The sample range ``[a, b)`` covering ``[t0, t1)`` seconds, clipped to the file."""
        info = self.info()
        fs = info.sampling_hz or 1.0
        a = max(0, int(round(t0 * fs)))
        b = info.n_samples if t1 is None else min(info.n_samples, int(round(t1 * fs)))
        return a, b

    def trace_window(
        self, channel: int, t0: float = 0.0, t1: float | None = None
    ) -> tuple[np.ndarray, TraceHealth]:
        """The waveform in µV over ``[t0, t1)`` **and** its health, from a SINGLE read.

        ⭐ **THIS EXISTS BECAUSE THE PAIR COST DOUBLE.** :meth:`trace` and :meth:`trace_health` each
        slice ``raw[row, a:b]`` independently, and every caller that presents a trace honestly needs
        both — so the API route was paying for the window twice (measured 1.05 s + 1.06 s on a 30 s
        window of P003658/000689). Decompression is the whole cost here, and it is now paid once.

        ⚠️ :meth:`trace` and :meth:`trace_health` are deliberately left in place and unchanged. They
        have their own callers and their own tests; this is an addition, not a replacement.
        """
        info = self.info()
        a, b = self._bounds(t0, t1)
        if b <= a:
            return np.empty(0, dtype=np.float64), TraceHealth(0, 0, 0.0, 0)
        row = self._row_of_channel(channel)
        raw = self._grp()["groups/routed/raw"]
        try:
            counts = np.asarray(raw[row, a:b])
        except OSError as e:
            raise _undecodable() from e
        return counts.astype(np.float64) * info.lsb_uv, health_of(counts)

    # -- the whole recording at a glance: the min/max envelope ------------------------------------

    def build_envelope(
        self,
        n_buckets: int,
        *,
        max_block_values: int = 25_000_000,
        progress: Callable[[float], None] | None = None,
    ) -> Envelope:
        """Reduce **every routed channel** to ``n_buckets`` min/max pairs spanning the recording.

        ⭐ **WHY EVERY CHANNEL AT ONCE, AND WHY THIS IS PRECOMPUTED RATHER THAN SERVED ON DEMAND.**
        ``groups/routed/raw`` is chunked ``(n_channels, 200)`` and gzipped, so reading **one**
        channel's full length decompresses **all** of them. Measured on his five recordings
        (2026-08-15): one channel costs 12-23 s; all 726-1015 channels cost 19-32 s — a factor of
        **1.4**, not 1000. So a per-pad whole-recording read is unaffordable (15-23 s per click) and
        a whole-file pass is affordable exactly once. That single ratio is why this method exists.

        ⭐ **MIN/MAX, NEVER SUB-SAMPLING.** A spike is 5-16 samples wide at 20 kHz; taking every
        n-th sample across a 300 s recording would miss essentially all of them and draw a calm line
        over a burst. Each bucket keeps the true extent of the samples under it, so a spike of any
        width forces its bucket to be tall and cannot be made invisible. Same rule the client already
        states in ``web/src/core/trace/TraceChart.tsx``; now binding on the writer too.

        ⚠️ **HEALTH IS COMPUTED HERE, EXACTLY, AND OVER THE WHOLE RECORDING.** A railed window is
        indistinguishable from a genuinely quiet electrode, and the rail fraction **changes with
        window length** (measured 1.000 over 1 s but 0.827 over 30 s on P003693/000690) — so an
        overview may not borrow a window's health number and must carry its own. Exact, not sampled:
        the pass already has every value in hand, and the value span is small enough (this file's own
        maximum, derived below — never assumed) that a per-channel tally costs a few MB.

        ⛔ Nothing here knows a sample rate, a duration, a channel count or a bucket count. ``n_buckets``
        is the caller's rendering choice; everything else comes from the file.
        """
        info = self.info()
        n_ch, n_s = info.n_channels, info.n_samples
        if n_buckets < 1:
            raise ValueError("n_buckets must be at least 1")
        if n_s == 0:
            # An ActivityScan writes no continuous trace at all. That is a fact about the assay, not
            # a failure, and it is worded differently everywhere it surfaces.
            raise MeaError(f"{self.path} stores no continuous trace (0 samples) — nothing to reduce")

        n_buckets = min(n_buckets, n_s)
        edges = np.linspace(0, n_s, n_buckets + 1, dtype=np.int64)
        channels = np.asarray(self._grp()["groups/routed/channels"][:], dtype=np.int64)
        raw = self._grp()["groups/routed/raw"]

        lo = np.zeros((n_ch, n_buckets), dtype=np.uint16)
        hi = np.zeros((n_ch, n_buckets), dtype=np.uint16)
        span = 1
        hist = np.zeros((n_ch, span), dtype=np.uint32)

        # Buckets per read. Sized by VALUES so wide-channel files do not blow the temporary up.
        per_bucket = max(1, n_s // n_buckets)
        group = max(1, int(max_block_values // max(1, n_ch * per_bucket)))

        k = 0
        while k < n_buckets:
            k1 = min(n_buckets, k + group)
            a, b = int(edges[k]), int(edges[k1])
            try:
                block = np.asarray(raw[:, a:b])
            except OSError as e:
                raise _undecodable() from e

            for j in range(k, k1):
                seg = block[:, int(edges[j]) - a : int(edges[j + 1]) - a]
                if seg.size == 0:  # pragma: no cover - only when n_buckets == n_samples
                    continue
                lo[:, j] = seg.min(axis=1)
                hi[:, j] = seg.max(axis=1)

            top = int(block.max()) + 1
            if top > span:
                hist = np.pad(hist, ((0, 0), (0, top - span)))
                span = top
            # ⭐ **THE TALLY, EXACT, IN THE SAME PASS.** Offset each channel into its own stretch of
            # bins so a whole strip is one `bincount` rather than one call per channel. Strips rather
            # than the whole block because `bincount` widens its input to intp: at 6e9 samples per
            # recording an all-at-once cast writes tens of GB, and 128 channels at a time keeps the
            # temporary inside cache. Measured on P003658/000691: 39 s -> 8 s.
            for s0 in range(0, n_ch, _TALLY_STRIP):
                sub = block[s0 : s0 + _TALLY_STRIP]
                rows = sub.shape[0]
                offs = (np.arange(rows, dtype=np.int32) * span)[:, None]
                idx = np.add(sub, offs, dtype=np.int32).ravel()
                hist[s0 : s0 + rows] += (
                    np.bincount(idx, minlength=rows * span).reshape(rows, span).astype(np.uint32)
                )

            k = k1
            if progress is not None:
                progress(k / n_buckets)

        modal = hist.argmax(axis=1)
        counts = hist[np.arange(n_ch), modal]
        return Envelope(
            version=ENVELOPE_VERSION,
            channels=channels.astype(np.int32),
            lo=lo,
            hi=hi,
            n_samples=n_s,
            sampling_hz=info.sampling_hz,
            lsb_uv=info.lsb_uv,
            fill_value=modal.astype(np.int32),
            fill_fraction=(counts / n_s).astype(np.float32),
            distinct_values=(hist > 0).sum(axis=1).astype(np.int32),
        )

    # -- the lamp episodes ------------------------------------------------------------------------

    def sync_episodes(self, t0: float = 0.0, t1: float | None = None, *,
                      min_channels: int = 50, min_duration_s: float = 0.5,
                      bin_ms: float = 1.0) -> list[SyncEpisode]:
        """Stretches where ``min_channels`` or more left the rail **together** — the 2P lamp marks.

        Synchrony is the whole discriminator: neural activity is local to a few electrodes, whereas
        a lamp switching hits the entire array in the same instant.

        ⚠️ **BOUND THE WINDOW.** Over a whole 300 s recording this is one full pass of the raw
        stream — measured ~16 s, far too slow to sit inside a request. Callers drawing a chart pass
        the window they are drawing, which costs a few blocks; callers building the MEA↔calcium
        clock alignment want the whole recording and should run it as a job.

        Returned times are absolute (seconds from the recording's first sample), not relative to
        ``t0`` — a mark is a timestamp in the recording, whatever window revealed it.
        """
        info = self.info()
        fs = info.sampling_hz or 1.0
        raw = self._grp()["groups/routed/raw"]
        n = info.n_samples
        a0 = max(0, int(round(t0 * fs)))
        a1 = n if t1 is None else min(n, int(round(t1 * fs)))
        if a1 <= a0:
            return []
        per_bin = max(1, int(round(bin_ms * fs / 1000.0)))
        rail = self._rail_value()
        block = max(per_bin, int(2e5) // per_bin * per_bin)
        parts: list[np.ndarray] = []
        try:
            for a in range(a0, a1, block):
                blk = raw[:, a:min(a + block, a1)]
                off = (np.asarray(blk) != rail).sum(axis=0).astype(np.int32)
                usable = off.size // per_bin * per_bin
                if usable:
                    parts.append(off[:usable].reshape(-1, per_bin).max(axis=1))
        except OSError as e:
            raise RawUndecodable(str(e)) from e
        if not parts:
            return []
        off = np.concatenate(parts)
        offset = a0 / fs
        return [dataclasses.replace(e, start_s=e.start_s + offset, end_s=e.end_s + offset)
                for e in _episodes(off, min_channels, min_duration_s, bin_ms)]

    def _rail_value(self) -> int:
        """The value the array sits at when nothing is happening — measured from a sample window."""
        raw = self._grp()["groups/routed/raw"]
        n = min(self.info().n_samples, 20000)
        try:
            blk = np.asarray(raw[:, :n])
        except OSError as e:
            raise RawUndecodable(str(e)) from e
        vals, cnts = np.unique(blk, return_counts=True)
        return int(vals[int(np.argmax(cnts))])


# ── helpers ─────────────────────────────────────────────────────────────────────────────────────


def _episodes(off: np.ndarray, min_channels: int, min_duration_s: float,
              bin_ms: float) -> Iterator[SyncEpisode]:
    mask = off >= min_channels
    if not mask.any():
        return
    edge = np.diff(np.concatenate([[0], mask.astype(np.int8), [0]]))
    starts = np.nonzero(edge == 1)[0]
    ends = np.nonzero(edge == -1)[0]
    for a, b in zip(starts, ends, strict=True):
        dur = (b - a) * bin_ms / 1000.0
        if dur >= min_duration_s:
            yield SyncEpisode(
                start_s=a * bin_ms / 1000.0,
                end_s=b * bin_ms / 1000.0,
                peak_channels=int(off[a:b].max()),
            )

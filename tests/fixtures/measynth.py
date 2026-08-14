"""A tiny synthetic MaxLab-shaped ``data.raw.h5`` — the fixture that makes `Analyze MEA` testable.

    from tests.fixtures.measynth import write_recording        (or the `measynth` conftest fixture)
    write_recording(tmp / "P0000" / "Network" / "000001" / "data.raw.h5")

⭐ **WHY THIS EXISTS AT ALL.** `tests/fixtures/synthetic/` is a *frame* dataset and `survey.avi` is a
*video*; neither is an MEA recording, so before this there was no way to exercise the import, the
copy or the shelf without the 35 GB mirror and a real MaxWell file. The fast suite and the e2e suite
both have to run on a clean clone (`tests/api/conftest.py` states the rule), so the fixture is
synthetic, committed, and a few kilobytes.

⛔ **NOTHING HERE IS A MAXWELL.** Same discipline as `tests/unit/test_mearecording.py` and
`web/src/features/electrodes/device.test.ts`: a fixture with a 220-wide array would let a hard-coded
220 pass its own test. The chip below is **13 wide × 5 tall on a 12.5 µm pitch** at 20 kHz, which no
device is, so `derive_geometry` has to actually derive it.

⛔ **AND NO DATASET KNOWLEDGE LEAVES THIS FILE.** The numbers here are fixture facts, which HARD RULE
3 explicitly permits inside `tests/`. Nothing in `src/camea/` or `web/src/` may know any of them.

────────────────────────────────────────────────────────────────────────────────────────────────
⭐ **THE RAW STREAM IS DECLARED BUT NEVER WRITTEN, AND THAT IS THE WHOLE TRICK.**
────────────────────────────────────────────────────────────────────────────────────────────────
A real recording's ``groups/routed/raw`` is (n_channels × n_samples) uint16 behind MaxWell's
proprietary HDF5 filter (id 401) — gigabytes, and undecodable on this machine anyway
(`utils/knowledge/mea-recordings.md`). `MeaRecording.info()` still needs that dataset to exist,
because it reads the channel count and the sample count off its *shape*.

So it is created **chunked and unallocated**: HDF5 writes no chunk until one is touched, so the
shape is real and the bytes are not there. Reading it back gives the fill value, which means
``trace_health`` reports the window as ``flat`` — ⭐ which is exactly what the real files do through
the published decoder, so a test that asserts "the app says the waveform did not decode" is testing
the real failure and not a mock of it.

The **spikes** are real, and they are the half that matters: MaxWell's on-chip detector writes them
uncompressed, so they need no plug-in, and they are what the shelf counts and what plan 003 colours
the chip map by.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

# ── the synthetic chip. ⛔ Deliberately not any real device. ─────────────────────────────────────
STRIDE = 13          #: the array's long axis (electrode = ey * STRIDE + ex)
N_ROWS = 5           #: its short axis — 65 pads in all
PITCH_UM = 12.5
FS_HZ = 20000.0      #: MaxWell's rate, and the one number here that is not invented: it is what
#:                      makes `duration_s = n_samples / sampling` come out at a plausible scale.
LSB_V = 6.294e-6     #: volts per count -> `lsb_uv` 6.294, the shape `RecordingInfo` reports
GAIN = 512.0
HPF_HZ = 300.0

#: The channels this "experimenter" routed, as (channel, electrode). ⭐ **Every other column**, which
#: is the sparse-routing case real data caught (`test_sparse_routing_does_not_fool_the_pitch`): the
#: smallest routed gap is twice the true pitch, so anything that measures pitch from the routed
#: spacing gets 25 µm instead of 12.5.
_ROUTED = [(i, ey * STRIDE + ex)
           for i, (ex, ey) in enumerate([(x, y) for y in range(0, N_ROWS, 2)
                                         for x in range(0, STRIDE, 2)])]


def routed() -> list[tuple[int, int]]:
    """The `(channel, electrode)` pairs `write_recording` routes by default."""
    return list(_ROUTED)


def _spike_table(n_samples: int, seed: int) -> np.ndarray:
    """A handful of spikes, unevenly spread across the routed channels.

    ⭐ **Uneven on purpose.** Plan 003 colours the chip map by spikes-per-second and needs a live end
    and a dead end of the scale to be visibly different; a uniform table would make every pad the
    same colour and the test would pass on a broken ramp. Channel 0 is busiest, and the last routed
    channel is deliberately **silent** — a pad that was recorded and heard nothing is a different
    fact from a pad that was never routed, and both must render as facts.
    """
    rng = np.random.default_rng(seed)
    rows: list[tuple[int, int, float]] = []
    for ch, _el in _ROUTED[:-1]:                       # the last one stays silent
        # Poisson around a rate that falls off across the array, so the counts differ from seed to
        # seed (two recordings on one shelf must not show the same number) while the busy end and
        # the quiet end stay where 003's colour ramp needs them.
        n = max(1, int(rng.poisson(40 / (ch + 1)))) if ch == 0 else int(rng.poisson(40 / (ch + 1)))
        if n == 0:
            continue
        frames = rng.integers(1, n_samples, size=n)
        amps = -rng.uniform(20.0, 120.0, size=n)
        rows += [(int(f), int(ch), float(a)) for f, a in zip(sorted(frames), amps, strict=True)]
    rows.sort()
    out = np.empty(len(rows), dtype=[("frameno", "<i8"), ("channel", "<i4"),
                                     ("amplitude", "<f4")])
    for i, (f, ch, a) in enumerate(rows):
        out[i] = (f + _FIRST_FRAME, ch, a)
    return out


#: Where the recording's frame counter starts. Non-zero because a real one is: spike times are
#: `(frameno - frame_nos[0]) / fs`, and a fixture that started at 0 would let an implementation that
#: forgot the subtraction pass.
_FIRST_FRAME = 1_000_000


def write_recording(path: str | Path, *, n_samples: int = 60_000, run_id: str = "",
                    seed: int = 7) -> Path:
    """Write one synthetic ``data.raw.h5`` at `path`, creating its parents. -> the path.

    `n_samples` at :data:`FS_HZ` is the duration the shelf shows (60,000 = 3.0 s). It costs nothing
    on disk — see the module docstring on the unallocated raw stream. `run_id` defaults to the
    parent folder's name, which is where a real file's run id comes from when the header is silent.
    """
    import h5py

    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    n_ch = len(_ROUTED)

    with h5py.File(p, "w") as f:
        g = f.create_group("data_store/data0000")
        s = g.create_group("settings")
        s["sampling"] = np.array([FS_HZ])
        s["lsb"] = np.array([LSB_V])
        s["gain"] = np.array([GAIN])
        s["hpf"] = np.array([HPF_HZ])

        m = np.empty(n_ch, dtype=[("channel", "<i4"), ("electrode", "<i4"),
                                  ("x", "<f8"), ("y", "<f8")])
        for i, (ch, el) in enumerate(_ROUTED):
            m[i] = (ch, el, (el % STRIDE) * PITCH_UM, (el // STRIDE) * PITCH_UM)
        s["mapping"] = m

        rg = g.create_group("groups/routed")
        rg["channels"] = np.array([c for c, _ in _ROUTED], dtype=np.uint16)
        # ⚠️ shuffle+gzip, and not for tidiness: uncompressed this one dataset is 8 bytes ×
        # n_samples and would be 480 kB of the file on its own — larger than everything else put
        # together, and committed. It is a plain `arange`, and `shuffle` is what makes that
        # compress: gzip alone manages only 5:1 because consecutive uint64s differ in their LOW
        # byte, while shuffle groups the seven identical high bytes together first. Measured 480 kB
        # -> 91 kB (gzip) -> under 2 kB (shuffle+gzip). Both filters are HDF5 built-ins, so this
        # needs no plug-in — unlike the raw stream, which is the whole point of the header above.
        rg.create_dataset("frame_nos",
                          data=np.arange(_FIRST_FRAME, _FIRST_FRAME + n_samples, dtype=np.uint64),
                          chunks=(min(n_samples, 8192),), shuffle=True,
                          compression="gzip", compression_opts=9)
        # ⭐ Declared, chunked, and never written to — the shape is real, the bytes are not there.
        rg.create_dataset("raw", shape=(n_ch, n_samples), dtype="<u2",
                          chunks=(n_ch, min(n_samples, 4096)))

        g["spikes"] = _spike_table(n_samples, seed)
        f["assay/run_id"] = np.array([(run_id or p.parent.name).encode()])
    return p


def write_session(root: str | Path, *, plate: str = "P0000", assay: str = "Network",
                  runs: tuple[str, ...] = ("000001", "000002"), **kw) -> list[Path]:
    """The folder shape a MaxLab session actually has — ``<plate>/<assay>/<run>/data.raw.h5``.

    This is what the import screen browses to: the user points at a folder and Camea lists every
    recording *underneath* it, which is only a meaningful gesture when there is more than one.

    ⚠️ Each run gets a different `seed`, so two recordings on one shelf are not byte-identical rows.
    A shelf that showed the same spike count twice would pass just as happily if the second row were
    rendering the first one's numbers.
    """
    root = Path(root)
    kw.pop("seed", None)
    return [write_recording(root / plate / assay / r / "data.raw.h5", run_id=r, seed=7 + i, **kw)
            for i, r in enumerate(runs)]


__all__ = ["FS_HZ", "LSB_V", "N_ROWS", "PITCH_UM", "STRIDE", "routed", "write_recording",
           "write_session"]

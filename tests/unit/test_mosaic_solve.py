"""The engine adapter — `camea.legacy.mosaic.solve`.

Six things are pinned here, and every one of them is a bug this project has already paid for:

  1. ⭐ **The incremental composite is BIT-IDENTICAL to `t33.composite`** — at every step of an
     incremental sweep, on the append path AND on each fallback path. The whole class is a
     performance trick on the array the matcher correlates against; "close" is not a thing it may be.
  2. ⭐⭐ **`cache_key` IS the anchor set + their positions + the refusal set.** It is the prefetch's
     correctness guarantee: press `E` instead of `A` and the key must genuinely differ, or the memo
     hands back an answer computed against a composite that includes a tile the user just threw out.
  3. ⛔ **A blank TARGET refuses; a blank ANCHOR is DROPPED, not fatal.** The rule that made a blank
     anchor an error dead-ended the app: the sweep died at tile 35, forever.
  4. ⭐ **`world = m0 + (dx, dy)`, and positions are TOP-LEFT corners.** Off-by-256 is the classic bug.
  5. 🔴 **The stdout scraper must not believe t27's inner `[done]`.** t33 runs t27 *inside* itself;
     scraped naively, pass 1's own "done" sends the bar to 100 % and then back to 20 %.
  6. ⛔ **No dataset knowledge.** No trial number is special; the refusal set is an ARGUMENT.

These run on **synthetic pixels**. They need no data mirror, no GPU and no ground truth — the science
is the 312/312 guard's job (`tests/slow/`), and this file is the *plumbing's*.
"""
from __future__ import annotations

import ast
import importlib
import inspect
from pathlib import Path

import numpy as np
import pytest

from camea.core.frames import FrameStore, Tone
from camea.engine import t33
from camea.legacy.mosaic import solve

# ⭐ RETIRED, NOT REMOVED (2026-08-11). The snapshot mosaic builder moved to `camea.legacy.mosaic`
# and is no longer offered for new projects, so its suites are deselected from the fast run —
# `uv run pytest -q` skips this file, `uv run pytest -m legacy -q` still runs it, and it still
# passes. It is deselected because nobody is changing this feature, NOT because it is broken.
#
# ⚠️ `test_solve_is_the_ONLY_module_under_src_that_imports_t27_or_t33` lives here, and it is a
# whole-`src/` invariant, not a feature test. It is deselected with the rest — if a NEW second
# entry point into the engine is ever added, `uv run pytest -m legacy` is what catches it.
pytestmark = pytest.mark.legacy

TILE = solve.TILE
SRC = Path(__file__).resolve().parents[2] / "src" / "camea"


# =================================================================================================
# Fixtures — a synthetic session
# =================================================================================================
def _store(frames: np.ndarray, trials: list[int]) -> FrameStore:
    """A `FrameStore` over pixels we made up. Nothing here touches disk."""
    return FrameStore(
        trials=list(trials),
        frames=np.ascontiguousarray(frames, np.float32),
        flat_n=np.ones(frames.shape[1:], np.float32),
        tone=Tone(lo=0.0, hi=1.0, level=1.0),
        metas={t: {"trial": t, "flip_x": True, "flip_y": True} for t in trials},
    )


@pytest.fixture
def noise_store() -> FrameStore:
    """Six unrelated 512x512 frames. Enough to exercise the composite; no scene structure."""
    rng = np.random.default_rng(7)
    frames = rng.normal(2000.0, 300.0, (6, TILE, TILE)).astype(np.float32)
    return _store(frames, [11, 12, 13, 14, 15, 16])


@pytest.fixture(scope="module")
def scene() -> dict:
    """A synthetic SCENE, and two 512x512 windows cut out of it at a KNOWN offset.

    This is the only test in the file that asserts a *placement*: it exists to pin the arithmetic
    `world_topleft = m0 + (dx, dy)`, which is the one that goes wrong by exactly 512 px (or 256, if
    somebody confuses a corner with a centre).
    """
    rng = np.random.default_rng(11)
    dx, dy = 200, 60                      # overlap = (512-200)*(512-60) = 141,024 px > ANCHOR_MINABS
    big = rng.normal(2000.0, 300.0, (TILE + dy, TILE + dx)).astype(np.float32)
    a = big[0:TILE, 0:TILE]
    b = big[dy:dy + TILE, dx:dx + TILE]
    return {"store": _store(np.stack([a, b]), [11, 12]), "dx": float(dx), "dy": float(dy)}


@pytest.fixture(autouse=True)
def _clean_caches():
    """Every test starts on a cold composite cache and an empty memo. They are module-level."""
    solve.reset_caches()
    yield
    solve.reset_caches()


class Q:
    """The child's `mp.Queue`, minus the process."""

    def __init__(self) -> None:
        self.msgs: list[dict] = []

    def put(self, m: dict) -> None:
        self.msgs.append(m)

    def progress(self) -> list[dict]:
        return [m for m in self.msgs if m.get("type") == "progress"]


# =================================================================================================
# 1. ⭐ THE INCREMENTAL COMPOSITE IS BIT-IDENTICAL TO t33.composite
# =================================================================================================
def _truth(store: FrameStore, anchors: list[int], pos: dict) -> tuple:
    """What `t33.composite` — the engine, unassisted — says. The only reference that counts."""
    ts = sorted(anchors)
    rows = [store.row_of[t] for t in ts]
    local = np.array([pos[t] for t in ts], float)
    return t33.composite(store.band, rows, local)


def test_composite_matches_t33_on_an_incremental_sweep(noise_store):
    """⭐ Anchor tiles one at a time, in trial order — the hot path — and check EVERY step.

    The cache only ever APPENDS, in `k` order, into a canvas grown by a pure integer paste. Float
    addition is not associative, but it IS deterministic, so the partial sum after `m` tiles is
    bit-for-bit the prefix of the full sum. `array_equal`, not `allclose`.
    """
    pos = {11: (0.0, 0.0), 12: (110.0, 0.0), 13: (220.0, 0.0),
           14: (330.0, 40.0), 15: (440.0, 40.0), 16: (550.0, 90.0)}
    for k in range(1, 7):
        anchors = noise_store.trials[:k]
        img, msk, m0 = solve.composite_of(noise_store, anchors, pos)
        timg, tmsk, tm0 = _truth(noise_store, anchors, pos)
        assert np.array_equal(img, timg), f"composite diverged from t33 at {k} anchors"
        assert np.array_equal(msk, tmsk), f"mask diverged from t33 at {k} anchors"
        assert np.array_equal(np.asarray(m0), np.asarray(tm0)), f"m0 diverged at {k} anchors"

    assert solve.cache_stats()["composite_hits"] >= 5, "the append path never fired"


def test_composite_matches_t33_when_an_anchor_MOVES(noise_store):
    """A re-dragged anchor breaks precondition 2 (the old list is no longer a prefix with the same
    positions). It must REBUILD — and still agree with t33 exactly."""
    pos = {11: (0.0, 0.0), 12: (110.0, 0.0), 13: (220.0, 0.0)}
    solve.composite_of(noise_store, [11, 12, 13], pos)
    before = solve.cache_stats()["composite_rebuilds"]

    pos[12] = (117.0, 5.0)                                   # he dragged it
    img, msk, m0 = solve.composite_of(noise_store, [11, 12, 13], pos)
    timg, tmsk, tm0 = _truth(noise_store, [11, 12, 13], pos)

    assert solve.cache_stats()["composite_rebuilds"] == before + 1, "it took the append path anyway"
    assert np.array_equal(img, timg)
    assert np.array_equal(msk, tmsk)
    assert np.array_equal(np.asarray(m0), np.asarray(tm0))


def test_composite_matches_t33_when_m0_MOVES_BY_A_FRACTION(noise_store):
    """⚠️ **PRECONDITION 3 — the subtle one.** `P = rint(local - m0)`, and `m0 = local.min(0)`. A new
    tile that pushes `m0` by a NON-INTEGER amount can change the rounding *per tile* (x=0.4 with
    m0=0.0 rounds to 0; with m0=-0.3 it rounds to 1 — while x=1.6 rounds to 2 in both). That is not a
    translation, and pasting the old canvas would be wrong. The check must catch it and rebuild."""
    pos = {11: (0.4, 0.0), 12: (110.0, 0.0), 13: (-0.3, 90.0)}
    solve.composite_of(noise_store, [11, 12], pos)
    img, msk, m0 = solve.composite_of(noise_store, [11, 12, 13], pos)   # m0 moves by -0.3
    timg, tmsk, tm0 = _truth(noise_store, [11, 12, 13], pos)
    assert np.array_equal(img, timg), "the fractional-m0 paste was accepted and it is WRONG"
    assert np.array_equal(msk, tmsk)
    assert np.array_equal(np.asarray(m0), np.asarray(tm0))


def test_composite_is_order_independent(noise_store):
    """The contract says anchor order is irrelevant. The server sorts — that canonical order is what
    lets the incremental cache and the memo key agree."""
    pos = {11: (0.0, 0.0), 12: (110.0, 0.0), 13: (220.0, 0.0)}
    a = solve.composite_of(noise_store, [13, 11, 12], pos)
    solve.reset_caches()
    b = solve.composite_of(noise_store, [11, 12, 13], pos)
    assert np.array_equal(a[0], b[0]) and np.array_equal(a[1], b[1])


def test_a_new_session_does_not_reuse_the_old_ones_pixels():
    """⭐ The cache token is the store's **nonce**, not `id(band)` — CPython recycles `id()` (measured:
    4 of 5 same-size allocations reused an address), and two sessions of the same dataset with the
    same frame count genuinely collided."""
    rng = np.random.default_rng(3)
    one = _store(rng.normal(2000, 300, (2, TILE, TILE)).astype(np.float32), [11, 12])
    two = _store(rng.normal(9000, 300, (2, TILE, TILE)).astype(np.float32), [11, 12])
    assert one.nonce != two.nonce

    pos = {11: (0.0, 0.0), 12: (110.0, 0.0)}
    a, _, _ = solve.composite_of(one, [11, 12], pos)
    b, _, _ = solve.composite_of(two, [11, 12], pos)
    assert not np.array_equal(a, b), "the second session was served the FIRST session's pixels"
    assert np.array_equal(b, _truth(two, [11, 12], pos)[0])


def test_the_solver_is_512_only_and_says_so():
    """The 512x512 gate is mosaic's policy (512 is `t33.TILE`); core holds whatever the XML said. If
    an off-shape store ever reached the matcher the feather would paste at the wrong stride and the
    answer would be silently, plausibly wrong. Fail loudly."""
    small = _store(np.zeros((2, 128, 128), np.float32), [11, 12])
    with pytest.raises(ValueError, match="512x512-only"):
        solve.composite_of(small, [11], {11: (0.0, 0.0)})


# =================================================================================================
# 2. ⭐⭐ cache_key — THE PREFETCH'S CORRECTNESS GUARANTEE
# =================================================================================================
def _key(**kw) -> str:
    base = dict(nonce="n1", target=13, anchors=[11, 12],
                positions={11: (0.0, 0.0), 12: (110.0, 0.0)},
                mode="global", near=None, radius=64, max_candidates=9, refuse=())
    base.update(kw)
    return solve.cache_key(**base)


def test_cache_key_ignores_anchor_ORDER():
    assert _key(anchors=[11, 12]) == _key(anchors=[12, 11])


def test_pressing_E_instead_of_A_produces_a_DIFFERENT_key():
    """🔴 **THE TRAP.** The front end prefetches tile N+1 assuming the user will press `A`, so the
    prefetch's composite INCLUDES the tile under judgement. If he presses `E` the anchor set genuinely
    differs — the key must differ, the memo must MISS, and the server must recompute honestly.
    (Prefetching from a composite without the tile disagrees with the truth in 18 % of presses and is
    catastrophically wrong — up to 1,143 px — in 6 %.)"""
    pressed_a = _key(target=14, anchors=[11, 12, 13],
                     positions={11: (0.0, 0.0), 12: (110.0, 0.0), 13: (220.0, 0.0)})
    pressed_e = _key(target=14, anchors=[11, 12],
                     positions={11: (0.0, 0.0), 12: (110.0, 0.0), 13: (220.0, 0.0)})
    assert pressed_a != pressed_e


def test_moving_an_anchor_changes_the_key():
    assert _key(positions={11: (0.0, 0.0), 12: (110.0, 0.0)}) != \
           _key(positions={11: (0.0, 0.0), 12: (111.0, 0.0)})


def test_the_REFUSAL_SET_is_part_of_the_key():
    """⚠️ In v1 the refusal set was hidden state on the session that `PUT /api/scan/blank` mutated —
    which is precisely what made `POST /api/match/anchor` **not** a pure function of its request body.
    It now travels in the body, so it must be in the key."""
    assert _key(refuse=()) != _key(refuse=[12])
    assert _key(refuse=[12, 34]) == _key(refuse=[34, 12]), "the refusal set is a SET"


def test_a_different_session_cannot_hit_another_ones_memo():
    assert _key(nonce="n1") != _key(nonce="n2")


def test_cache_key_takes_str_or_int_position_keys():
    """Positions arrive from JSON with string keys and from python with int keys."""
    assert _key(positions={11: (0.0, 0.0), 12: (110.0, 0.0)}) == \
           _key(positions={"11": (0.0, 0.0), "12": (110.0, 0.0)})


def test_a_missing_anchor_position_is_an_error_not_a_guess():
    with pytest.raises(KeyError):
        _key(anchors=[11, 12, 13])


# =================================================================================================
# 3. ⛔ REFUSAL — the target is fatal; an anchor is DROPPED
# =================================================================================================
def test_a_blank_TARGET_is_refused_not_scored(noise_store):
    """⛔ Two blank frames 136 trials apart correlate **+0.43 at zero shift** (noise floor 0.115),
    because what they share is fixed-pattern SENSOR structure, which does not move with the stage.
    **They register confidently and wrongly.** There is no `force` flag and there will not be one."""
    r = solve.match_anchor(noise_store, 13, [11, 12],
                           {11: (0.0, 0.0), 12: (110.0, 0.0)}, refuse=[13], threshold=60.1)
    assert r.candidates == [] and r.best is None
    assert r.composite is None
    assert r.refused["reason"] == "blank"
    assert r.refused["trials"] == [13]
    assert r.refused["threshold"] == pytest.approx(60.1)
    assert r.refused["texture"] is not None            # the MEASURE, for the message. Not a verdict.


def test_a_blank_ANCHOR_is_dropped_and_the_sweep_SURVIVES(scene):
    """🔴 **THE RULE THAT DEAD-ENDED THE APP.** The old API said a blank *anchor* was an error too. The
    human ticks the refusal list himself, in trial order — so the moment he anchored trial 34, every
    subsequent `Space` and snap refused **forever** and the sweep died at tile 35.

    A refused anchor contributes **no pixels at all** to the correlation, is reported in
    `dropped_anchors`, and is **never fatal**.
    """
    store = scene["store"]
    frames = np.concatenate([store.frames, store.frames[:1]])      # a third tile to refuse
    s3 = _store(frames, [11, 12, 13])
    pos = {11: (0.0, 0.0), 13: (900.0, 900.0)}

    r = solve.match_anchor(s3, 12, [11, 13], pos, refuse=[13])
    assert r.refused is None, "a blank anchor must never be fatal"
    assert r.dropped_anchors == [13]
    assert r.n_anchors == 1, "the dropped anchor still counted toward the aperture"
    assert r.best is not None
    assert r.best.x == pytest.approx(scene["dx"], abs=1.0)
    assert r.best.y == pytest.approx(scene["dy"], abs=1.0)


def test_every_anchor_blank_is_no_anchors(noise_store):
    r = solve.match_anchor(noise_store, 13, [11, 12],
                           {11: (0.0, 0.0), 12: (110.0, 0.0)}, refuse=[11, 12])
    assert r.refused["reason"] == "no_anchors"
    assert r.refused["trials"] == [11, 12]
    assert r.candidates == []


def test_score_at_refuses_a_blank_target_too(noise_store):
    out = solve.score_at(noise_store, 13, [11, 12],
                         {11: (0.0, 0.0), 12: (110.0, 0.0)}, at=(220.0, 0.0), refuse=[13])
    assert out["ncc"] is None and out["refused"]["reason"] == "blank"


def test_nothing_is_refused_by_TRIAL_NUMBER(noise_store):
    """⛔ **THE STANDING RULING.** The refusal set is an ARGUMENT. With an empty one, every trial —
    including any number some other tool once threw out — matches like any other."""
    for t in (13, 284, 348):
        s = _store(noise_store.frames, [11, 12, t]) if t != 13 else noise_store
        r = solve.match_anchor(s, t, [11, 12], {11: (0.0, 0.0), 12: (110.0, 0.0)})
        assert r.refused is None, f"trial {t} was refused and NOTHING asked for that"


# =================================================================================================
# 4. ⭐ world = m0 + (dx, dy) — and the memo
# =================================================================================================
def test_match_finds_the_true_offset_and_reports_a_TOP_LEFT(scene):
    """⭐ Positions are **world TOP-LEFT corners**, never centres. Off-by-256 is the classic bug here."""
    r = solve.match_anchor(scene["store"], 12, [11], {11: (0.0, 0.0)})
    assert r.refused is None and r.best is not None
    assert r.best.rank == 0 and r.best.subpixel is True
    assert r.best.x == pytest.approx(scene["dx"], abs=1.0)
    assert r.best.y == pytest.approx(scene["dy"], abs=1.0)
    assert r.best.ncc > 0.5
    assert r.composite["m0"] == [0.0, 0.0]
    assert r.n_anchors == 1
    assert r.cached is False


def test_the_anchor_field_is_TRANSLATION_EQUIVARIANT(scene):
    """Anchor 11 at (1000, 500) and the answer moves with it, exactly. (`world = m0 + (dx, dy)`, and
    `m0` is `local.min(0)`.)"""
    r = solve.match_anchor(scene["store"], 12, [11], {11: (1000.0, 500.0)})
    assert r.composite["m0"] == [1000.0, 500.0]
    assert r.best.x == pytest.approx(1000.0 + scene["dx"], abs=1.0)
    assert r.best.y == pytest.approx(500.0 + scene["dy"], abs=1.0)


def test_local_mode_snaps_a_drag_back(scene):
    """`S` — the snap. The committed number is the SERVER's: a JS pre-snap is alias-safe only within
    ~±48 px, and the electrode grid repeats every 256."""
    dropped = (scene["dx"] + 9.0, scene["dy"] - 7.0)
    r = solve.match_anchor(scene["store"], 12, [11], {11: (0.0, 0.0)},
                           mode="local", near=dropped, radius=32)
    assert r.mode == "local" and r.best is not None
    assert r.best.x == pytest.approx(scene["dx"], abs=1.0)
    assert r.best.y == pytest.approx(scene["dy"], abs=1.0)


def test_local_mode_without_near_is_an_error(scene):
    with pytest.raises(ValueError, match="requires `near`"):
        solve.match_anchor(scene["store"], 12, [11], {11: (0.0, 0.0)}, mode="local")


def test_score_at_measures_where_you_dropped_it(scene):
    """The live NCC under the cursor. It agrees with the match's own score at the match's position."""
    at = (scene["dx"], scene["dy"])
    out = solve.score_at(scene["store"], 12, [11], {11: (0.0, 0.0)}, at=at)
    assert out["ncc"] is not None and out["ncc"] > 0.5
    assert out["npix"] > 3000
    assert out["refused"] is None


def test_score_at_says_NOT_MEASURABLE_never_zero(scene):
    """⚠️ `ncc` is **`None`** below `exact_ncc`'s floor (< 3,000 valid px, or < 64 px on a side). The
    honest answer is *"not measurable"*. **Never `0.0`** — a 0.0 reads as "measured, and bad"."""
    out = solve.score_at(scene["store"], 12, [11], {11: (0.0, 0.0)}, at=(5000.0, 5000.0))
    assert out["ncc"] is None
    assert out["npix"] == 0


def test_the_memo_serves_a_repeat_and_says_so(scene):
    """The prefetch IS the same call, fired early. A repeat must come back `cached: true` — that is
    what makes it free."""
    a = solve.match_anchor(scene["store"], 12, [11], {11: (0.0, 0.0)})
    b = solve.match_anchor(scene["store"], 12, [11], {11: (0.0, 0.0)})
    assert a.cached is False and b.cached is True
    assert a.cache_key == b.cache_key
    assert (b.best.x, b.best.y) == (a.best.x, a.best.y)
    assert solve.cache_stats()["memo_entries"] == 1


def test_reset_caches_empties_the_memo(scene):
    solve.match_anchor(scene["store"], 12, [11], {11: (0.0, 0.0)})
    assert solve.cache_stats()["memo_entries"] == 1
    solve.reset_caches()
    assert solve.cache_stats()["memo_entries"] == 0
    assert solve.match_anchor(scene["store"], 12, [11], {11: (0.0, 0.0)}).cached is False


def test_the_target_may_not_also_be_an_anchor(scene):
    with pytest.raises(ValueError, match="also listed as an anchor"):
        solve.match_anchor(scene["store"], 11, [11], {11: (0.0, 0.0)})


def test_a_trial_outside_the_session_is_a_KeyError(scene):
    with pytest.raises(KeyError):
        solve.match_anchor(scene["store"], 99, [11], {11: (0.0, 0.0)})


def test_match_needs_at_least_one_anchor(scene):
    with pytest.raises(ValueError, match="at least one anchor"):
        solve.match_anchor(scene["store"], 12, [], {})


# =================================================================================================
# 5. 🔴 THE STDOUT SCRAPER — t33 has no progress callback
# =================================================================================================
def _sink(n_total: int = 312, gpu: bool = True) -> tuple[solve._ProgressSink, Q]:
    q = Q()
    w = solve.PHASE_WEIGHT_GPU if gpu else solve.PHASE_WEIGHT_CPU
    return solve._ProgressSink(q, t0=0.0, n_total=n_total, weights=w), q


def test_the_scraper_does_NOT_believe_t27s_INNER_done():
    """🔴 **THE BUG THIS GUARD EXISTS FOR.** t33 runs t27 *inside* itself and lets its narration
    through. t27 prints its own `[done] placed 156 snapshots` when pass 1 finishes — **a third of the
    way into the build**. Scraped naively, the bar goes to **100 %** and then back to 20 %."""
    sink, q = _sink(n_total=312)
    sink.write("[   1.0s] STEP 1 — PASS 1 (t27)\n")
    sink.write("[  90.0s] [done] placed 156 snapshots\n")          # t27's. NOT the build's.
    assert sink.phase != "done"
    assert all(p["pct"] < 100.0 for p in q.progress()), "the inner [done] took the bar to 100 %"

    sink.write("[ 500.0s] [done] placed 312 snapshots\n")          # t33's. The real one.
    assert sink.phase == "done"
    assert q.progress()[-1]["pct"] == 100.0


def test_a_phase_never_goes_BACKWARDS():
    sink, q = _sink()
    sink.write("[  1.0s] STEP 3 — PER-TILE ANCHORS: each pass-2 tile\n")
    at_anchors = q.progress()[-1]["pct"]
    sink.write("[  2.0s] STEP 1 — PASS 1 (t27)\n")                 # a stray earlier-looking line
    assert sink.phase == "anchors"
    assert q.progress()[-1]["pct"] >= at_anchors


def test_pass1_MOVES_instead_of_sitting_at_zero_for_four_minutes():
    """🔴 On the CPU-only path — **the shipped default** — pass 1 + backbone are **75 % of the build**,
    and the bar used to sit at **0.0 %, with no ETA, for 3 min 40 s**. A lab-mate who cancels that has
    cancelled a build that would have produced 312/312. t27's own narration was always there; it was
    simply never scraped."""
    sink, q = _sink(gpu=False)
    sink.write("[  1.0s] STEP 1 — PASS 1 (t27, frozen reference)\n")
    start = q.progress()[-1]["pct"]
    sink.write("[  3.0s] [data] 312 snapshots, trials 11..348\n")
    sink.write("[  9.0s] [data] band-passed (DoG 3-30)\n")
    sink.write("[ 60.0s] [swim] 4,800 pairs in 51.0s\n")
    sink.write("[ 70.0s] [validate] batched NCC agrees\n")
    pcts = [p["pct"] for p in q.progress()]
    assert pcts == sorted(pcts), "the bar went backwards inside pass 1"
    assert pcts[-1] > start, "pass 1 emitted no intra-phase progress at all"
    assert q.progress()[-1]["message"].startswith("pass 1 (t27, frozen reference) — ")


def test_the_run_rows_are_counted_by_a_SET_not_a_counter():
    """⚠️ t33 prints its MARGIN TABLE after the run loop, and those rows look **exactly** like run
    rows. A set is what stops them being counted twice (and `before` is what stops it re-emitting 11
    identical 100 % messages)."""
    sink, q = _sink()
    sink.write("[100.0s] STEP 5 — COMPOSITE-TO-COMPOSITE\n")
    sink.write("[101.0s] pass 2 -> 3 runs\n")
    for r in (0, 1, 2):
        sink.write(f"[10{r + 2}.0s]   R{r} 42 tiles\n")
    assert sink.frac == pytest.approx(1.0)
    n_run_msgs = len([p for p in q.progress() if p["message"].startswith("placed run")])
    for r in (0, 1, 2):                                            # the margin table, again
        sink.write(f"[11{r}.0s]   R{r} 42 0.47\n")
    assert sink.runs_seen == {0, 1, 2}
    assert len([p for p in q.progress() if p["message"].startswith("placed run")]) == n_run_msgs


def test_the_CPU_and_GPU_curves_are_DIFFERENT():
    """🔴 There are two weight tables and there have to be. On the GPU the anchor loop is 53 % of the
    build; on the CPU pass 1 + backbone are 75 % of it. One GPU-calibrated table told a CPU user
    "~873 s left" when 368 s remained."""
    out = {}
    for gpu in (True, False):
        sink, q = _sink(gpu=gpu)
        sink.write("[100.0s] STEP 3 — PER-TILE ANCHORS: each pass-2 tile\n")
        out[gpu] = q.progress()[-1]["pct"]
    assert out[True] != out[False]
    assert solve.PHASE_WEIGHT_CPU["backbone"] > solve.PHASE_WEIGHT_GPU["backbone"]
    assert solve.PHASE_WEIGHT_GPU["anchors"] > solve.PHASE_WEIGHT_CPU["anchors"]
    for w in (solve.PHASE_WEIGHT_GPU, solve.PHASE_WEIGHT_CPU):
        assert sum(w.values()) == pytest.approx(1.0)
        assert set(w) == set(solve.PHASES)


def test_every_raw_line_reaches_the_log_tail():
    sink, q = _sink()
    sink.write("[  1.0s] something t33 said\n[  2.0s] and another\n")
    assert [m["line"] for m in sink.q.msgs if m["type"] == "log"] == \
           ["[  1.0s] something t33 said", "[  2.0s] and another"]


def test_the_eta_is_None_until_the_bar_has_actually_moved():
    """`eta = elapsed * (100 - pct) / pct` is meaningless at pct ~= 0. `None` is the honest answer, and
    the front end shows no countdown rather than a fantasy one."""
    sink, q = _sink()
    sink.write("[  1.0s] STEP 1 — PASS 1 (t27)\n")
    assert q.progress()[-1]["eta_s"] is None


# =================================================================================================
# 6. THE BUILD — config, result, and the spawn target
# =================================================================================================
def test_make_config_REFUSES_to_default_the_pass_split():
    """⛔⛔ **t33.Config's default `pass_split` is 166 — that is 260620d's measured number.** Letting it
    apply silently is *exactly* the dataset knowledge the app is forbidden to carry."""
    with pytest.raises(ValueError, match="no dataset knowledge"):
        solve.make_config(None)
    with pytest.raises(ValueError, match="no dataset knowledge"):
        solve.make_config({"anchor_ncc": 0.3})


def test_make_config_takes_the_DETECTED_split_and_an_override():
    assert solve.make_config(None, pass_split=140).pass_split == 140
    assert solve.make_config({}, pass_split=140).pass_split == 140
    # the Advanced drawer wins: the detection is a DEFAULT, and it is always overridable
    assert solve.make_config({"pass_split": 99}, pass_split=140).pass_split == 99


def test_make_config_lets_t33_reject_an_unknown_knob():
    """⛔ Do not hard-code the knob list. `t33.Config.__init__` raises `TypeError` itself — that is the
    validation, and it cannot drift from t33."""
    with pytest.raises(TypeError, match="unknown T33 config knob"):
        solve.make_config({"speed": 11}, pass_split=140)


def test_make_config_builds_the_nested_t27_config():
    cfg = solve.make_config({"t27": {"control": True}}, pass_split=140)
    assert cfg.t27 is not None and cfg.t27.control is True


def test_build_result_records_WHAT_THE_SOLVER_WAS_GIVEN():
    """⭐ `trials` + `gaps` are what the solver was **actually handed**. Without them the document can
    never know its build was solved on a different input, and the staleness check degenerates into
    comparing the current trial list with itself. Excluding a mid-run tile opens a GAP, and across a
    gap the serpentine one-step prior does NOT hold."""
    trials = [11, 12, 13, 20, 21]                      # 13 -> 20 is a multi-step jump
    pos = {11: (0.0, 0.0), 12: (100.0, 0.0), 13: (200.0, 0.0), 20: (300.0, 0.0)}
    out = solve.build_result(pos, {"seconds": 12.5, "gpu": True}, trials, pass_split=12)

    assert out["trials"] == trials
    assert out["gaps"] == [[13, 20]]
    assert out["unplaced"] == [21]
    assert out["n_placed"] == 4
    assert out["positions"]["11"] == [0.0, 0.0]       # JSON has no integer keys
    assert out["pass_split"] == 12
    assert out["seconds"] == 12.5 and out["gpu"] is True
    assert out["per_tile"]["11"]["pass"] == 1
    assert out["per_tile"]["13"]["pass"] == 2


def test_build_result_survives_a_t27_Config_inside_info():
    """⚠️ `info["config"]` holds a nested `t27.Config` and **`json.dumps(info)` CRASHES** without a
    coercer. And ⚠️ `t33.Config.t27` defaults to `None` — a faithful `vars()` dump writes `"t27": null`
    into the provenance, which tells a later reader **nothing** about which knobs produced these
    positions. Resolve the sentinel."""
    import json

    cfg = solve.make_config(None, pass_split=12)
    assert cfg.t27 is None                                   # the sentinel
    out = solve.build_result({11: (0.0, 0.0)}, {"config": cfg, "seconds": 1.0}, [11], pass_split=12)
    json.dumps(out)                                          # must not raise

    eff = out["info"]["config"]["t27"]
    assert isinstance(eff, dict) and eff, "the t27 sentinel was written to the record as null"
    assert "t27_source" in out["info"]["config"]


def test_build_result_resolves_the_sentinel_on_a_WARM_CACHE_HIT_TOO():
    """⚠️ A warm cache hit hands back a **plain dict**, not a `t33.Config` (`t33._load_checked` rebuilds
    `info` from the file). Keying the fix on `hasattr(cfg, "t27_config")` made it a no-op on every
    cached build — **which is the common case**, and the one whose provenance was landing in the
    project file with `"t27": null`."""
    warm = {"config": {"pass_split": 166, "t27": None}, "seconds": 25.0}
    out = solve.build_result({11: (0.0, 0.0)}, warm, [11], pass_split=166)
    assert isinstance(out["info"]["config"]["t27"], dict)
    assert out["info"]["config"]["t27"], "the warm-cache path left t27 null"


def test_the_spawn_target_is_importable_by_its_DOTTED_PATH():
    """`core.jobs.submit_process` imports this in a **FRESH spawn interpreter**, by name, exactly as
    below. If the module ever moves and this string does not, every build dies in the child with an
    ImportError — and the only symptom is a job that failed before it printed anything.

    (Identity is deliberately *not* asserted: this must hold in a brand-new interpreter that has never
    seen our `solve` object.)
    """
    mod_name, _, fn_name = solve.BUILD_TARGET.rpartition(".")
    fn = getattr(importlib.import_module(mod_name), fn_name)      # <- `jobs._process_entry`, verbatim
    assert callable(fn)
    assert fn.__module__ == "camea.legacy.mosaic.solve"
    assert fn.__name__ == "build_worker"
    # `_process_entry` calls it as `fn(queue=q, **kwargs)` — `queue` MUST be a keyword parameter.
    assert "queue" in inspect.signature(fn).parameters


def test_build_worker_reports_a_failure_on_the_QUEUE_never_raises():
    """A crash in the child must reach the user as a job error, not vanish with the process."""
    q = Q()
    solve.build_worker(data_dir="D:/nope/not/a/dataset", trials=[11, 12], pass_split=11, queue=q)
    err = [m for m in q.msgs if m["type"] == "error"]
    assert len(err) == 1
    assert err[0]["error"]["code"] == "job_failed"
    assert err[0]["error"]["traceback"]


# =================================================================================================
# 7. ⛔ NO DATASET KNOWLEDGE, AND ONE ENGINE
# =================================================================================================
def test_solve_carries_no_dataset_knowledge():
    """⛔ **THE STANDING RULING.** The app hard-coded 26 excluded trial numbers for one acquisition and
    auto-applied them — "it answered, on the user's behalf, the exact question the app exists to help
    him answer". It was ripped out at real cost. The only symbol importable from the exclusion module
    is `gaps()`, a pure function over a trial list.

    ⚠️ This reads the **AST**, not the text: the module names these symbols in its own *"and here is
    why we do not import them"* comment, which is the note that keeps the next agent from putting them
    back. A grep would forbid the warning along with the sin.
    """
    tree = ast.parse((SRC / "legacy" / "mosaic" / "solve.py").read_text(encoding="utf-8"))
    forbidden = {"EXCLUDED", "BLANK", "BLURRY", "usable_trials", "BLANK_THRESHOLD", "DATA_DIR"}

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for a in node.names:
                assert a.name not in forbidden, f"{a.name} imported from {node.module}"
        if isinstance(node, ast.Name):
            assert node.id not in forbidden, f"{node.id} is used in the code"
        if isinstance(node, ast.Attribute):
            assert node.attr not in forbidden, f".{node.attr} is reached for in the code"

    assert not (forbidden & set(vars(solve))), "a forbidden symbol reached the module namespace"

    # ⭐ And it reaches `gaps()` through `camea.core.dataset` — the ONE place in the app that touches
    #    the exclusion module — never by importing `camea.engine.excluded` itself.
    from camea.core import dataset as core_dataset
    from camea.engine import excluded as engine_excluded

    assert solve.gaps is core_dataset.gaps
    trials = [11, 12, 13, 20, 21]
    assert list(solve.gaps(trials)) == list(engine_excluded.gaps(trials)) == [(13, 20)]


def test_solve_is_the_ONLY_module_under_src_that_imports_t27_or_t33():
    """⭐ `docs/SPLIT.md` §0.5. Two entry points into the engine is how two copies of it get made."""
    hits = sorted(
        p.relative_to(SRC).as_posix()
        for p in SRC.rglob("*.py")
        if p.parent.name != "engine"
        and any(s in p.read_text(encoding="utf-8")
                for s in ("from camea.engine import t27", "from camea.engine import t33",
                          "import camea.engine.t27", "import camea.engine.t33"))
    )
    assert hits == ["legacy/mosaic/solve.py"], hits


def test_solve_does_not_import_the_api_layer():
    """The arrow is one-way: `api -> features -> core -> engine`. A feature that imports `camea.api`
    is a cycle, and it is how the contract stops being the contract."""
    src = (SRC / "legacy" / "mosaic" / "solve.py").read_text(encoding="utf-8")
    assert "camea.api" not in src


def test_the_build_memo_is_NOT_LIVE_at_rest():
    """⚠️ The memo monkey-patches `t33._pool`. v1 used a global `enable/disable` pair and nothing
    enforced that it was ever turned off — on a module the 312/312 guard also imports. It is a context
    manager now; importing `solve` must not patch anything."""
    assert t33._pool.__module__ == t33.__name__, "t33._pool is patched at import. The guard is blind."

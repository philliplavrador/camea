"""Pass 2 — keyframe-to-keyframe registration: measure links, validate them, refuse the bad.

A LINK is one measured statement "keyframe b sits at keyframe a + (dx, dy)". Three kinds:

- `seq`    — consecutive keyframes of one tracking segment. The prior (from pass 1) is good
             to a few px; the correction allowance is small.
- `cross`  — non-adjacent keyframes whose predicted footprints overlap (neighbouring rows of
             the serpentine, revisits). These are the drift killers: every one closes a loop
             that frame-to-frame chaining would let sag.
- `bridge` — across a tracking break (a black stretch), where there is NO usable prior: the
             full frames go through phase correlation cold, and only the validators decide.

Every measurement must pass ALL of: phase response, correction-vs-prior bound, minimum
actual overlap, and a zero-normalised cross-correlation over HIGH-PASSED crops at the
measured offset (high-passed so background residue and illumination ramps cannot move the
statistic; it is the arbiter that catches the electrode grid's false comb peaks — a
confidently wrong phase peak scores ~0.05 on the real pixels, a correct one ~0.6+).
Rejected links are kept with their reason: they are diagnostics, not garbage.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from .config import VideoConfig


@dataclass
class Link:
    a: int                      # keyframe indices into the keyframe LIST (not video frames)
    b: int
    kind: str                   # seq | cross | bridge
    dx: float = 0.0             # measured world offset pos_b - pos_a (full-res px)
    dy: float = 0.0
    response: float = 0.0
    ncc: float = 0.0
    overlap_px: int = 0
    correction_px: float = 0.0  # |measured - prior|
    ok: bool = False
    reject_reason: str | None = None

    def to_json(self) -> dict:
        return {"a": self.a, "b": self.b, "kind": self.kind,
                "dx": round(self.dx, 2), "dy": round(self.dy, 2),
                "response": round(self.response, 4), "ncc": round(self.ncc, 4),
                "overlap_px": self.overlap_px, "correction_px": round(self.correction_px, 1),
                "ok": self.ok, "reject_reason": self.reject_reason}


_HANN: dict[tuple[int, int], np.ndarray] = {}


def _hann(w: int, h: int) -> np.ndarray:
    win = _HANN.get((w, h))
    if win is None:
        win = cv2.createHanningWindow((w, h), cv2.CV_32F)
        if len(_HANN) > 64:
            _HANN.clear()
        _HANN[(w, h)] = win
    return win


def _overlap_crops(A: np.ndarray, B: np.ndarray, off: tuple[float, float],
                   ) -> tuple[np.ndarray, np.ndarray] | None:
    """Same-size crops of the region where B (placed at `off` relative to A) overlaps A.
    Crop sizes are floored to multiples of 16 (FFT-friendly, window-cacheable)."""
    h, w = A.shape
    dx, dy = int(round(off[0])), int(round(off[1]))
    x0, x1 = max(0, dx), min(w, dx + w)
    y0, y1 = max(0, dy), min(h, dy + h)
    cw, ch = (x1 - x0) // 16 * 16, (y1 - y0) // 16 * 16
    if cw < 32 or ch < 32:
        return None
    return (A[y0:y0 + ch, x0:x0 + cw], B[y0 - dy:y0 - dy + ch, x0 - dx:x0 - dx + cw])


def _zncc(a: np.ndarray, b: np.ndarray) -> float:
    a = a - a.mean()
    b = b - b.mean()
    denom = float(np.sqrt((a * a).sum() * (b * b).sum()))
    if denom < 1e-6:
        return 0.0
    return float((a * b).sum() / denom)


def measure_link(A: np.ndarray, B: np.ndarray, prior: tuple[float, float],
                 link: Link, cfg: VideoConfig) -> Link:
    """Measure `pos_b - pos_a` for full-res flattened frames A and B, seeded at `prior`.

    Derivation of the sign (kept here because it earns its keep): the crops are cut at the
    ROUNDED prior — call it r — so that at exactly r they would align; if the true offset is
    `r + e`, the B-crop's content is shifted by `-e` relative to the A-crop, and
    `measured = r - shift/scale`. Reconstructing from the un-rounded prior would leak its
    fractional part (up to 0.5 px/axis) into every link — measured, and pinned by a test.
    """
    h, w = A.shape
    frame_px = float(h * w)
    min_ov = (cfg.min_overlap_frac if link.kind != "cross" else cfg.cross_overlap_frac)

    rx, ry = float(round(prior[0])), float(round(prior[1]))
    crops = _overlap_crops(A, B, (rx, ry))
    if crops is None or crops[0].size < min_ov * frame_px:
        link.reject_reason = "no_overlap_at_prior"
        return link

    k = float(cfg.register_scale)
    ca = cv2.resize(crops[0], None, fx=k, fy=k, interpolation=cv2.INTER_AREA)
    cb = cv2.resize(crops[1], None, fx=k, fy=k, interpolation=cv2.INTER_AREA)
    (sx, sy), resp = cv2.phaseCorrelate(ca, cb, _hann(ca.shape[1], ca.shape[0]))
    link.response = float(resp)
    if resp < cfg.min_link_response:
        link.reject_reason = "weak_phase_response"
        return link

    ex, ey = -sx / k, -sy / k
    measured = (rx + ex, ry + ey)
    link.correction_px = float(np.hypot(measured[0] - prior[0], measured[1] - prior[1]))
    max_corr = {"seq": cfg.max_correction_seq_px,
                "cross": cfg.max_correction_cross_px,
                "bridge": float(np.hypot(w, h))}[link.kind]
    if link.correction_px > max_corr:
        link.dx, link.dy = measured
        link.reject_reason = "correction_too_large"
        return link

    # The arbiter: real pixels at the measured offset. A grid-comb false peak dies here.
    ver = _overlap_crops(A, B, measured)
    if ver is None or ver[0].size < min_ov * frame_px:
        link.dx, link.dy = measured
        link.reject_reason = "no_overlap_at_measured"
        return link
    va = cv2.resize(ver[0], None, fx=k, fy=k, interpolation=cv2.INTER_AREA)
    vb = cv2.resize(ver[1], None, fx=k, fy=k, interpolation=cv2.INTER_AREA)
    hp = max(2.0, cfg.verify_highpass_sigma * k)         # σ in crop-scale px
    va = va - cv2.GaussianBlur(va, (0, 0), hp)
    vb = vb - cv2.GaussianBlur(vb, (0, 0), hp)
    link.ncc = _zncc(va, vb)
    link.overlap_px = int(ver[0].size)
    link.dx, link.dy = measured
    if link.ncc < cfg.min_link_ncc:
        link.reject_reason = "low_ncc_at_measured"
        return link

    link.ok = True
    return link


def candidate_links(kf_pos: np.ndarray, kf_segment: np.ndarray, frame_wh: tuple[int, int],
                    cfg: VideoConfig, *, trust_all_priors: bool,
                    bridge_to_first: bool = False) -> list[Link]:
    """The pairs worth measuring, given current position estimates.

    `trust_all_priors=False` (round 0): positions are pass-1 estimates — comparable only
    within a segment, so overlap prediction is restricted to same-segment pairs, and segment
    boundaries get prior-less `bridge` candidates instead.
    `trust_all_priors=True` (refine rounds): positions come from a global solve — every pair
    with predicted overlap is fair game, whatever its segment.
    """
    n = len(kf_pos)
    w, h = frame_wh
    links: list[Link] = []
    seen: set[tuple[int, int]] = set()

    def add(a: int, b: int, kind: str) -> None:
        if a > b:
            a, b = b, a
        if a != b and (a, b) not in seen:
            seen.add((a, b))
            links.append(Link(a=a, b=b, kind=kind))

    same_gauge = (lambda i, j: True) if trust_all_priors \
        else (lambda i, j: kf_segment[i] == kf_segment[j])

    # sequential: i -> i+1 and i -> i+2 (redundancy is cheap and one bad frame must not
    # sever the chain)
    for i in range(n - 1):
        if same_gauge(i, i + 1):
            add(i, i + 1, "seq")
        if i + 2 < n and same_gauge(i, i + 2):
            add(i, i + 2, "seq")

    # cross: predicted-overlap pairs, closest first, capped per keyframe
    if n > 2:
        budget = np.full(n, cfg.max_cross_links_per_keyframe, int)
        cand: list[tuple[float, int, int]] = []
        for i in range(n):
            for j in range(i + 3, n):
                if not same_gauge(i, j):
                    continue
                dx = float(kf_pos[j, 0] - kf_pos[i, 0])
                dy = float(kf_pos[j, 1] - kf_pos[i, 1])
                ow = w - abs(dx)
                oh = h - abs(dy)
                if ow <= 0 or oh <= 0 or ow * oh < cfg.cross_overlap_frac * w * h:
                    continue
                cand.append((float(np.hypot(dx, dy)), i, j))
        cand.sort()
        for _, i, j in cand:
            if budget[i] > 0 and budget[j] > 0:
                add(i, j, "cross")
                budget[i] -= 1
                budget[j] -= 1

    # bridges: across segment boundaries there is no prior — offer the last few keyframes of
    # every earlier segment to the first few of each later one, cold
    if not trust_all_priors:
        segs = sorted(set(int(s) for s in kf_segment))
        by_seg = {s: [i for i in range(n) if kf_segment[i] == s] for s in segs}
        for si in range(1, len(segs)):
            heads = by_seg[segs[si]][:3]
            # Round 0: the 3 nearest earlier segments (temporal locality). Refine rounds pass
            # bridge_to_first — the ids are then solve COMPONENTS ordered by size, where
            # locality means nothing and the one bridge that matters is to the mosaic (id 0).
            targets = set(range(max(0, si - 3), si))
            if bridge_to_first:
                targets.add(0)
            for sj in sorted(targets):
                tails = by_seg[segs[sj]][-4:]
                for a in tails:
                    for b in heads:
                        add(a, b, "bridge")
    return links

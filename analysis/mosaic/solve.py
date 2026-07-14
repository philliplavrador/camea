"""Stages (4) backbone chain and (5) refine (loop-closure + Placement + IRLS).

SHARED by every build -- byte-for-byte identical regardless of how the pairwise shifts
were measured (that is match.py's job). `spectralign.Placement` is a single weighted
least-squares with NO outlier rejection, so we wrap it in IRLS trimming and only add
loop-closure links whose measured shift agrees with the current layout.
"""
import numpy as np
from spectralign import Placement

CTR = 256   # frame centre = tie point for whole-frame placement


def rigid(links, ctr=CTR):
    """Global translation-only solve -> {trial: (x, y)}, mean-centred."""
    plc = Placement()
    for a, b, sh, w in links:
        plc.addmatch(a, b, (ctr, ctr), (ctr - sh[0], ctr - sh[1]), weight=w)
    return plc.rigid()


def irls(links, r_drop, iters=5, ctr=CTR):
    """Placement.rigid has no outlier rejection -> trim links whose residual exceeds
    `r_drop` and re-solve, always keeping the consecutive backbone (b == a+1) for
    connectivity. Iterate until the kept set stops shrinking (or `iters` reached)."""
    keep = links
    for _ in range(iters):
        p = rigid(keep, ctr)
        nk = [(a, b, sh, w) for a, b, sh, w in keep
              if np.hypot(*(sh - (np.array(p[b]) - np.array(p[a])))) < r_drop or b == a + 1]
        if len(nk) == len(keep):
            break
        keep = nk
    return rigid(keep, ctr), keep


def _extent(pos, trials, tile=512):
    a = np.array([pos[t] for t in trials])
    return a.max(0) - a.min(0) + tile


def backbone_chain(matcher, tile=512):
    """(4) Accumulate consecutive-frame shifts (the serpentine path) into a first
    layout {trial: (x, y)}."""
    trials = matcher.trials
    cur = np.zeros(2)
    pos = {trials[0]: np.zeros(2)}
    for i in range(len(trials) - 1):
        step = matcher.backbone_step(i)
        cur = cur + (step if step is not None else np.zeros(2))
        pos[trials[i + 1]] = cur.copy()
    ext = _extent(pos, trials, tile)
    print(f"backbone chain extent {int(ext[0])} x {int(ext[1])} px")
    return pos


def refine(matcher, pos, schedule, overlap, tile=512, ctr=CTR):
    """(5) For each (agreement-tol, IRLS-drop) round in `schedule`: always add the
    consecutive backbone links, add loop-closure links for spatially-near
    non-consecutive pairs (distance < `overlap`) that agree with the current layout
    within `tol`, then solve Placement.rigid wrapped in IRLS(`r_drop`). Tightening the
    schedule is coarse-to-fine: loose first to pull the layout in, strict last."""
    trials = matcher.trials
    for rnd, (tol, r_drop) in enumerate(schedule, 1):
        P = np.array([pos[t] for t in trials])
        links = [matcher.backbone_link(i, P) for i in range(len(trials) - 1)]  # always kept
        D = np.hypot(*((P[:, None, :] - P[None, :, :]).transpose(2, 0, 1)))
        ii, jj = np.where((D < overlap) & np.triu(np.ones_like(D, bool), k=2))  # near, non-consecutive
        for i, j in zip(ii.tolist(), jj.tolist()):
            lk = matcher.loop_link(i, j, P, tol)
            if lk is not None:
                links.append(lk)
        pos, kept = irls(links, r_drop, ctr=ctr)
        ext = _extent(pos, trials, tile)
        extra = getattr(matcher, "stats", lambda: "")()
        print(f"round {rnd}: {len(ii)} loop candidates, {len(links)} links -> {len(kept)} kept; "
              f"extent {int(ext[0])}x{int(ext[1])} px" + (f"  ({extra})" if extra else ""))
    return pos

"""The global solve — one coherent coordinate system from many pairwise links.

Translation-only weighted least squares over the link graph (the motion IS translation:
measured rotation ≤0.1°, scale within ±0.2% on real survey video — and the snapshot science
in this repo settled the same question the same way). Chaining frame→frame would accumulate
drift along a 40 000+ px path; the cross links close those loops, and the least squares
spreads every closure's correction over the whole loop instead of leaving it at the seam.

Robustness is IRLS with a Huber weight, then a hard residual gate, then a re-solve — a link
that survived registration validation can still disagree with every loop it sits on, and the
solve is where that shows. Disconnected components each get their own gauge; the pipeline
renders the largest and says what it dropped.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .config import VideoConfig
from .register import Link


@dataclass
class SolveResult:
    pos: np.ndarray                     # (n,2) float64 — world top-left per keyframe
    component: np.ndarray               # (n,) int32 — component id, 0 = largest
    placed: np.ndarray                  # (n,) bool — member of the largest component
    dropped_links: int = 0
    residual_median: float = 0.0
    residual_p95: float = 0.0
    stats: dict = field(default_factory=dict)


def _components(n: int, links: list[Link]) -> np.ndarray:
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for l in links:
        ra, rb = find(l.a), find(l.b)
        if ra != rb:
            parent[ra] = rb
    roots = [find(i) for i in range(n)]
    # relabel: 0 = biggest component, then by size
    sizes: dict[int, int] = {}
    for r in roots:
        sizes[r] = sizes.get(r, 0) + 1
    order = {r: k for k, r in enumerate(sorted(sizes, key=lambda r: -sizes[r]))}
    return np.array([order[r] for r in roots], np.int32)


def _solve_component(nodes: list[int], links: list[Link], weights: np.ndarray,
                     ) -> dict[int, tuple[float, float]]:
    """Weighted LSQ for one connected component; node 0 of the component pins the gauge."""
    index = {node: i for i, node in enumerate(nodes)}
    m = len(nodes)
    L = np.zeros((m, m))
    cx = np.zeros(m)
    cy = np.zeros(m)
    for l, w in zip(links, weights):
        ia, ib = index[l.a], index[l.b]
        L[ia, ia] += w
        L[ib, ib] += w
        L[ia, ib] -= w
        L[ib, ia] -= w
        cx[ia] -= w * l.dx
        cx[ib] += w * l.dx
        cy[ia] -= w * l.dy
        cy[ib] += w * l.dy
    # pin the first node: delete its row/column (the gauge; L alone is singular)
    K = L[1:, 1:]
    px = np.zeros(m)
    py = np.zeros(m)
    if m > 1:
        px[1:] = np.linalg.solve(K + 1e-9 * np.eye(m - 1), cx[1:])
        py[1:] = np.linalg.solve(K + 1e-9 * np.eye(m - 1), cy[1:])
    return {node: (float(px[i]), float(py[i])) for node, i in index.items()}


def solve_links(n: int, links: list[Link], cfg: VideoConfig) -> SolveResult:
    """IRLS solve over the OK links. Mutates nothing; a link the gate drops is only counted."""
    ok = [l for l in links if l.ok]
    active = list(ok)
    dropped = 0

    for _round in range(4):                          # hard-gate rounds (last is a clean re-solve)
        if not active:
            break
        comp = _components(n, active)
        pos = np.zeros((n, 2))
        for c in sorted({int(comp[l.a]) for l in active}):
            nodes = [i for i in range(n) if comp[i] == c]
            clinks = [l for l in active if comp[l.a] == c]
            cw = np.array([max(l.ncc, 0.05) for l in clinks])
            for _it in range(cfg.irls_iters):
                sol = _solve_component(nodes, clinks, cw)
                r = np.array([np.hypot(sol[l.b][0] - sol[l.a][0] - l.dx,
                                       sol[l.b][1] - sol[l.a][1] - l.dy) for l in clinks])
                hub = np.where(r <= cfg.huber_px, 1.0, cfg.huber_px / np.maximum(r, 1e-9))
                cw = np.array([max(l.ncc, 0.05) for l in clinks]) * hub
            for node in nodes:
                pos[node] = sol[node]
        # residuals against the final positions; gate
        resid = np.array([np.hypot(pos[l.b][0] - pos[l.a][0] - l.dx,
                                   pos[l.b][1] - pos[l.a][1] - l.dy) for l in active])
        bad = resid > cfg.max_residual_px
        if not bad.any():
            break
        dropped += int(bad.sum())
        active = [l for l, b in zip(active, bad) if not b]

    if not active:                                   # nothing survived — everyone is alone
        comp = _components(n, [])
        return SolveResult(pos=np.zeros((n, 2)), component=comp,
                           placed=comp == 0, dropped_links=len(ok),
                           stats={"links_in": len(ok), "links_used": 0})

    comp = _components(n, active)
    resid = np.array([np.hypot(pos[l.b][0] - pos[l.a][0] - l.dx,
                               pos[l.b][1] - pos[l.a][1] - l.dy) for l in active])
    placed = comp == 0
    return SolveResult(
        pos=pos, component=comp, placed=placed, dropped_links=dropped,
        residual_median=float(np.median(resid)) if resid.size else 0.0,
        residual_p95=float(np.percentile(resid, 95)) if resid.size else 0.0,
        stats={
            "links_in": len(ok),
            "links_used": len(active),
            "links_dropped_by_solve": dropped,
            "components": int(comp.max()) + 1,
            "placed_keyframes": int(placed.sum()),
            "residual_median_px": round(float(np.median(resid)), 3) if resid.size else 0.0,
            "residual_p95_px": round(float(np.percentile(resid, 95)), 3) if resid.size else 0.0,
        })

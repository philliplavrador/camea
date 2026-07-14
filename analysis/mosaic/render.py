"""Stage (6): composite the (optionally flat-fielded) frames at the solved positions
into one mosaic. Shared by every build. Three modes:

  "alpha"   -- spectralign.Renderer: triangular per-tile alpha, optional butterworth
               `blend` seam-softening. The library-native path (used by builds A/B/C).
  "feather" -- numpy weighted linear blend: each tile weighted by a separable triangular
               feather (peaks at its centre), so overlaps cross-fade smoothly and edge
               pixels (dark/vignette-prone) contribute least. Fast, seam-free.
  "median"  -- numpy per-pixel median over all tiles covering a pixel (banded to bound
               memory). Robust: rejects per-tile artefacts, dwell dark-patches and the
               odd misplaced tile, at the cost of slightly softening where placement is
               imperfect.

`pos`: {trial: (x, y)} model-space top-left of each tile; `frame_of(t)`: the float frame
to place for trial t (raw, or flat-fielded -- run.py decides).

Also home to `layout_png` -- the ONE canonical layout figure. Every layout png in the
project goes through it, so they all look the same."""
import numpy as np


def layout_png(xy, trials, path, title, *, color_of=None, show=False):
    """THE canonical layout figure -- the house style; do not roll your own.

    The trial number IS the marker (bold, white-haloed so it reads over the path), joined
    by a faint acquisition-order line. Equal aspect, y down, figure shaped to the data so
    a tall strip renders tall. Font shrinks as tiles get denser.

    `xy`: (N, 2) tile positions, already in the coordinates you want plotted (add any
    centre offset before calling). `trials`: the N trial numbers, same order.
    `color_of(t) -> colour` optionally tints the digits (e.g. by pass); default all black.
    """
    import matplotlib
    if not show:
        matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.patheffects as pe

    c = np.asarray(xy, float)
    trials = [int(t) for t in trials]
    span = c.max(0) - c.min(0)
    aspect = span[1] / max(span[0], 1.0)                          # height / width
    W = 10.0
    H = float(np.clip(W * aspect, 5.0, 60.0))                    # match data aspect (tall strip)
    fs = float(np.clip(3200.0 / max(len(c), 1), 6.0, 16.0))      # shrink font when denser

    fig, ax = plt.subplots(figsize=(W, H))
    ax.plot(c[:, 0], c[:, 1], "-", lw=.5, alpha=.30, color="steelblue", zorder=1)  # acquisition path
    stroke = [pe.withStroke(linewidth=2.0, foreground="white")]   # halo so digits read over the lines
    for (x, y), t in zip(c, trials):                             # the trial number IS the marker
        ax.annotate(str(t), (x, y), fontsize=fs, ha="center", va="center",
                    color=color_of(t) if color_of else "black",
                    fontweight="bold", zorder=3, path_effects=stroke)
    ax.set_aspect("equal"); ax.invert_yaxis(); ax.margins(0.02)
    ax.set_title(title)
    fig.savefig(path, dpi=200, bbox_inches="tight")
    plt.show() if show else plt.close(fig)
    return fig


def render(pos, frame_of, tilesize=(512, 512), blend=0, mode="alpha"):
    if mode == "alpha":
        return _render_alpha(pos, frame_of, tilesize, blend)
    if mode in ("feather", "median"):
        return _render_numpy(pos, frame_of, tilesize, mode)
    raise ValueError(f"unknown render mode: {mode!r} (expected alpha|feather|median)")


def _render_alpha(pos, frame_of, tilesize, blend):
    """spectralign.Renderer -- clip=False -> union extent (clip is buggy for the rigid
    path in 0.4.2)."""
    from spectralign import Renderer
    rnd = Renderer(rigid=pos, tilesize=tilesize, blend=blend, clip=False)
    for k, t in enumerate(sorted(pos)):
        rnd.render(t, frame_of(t))                      # render frames at solved positions
        if k % 50 == 0:
            print(f"  rendered {k}/{len(pos)}")
    return np.asarray(rnd.image)


def _canvas(pos, tilesize):
    """Integer top-left of every tile on a common canvas + (H, W). Matches the alpha
    path's union extent (clip=False) so all render modes are directly comparable."""
    h, w = tilesize
    trials = sorted(pos)
    P = np.array([pos[t] for t in trials], float)
    P = P - P.min(0)
    P = np.rint(P).astype(int)
    H = int(P[:, 1].max()) + h
    W = int(P[:, 0].max()) + w
    return trials, P, H, W


def _feather(h, w):
    yy, xx = np.mgrid[0:h, 0:w]
    f = (1 - np.abs(xx - (w - 1) / 2) / ((w - 1) / 2)) * \
        (1 - np.abs(yy - (h - 1) / 2) / ((h - 1) / 2))
    return np.clip(f, 1e-3, None).astype(np.float32)


def _render_numpy(pos, frame_of, tilesize, mode):
    h, w = tilesize
    trials, P, H, W = _canvas(pos, tilesize)
    print(f"  canvas {H} x {W} px, {len(trials)} tiles, mode={mode}")

    if mode == "feather":
        feat = _feather(h, w)
        acc = np.zeros((H, W), np.float32)
        wsum = np.zeros((H, W), np.float32)
        for k, (t, (x, y)) in enumerate(zip(trials, P)):
            acc[y:y+h, x:x+w] += frame_of(t).astype(np.float32) * feat
            wsum[y:y+h, x:x+w] += feat
            if k % 50 == 0:
                print(f"  rendered {k}/{len(trials)}")
        return np.where(wsum > 0, acc / np.maximum(wsum, 1e-6), 0.0)

    # mode == "median": band over rows so we only stack tiles hitting each strip
    frames = {t: frame_of(t).astype(np.float32) for t in trials}     # each loaded once
    med = np.zeros((H, W), np.float32)
    BAND = h
    for y0 in range(0, H, BAND):
        y1 = min(y0 + BAND, H)
        hits = [(t, x, y) for t, (x, y) in zip(trials, P) if y < y1 and y + h > y0]
        if not hits:
            continue
        strip = np.full((len(hits), y1 - y0, W), np.nan, np.float32)
        for s, (t, x, y) in enumerate(hits):
            ry0, ry1 = max(y, y0), min(y + h, y1)
            strip[s, ry0 - y0:ry1 - y0, x:x+w] = frames[t][ry0 - y:ry1 - y]
        with np.errstate(all="ignore"):
            med[y0:y1] = np.nan_to_num(np.nanmedian(strip, axis=0))
        print(f"  median band {y0}-{y1}")
    return med

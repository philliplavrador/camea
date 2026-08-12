"""The videomosaic pipeline against a synthetic survey video with a KNOWN truth.

The contract under test is the whole point of the feature: hand the pipeline a video, get a
mosaic whose recovered geometry matches where the frames actually came from — no manual
anything. Plus the pieces that earn their own scrutiny: the sign conventions (verified
empirically before the pipeline was built — these tests pin them), link validation, the
robust solve, and the failure sentences.
"""

from __future__ import annotations

import numpy as np
import pytest

from camea.features.videomosaic.config import VideoConfig
from camea.features.videomosaic.pipeline import PipelineError, build
from camea.features.videomosaic.register import Link, measure_link
from camea.features.videomosaic.solvelinks import solve_links
from camea.features.videomosaic.video import VideoError, probe

#: Test-scale overrides: the synthetic frames are 480×320 (not 1080p), so the spacing that
#: gives ~58 % sequential overlap is proportionally smaller. Everything else is the shipped
#: default — the defaults themselves are part of what the real-video runs validated.
TEST_CFG = {"keyframe_spacing_frac": 200.0 / 480.0}


def _residuals(result: dict, truth: dict[int, tuple[float, float]]) -> np.ndarray:
    """Per-keyframe deviation between recovered and true positions, gauge aligned (both sides
    are translations of the same layout; subtracting each side's mean removes the free gauge)."""
    placed = {int(k): (v["x"], v["y"]) for k, v in result["keyframes"].items() if v["placed"]}
    assert placed, "nothing was placed"
    got = np.array([placed[f] for f in sorted(placed)])
    want = np.array([truth[f] for f in sorted(placed)])
    d = got - want
    return d - d.mean(axis=0)


def test_pipeline_recovers_the_survey_geometry(tmp_path, videosynth):
    v = videosynth.write_survey_video(tmp_path / "survey.avi")
    cfg = VideoConfig.from_overrides(TEST_CFG)
    result = build(tmp_path / "survey.avi", tmp_path / "out", cfg)

    stats = result["stats"]
    assert stats["solve"]["components"] == 1, "the survey must solve into ONE mosaic"
    assert stats["keyframes_dropped"] == 0, f"dropped: {result['stats']['dropped_video_frames']}"
    assert stats["track"]["keyframes"] >= 15

    r = _residuals(result, v["truth"])
    err = np.hypot(r[:, 0], r[:, 1])
    assert float(err.max()) < 3.0, f"worst keyframe is {err.max():.2f} px off the truth"

    # the mosaic itself: canvas ≈ the area the survey actually covered, well filled
    tx = [p[0] for p in v["truth"].values()]
    ty = [p[1] for p in v["truth"].values()]
    fh, fw = v["frame_hw"]
    assert abs(result["canvas"]["w"] - (max(tx) - min(tx) + fw)) < 20
    assert abs(result["canvas"]["h"] - (max(ty) - min(ty) + fh)) < 20
    assert stats["render"]["coverage_frac"] > 0.8
    for name in ("mosaic", "preview", "positions", "build"):
        assert (tmp_path / "out" / result["outputs"][name]).is_file()


def test_artifacts_are_named_after_the_project(tmp_path, videosynth):
    """⭐ R43: the folder the user names is the project AND the export, so the build writes
    `<project>.png` straight into it — no `outputs/`, no file called `mosaic.png`.

    🔴 `outputs` records FILENAMES, never absolute paths: a saved project MOVES
    (`Project.move_to`), and a path recorded here would be a lie the moment it did.
    """
    videosynth.write_survey_video(tmp_path / "survey.avi")
    cfg = VideoConfig.from_overrides(TEST_CFG)
    out = tmp_path / "the project"
    result = build(tmp_path / "survey.avi", out, cfg, basename="night sky")

    assert result["outputs"] == {
        "mosaic": "night sky.png",
        "preview": "night sky-preview.png",
        "positions": "night sky-positions.csv",
        "build": "night sky-build.json",
    }
    for fname in result["outputs"].values():
        assert (out / fname).is_file(), fname
    assert not (out / "mosaic.png").exists()
    assert not (out / "outputs").exists()


def test_pipeline_bridges_a_lights_off_gap(tmp_path, videosynth):
    """An illumination outage mid-survey must cost the black frames, not the mosaic."""
    v = videosynth.write_survey_video(tmp_path / "gap.avi", black_gap=(0.5, 40))
    cfg = VideoConfig.from_overrides(TEST_CFG)
    result = build(tmp_path / "gap.avi", tmp_path / "out", cfg)

    stats = result["stats"]
    assert stats["track"]["segments"] >= 2, "the gap must split tracking"
    assert stats["track"]["frames_black"] >= 40
    assert stats["solve"]["components"] == 1, "the bridge must tie the segments back together"
    assert stats["keyframes_dropped"] == 0
    err = np.hypot(*(_residuals(result, v["truth"]).T))
    assert float(err.max()) < 3.0


def test_pipeline_refuses_an_all_black_video(tmp_path, videosynth):
    import cv2

    vw = cv2.VideoWriter((tmp_path / "black.avi").as_posix(),
                         cv2.VideoWriter_fourcc(*"MJPG"), 30, (480, 320), True)
    for _ in range(60):
        vw.write(np.zeros((320, 480, 3), np.uint8))
    vw.release()
    with pytest.raises(PipelineError, match="black"):
        build(tmp_path / "black.avi", tmp_path / "out", VideoConfig())


def test_pipeline_refuses_a_still_video(tmp_path, videosynth):
    """A video that never moves is not a survey — the sentence must say so."""
    import cv2

    world = videosynth.survey_world()
    frame = np.clip(world[10:330, 10:490], 0, 255).astype(np.uint8)
    vw = cv2.VideoWriter((tmp_path / "still.avi").as_posix(),
                         cv2.VideoWriter_fourcc(*"MJPG"), 30, (480, 320), True)
    for _ in range(80):
        vw.write(cv2.merge([frame // 16, frame, frame // 32]))
    vw.release()
    with pytest.raises(PipelineError, match="barely moves"):
        build(tmp_path / "still.avi", tmp_path / "out", VideoConfig())


def test_probe_refuses_a_non_video(tmp_path):
    p = tmp_path / "not_video.mp4"
    p.write_bytes(b"this is not a movie" * 100)
    with pytest.raises(VideoError):
        probe(p)
    with pytest.raises(VideoError, match="no video file"):
        probe(tmp_path / "missing.mp4")


def test_measure_link_sign_convention(videosynth):
    """Pins the derivation the whole coordinate system rests on: `measured == pos_b - pos_a`,
    for crops cut from one world at known top-lefts."""
    world = videosynth.survey_world()
    A = world[100:420, 100:580].astype(np.float32)           # pos_a = (100, 100)
    B = world[130:450, 180:660].astype(np.float32)           # pos_b = (180, 130)
    cfg = VideoConfig()
    link = measure_link(A, B, (80.0, 30.0), Link(a=0, b=1, kind="seq"), cfg)
    assert link.ok, link.reject_reason
    assert abs(link.dx - 80.0) < 0.5 and abs(link.dy - 30.0) < 0.5

    # seeded 15 px off, it must still land on the truth (that is what "measurement" means)
    link2 = measure_link(A, B, (95.0, 20.0), Link(a=0, b=1, kind="seq"), cfg)
    assert link2.ok and abs(link2.dx - 80.0) < 0.5 and abs(link2.dy - 30.0) < 0.5

    # a prior with no overlap must be refused, not guessed at
    link3 = measure_link(A, B, (470.0, 310.0), Link(a=0, b=1, kind="seq"), cfg)
    assert not link3.ok and link3.reject_reason == "no_overlap_at_prior"


def test_segment_end_keyframe_survives_a_black_gap(monkeypatch, videosynth):
    """The frame right before a lights-out sits inside the black margin — the segment's tail
    keyframe must walk BACK to the newest eligible frame, not silently vanish (review finding:
    a coverage hole opened before every black gap)."""
    from camea.features.videomosaic import track as trackmod
    from camea.features.videomosaic.video import VideoInfo

    world = videosynth.survey_world()
    fh, fw = 320, 480
    seq = [world[10:10 + fh, 8 + 10 * i:8 + 10 * i + fw].astype(np.float32) for i in range(100)]
    seq += [np.zeros((fh, fw), np.float32)] * 12
    seq += [world[300:300 + fh, 8 + 10 * i:8 + 10 * i + fw].astype(np.float32)
            for i in range(100, 160)]

    def fake_iter(path, *, on_frame=None):
        yield from enumerate(seq)

    monkeypatch.setattr(trackmod, "iter_gray", fake_iter)
    info = VideoInfo(path="x", name="x", width=fw, height=fh, fps=30.0,
                     n_frames=len(seq), duration_s=len(seq) / 30.0, size_bytes=0)
    tr = trackmod.track("x", info, VideoConfig())
    ends = [k for k in tr.keyframes if k.reason == "segment-end"]
    assert any(88 <= k.index <= 99 for k in ends),         f"no segment-end keyframe before the black gap (got {[k.to_json() for k in ends]})"


def test_measured_offset_ignores_the_priors_fraction(videosynth):
    """A fractional prior must not leak into the measurement (review finding: up to 0.5 px/axis
    bias per link, feeding the global solve)."""
    world = videosynth.survey_world()
    A = world[100:420, 100:580].astype(np.float32)           # pos_a = (100, 100)
    B = world[130:450, 180:660].astype(np.float32)           # true offset (80, 30), exactly
    cfg = VideoConfig()
    link = measure_link(A, B, (80.4, 30.4), Link(a=0, b=1, kind="seq"), cfg)
    assert link.ok, link.reject_reason
    assert abs(link.dx - 80.0) < 0.3 and abs(link.dy - 30.0) < 0.3, (link.dx, link.dy)


def test_solve_drops_the_outlier_link():
    """Five nodes in a line, honest 100 px links — plus one confident liar. The solve must
    place the nodes right and throw the liar out, not average it in."""
    links = [Link(a=i, b=i + 1, kind="seq", dx=100.0, dy=0.0, ncc=0.8, ok=True)
             for i in range(4)]
    links += [Link(a=i, b=i + 2, kind="cross", dx=200.0, dy=0.0, ncc=0.7, ok=True)
              for i in range(3)]
    links.append(Link(a=0, b=4, kind="cross", dx=900.0, dy=250.0, ncc=0.9, ok=True))  # liar
    sol = solve_links(5, links, VideoConfig())
    assert sol.dropped_links >= 1
    xs = sol.pos[:, 0] - sol.pos[0, 0]
    assert np.allclose(xs, [0, 100, 200, 300, 400], atol=1.0), xs
    assert np.allclose(sol.pos[:, 1] - sol.pos[0, 1], 0, atol=1.0)
    assert sol.stats["components"] == 1


def test_config_refuses_unknown_keys():
    with pytest.raises(ValueError, match="unknown VideoConfig keys"):
        VideoConfig.from_overrides({"keyframe_spacing": 0.3})   # typo'd name
    cfg = VideoConfig.from_overrides({"keyframe_spacing_frac": 0.3})
    assert cfg.keyframe_spacing_frac == 0.3
    assert VideoConfig.from_overrides(None) == VideoConfig()

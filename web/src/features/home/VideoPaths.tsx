// ─────────────────────────────────────────────────────────────────────────────────────────────
// THE VIDEO — the last step of New project for the VIDEOMOSAIC task (2026-08-07).
//
// ⭐ **ONE BOX, NOT TWO** (his ruling, R43). The dataset flow names two paths — where the data comes
// FROM and where the project is saved INTO (R42) — because an hour of human sweeping needs a crash
// net in a real place from minute one. A video build is fully automatic and takes minutes, so this
// task asks only for the video and defers "where does this go?" to the finished screen, where he can
// see what he is saving. He was answering that question twice for one mosaic; now he answers it once.
//
// The box names the SOURCE — a video FILE, receipted by a real probe (the backend decodes a frame,
// so "probed OK" means "this will decode"). A refusal — probe (400) or create (409) — shows the
// backend's reason INLINE and KEEPS the typed text (R42.5). Every number on the receipt is read off
// `POST /api/videomosaic/probe`; fps/frames are what the container CLAIMS (phone video is often
// VFR) — a receipt, never arithmetic.
// ─────────────────────────────────────────────────────────────────────────────────────────────

import { useCallback, useEffect, useRef, useState } from 'react';
import { probeVideo, pickOpenFilePath } from '../../api';
import type { VideoSource } from '../../api';
import { Button } from '../../design/primitives/Button';
import { Help } from '../../design/primitives/Help';
import { fmtDuration, fmtBytes, fmtFps } from '../videomosaic/format';
import { normalisePath, forSubmit } from './pathText';
import paths from './ProjectPaths.module.css';
import styles from './VideoPaths.module.css';

const VIDEO_HELP =
  'Paste the path of your survey video (mp4/avi — anything the decoder reads) and press Enter. ' +
  'Probing decodes a real frame, so the receipt means the video will actually open. Frame count and ' +
  'fps are what the file claims about itself. Camea asks where to save the mosaic once it is built.';

export interface VideoPathsProps {
  /** The probed video. There is no folder to confirm — that comes after the build (R43). */
  onReady: (choice: { videoPath: string; videoName: string } | null) => void;
  /** Create the project and start building. A rejection is shown inline here, text kept (R42.5). */
  onCreate: () => Promise<void>;
  busy?: boolean;
}

export function VideoPaths({ onReady, onCreate, busy }: VideoPathsProps) {
  // ── the video ──────────────────────────────────────────────────────────────────
  const [text, setText] = useState('');
  const [probing, setProbing] = useState(false);
  const [probeError, setProbeError] = useState<string | null>(null);
  const [source, setSource] = useState<VideoSource | null>(null);

  const [createError, setCreateError] = useState<string | null>(null);

  useEffect(() => {
    onReady(source ? { videoPath: source.path, videoName: source.name } : null);
  }, [source, onReady]);

  // Editing the path invalidates the receipt IMMEDIATELY (Create must not bind the project to
  // the previously probed video), and a slow old probe must never overwrite a newer one.
  const probeSeq = useRef(0);

  const probe = useCallback(async (raw: string) => {
    const path = forSubmit(raw);
    if (!path) return;
    const seq = ++probeSeq.current;
    setProbing(true);
    setProbeError(null);
    try {
      const src = await probeVideo(path);
      if (seq === probeSeq.current) setSource(src);
    } catch (e) {
      // The backend's own reason (400: not decodable), inline under the box; the typed text stays.
      if (seq === probeSeq.current) {
        setSource(null);
        setProbeError(e instanceof Error ? e.message : String(e));
      }
    } finally {
      if (seq === probeSeq.current) setProbing(false);
    }
  }, []);

  // Probe on blur/Enter — the receipt follows the typed path, like ProjectPaths' dataset receipt.
  function maybeProbe(): void {
    const path = forSubmit(text);
    if (!path || probing) return;
    if (source && source.path === path) return; // already receipted
    void probe(path);
  }

  async function browse(): Promise<void> {
    // Native open-file dialog; headless answers 501 and the wrapper falls back to window.prompt (R38).
    const picked = await pickOpenFilePath({ title: 'Where is your survey video?' });
    if (!picked) return;
    const p = normalisePath(picked);
    setText(p);
    void probe(p);
  }

  function create(): void {
    setCreateError(null);
    onCreate().catch((e: unknown) =>
      setCreateError(e instanceof Error ? e.message : String(e)),
    );
  }

  return (
    <div className={paths.panel} data-testid="video-paths">
      {/* ── THE VIDEO ─────────────────────────────────────────────────────────── */}
      <section className={paths.step}>
        <h2 className={paths.label}>
          Video file
          <Help body={VIDEO_HELP} />
        </h2>
        <div className={styles.row}>
          <input
            className={styles.input}
            type="text"
            spellCheck={false}
            autoComplete="off"
            aria-label="Video file path"
            placeholder="paste the path of your survey video…"
            data-testid="np-video-path"
            value={text}
            onChange={(e) => {
              setText(normalisePath(e.target.value));
              setProbeError(null);
              setSource(null); // the receipt described a path that is no longer in the box
            }}
            onBlur={maybeProbe}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault();
                maybeProbe();
              }
            }}
          />
          <Button variant="ghost" size="sm" onClick={() => void browse()} data-testid="np-video-browse">
            Browse…
          </Button>
        </div>
        {probing && <div className={styles.probing}>probing…</div>}
        {probeError && (
          <div className={styles.error} role="alert" data-testid="video-probe-error">
            {probeError}
          </div>
        )}
        {source && <VideoReceipt src={source} onClear={() => setSource(null)} />}
      </section>

      {createError && (
        <div className={styles.error} role="alert" data-testid="np-create-error">
          {createError}
        </div>
      )}

      <div className={paths.actions}>
        <Button
          variant="primary"
          disabled={!source || busy}
          onClick={create}
          data-testid="np-create"
        >
          {busy ? 'Working…' : 'Build mosaic'}
        </Button>
      </div>
    </div>
  );
}

/** The probe receipt — a confirmation that the typed path decodes, not a browse card. */
function VideoReceipt({ src, onClear }: { src: VideoSource; onClear: () => void }) {
  return (
    <div className={paths.receipt} data-testid="video-receipt">
      <div className={paths.receiptBody}>
        <div className={paths.receiptName} data-testid="video-name">
          {src.name}
        </div>
        <div className={paths.facts}>
          <span className={paths.fact}>
            <span className={paths.factLabel}>frame</span>
            {src.width}×{src.height}
          </span>
          <span className={paths.fact}>
            <span className={paths.factLabel}>fps</span>
            {fmtFps(src.fps)}
          </span>
          <span className={paths.fact}>
            <span className={paths.factLabel}>frames</span>~{src.n_frames}
          </span>
          <span className={paths.fact}>
            <span className={paths.factLabel}>duration</span>
            {fmtDuration(src.duration_s)}
          </span>
          <span className={paths.fact}>
            <span className={paths.factLabel}>size</span>
            {fmtBytes(src.size_bytes)}
          </span>
        </div>
      </div>
      <button
        type="button"
        className={paths.clear}
        onClick={onClear}
        aria-label="Choose a different video"
      >
        ✕
      </button>
    </div>
  );
}

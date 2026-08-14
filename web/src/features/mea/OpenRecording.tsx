// ─────────────────────────────────────────────────────────────────────────────────────────────
// ONE RECORDING, OPEN — *"you pick one to load, and it opens it up"* (his interview, 2026-08-14).
//
// ⭐ **ONE AT A TIME, AND THAT IS A DECISION, NOT A LIMITATION.** Comparing recordings side by
// side, overlaying two traces and averaging across pads were all explicitly rejected. This screen
// is one recording, one pad, one trace.
//
// It loads the two GETs the chip needs — the chip's own layout, and the per-pad tally — and hands
// them to `ChipMap`. ⭐ Both are plain GETs because I measured them: 2.3–21 ms end to end on the
// real 300 s recordings under `data/`, the worst being 982 channels against 244,925 spikes. Neither
// needed to be a job, so the picture is there on the first paint and there is no progress bar.
//
// ⚠️ **A recording is read from wherever it currently lives** — his original while the copy runs,
// the project's own copy once it has landed. That is decided once, on the server
// (`features/mea/recordings.py :: open_path`), so nothing here has to know or care.
// ─────────────────────────────────────────────────────────────────────────────────────────────

import { useEffect, useState } from 'react';
import { meaChipActivity, meaChipLayout } from '../../api';
import type { MeaChipActivity, MeaChipLayout } from '../../api';
import { Button, LiveWarning } from '../../design';
import { ChipMap } from './ChipMap';
import { MeaTrace } from './MeaTrace';
import styles from './OpenRecording.module.css';

export interface OpenRecordingProps {
  analysisId: string;
  recordingId: string;
  /** Back to the shelf. */
  onClose: () => void;
}

export function OpenRecording({ analysisId, recordingId, onClose }: OpenRecordingProps) {
  const [layout, setLayout] = useState<MeaChipLayout | null>(null);
  const [activity, setActivity] = useState<MeaChipActivity | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [channel, setChannel] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLayout(null);
    setActivity(null);
    setError(null);
    setChannel(null);
    void Promise.all([
      meaChipLayout(analysisId, recordingId),
      meaChipActivity(analysisId, recordingId),
    ])
      .then(([l, a]) => {
        if (cancelled) return;
        setLayout(l);
        setActivity(a);
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      });
    return () => {
      cancelled = true;
    };
  }, [analysisId, recordingId]);

  return (
    <section className={styles.open} data-testid="mea-open-recording">
      <header className={styles.head}>
        <Button size="sm" variant="ghost" onClick={onClose} data-testid="mea-close-recording">
          ← All recordings
        </Button>
        <h2 className={styles.title} data-testid="mea-open-label">
          {layout?.label || '…'}
        </h2>
        {layout && (
          <span className={styles.facts} data-testid="mea-open-facts">
            {formatSeconds(layout.duration_s)} · {layout.n_channels.toLocaleString()} channels ·{' '}
            {layout.n_spikes.toLocaleString()} spikes
          </span>
        )}
      </header>

      {/* 🔴 A recording that has lost its file refuses to open and SAYS SO, naming it. Never an
          empty chip map — a chip drawn with no dots is indistinguishable from a chip on which
          nothing happened, and that would be a lie about his data. */}
      {error && (
        <LiveWarning variant="loud">
          <span data-testid="mea-open-error">{error}</span>
        </LiveWarning>
      )}

      {!error && layout && activity && (
        <div className={styles.split}>
          <ChipMap
            layout={layout}
            activity={activity}
            selected={channel}
            onSelect={setChannel}
          />
          <div className={styles.side}>
            <MeaTrace analysisId={analysisId} recordingId={recordingId} channel={channel} />
          </div>
        </div>
      )}
    </section>
  );
}

function formatSeconds(s: number): string {
  if (s < 60) return `${s.toFixed(s < 10 ? 1 : 0)} s`;
  const m = Math.floor(s / 60);
  return `${m}m ${Math.round(s - m * 60)}s`;
}

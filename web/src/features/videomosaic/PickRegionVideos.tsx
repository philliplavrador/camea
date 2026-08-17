// ─────────────────────────────────────────────────────────────────────────────────────────────
// PICK REGION VIDEOS — ⭐ **THE DOOR THAT WORKS IN EVERY MODE** (2026-08-16).
//
// The Regions step's "Pick files…" is the native multi-select dialog, which only exists with
// `--window` — and the app is actually driven over VSCode remote, where that route is a 501 (R38)
// and the step could only say *"paste one path at a time"*. This is the served answer, the same
// shape the MEA import proved out: `FolderPicker` to choose a folder, then
// `GET /api/videomosaic/browse-videos` lists every video underneath with a tick box each —
// PROBED, so a ticked row is one the locate job will actually be able to open, and a file that
// does not decode is listed greyed with the reason, never dropped.
//
// ⚠️ **IT HANDS BACK PATHS AND DOES NOTHING ELSE.** The caller feeds them to the same batch queue
// the native multi-select uses — one locate at a time through the one lease, every row appearing
// as it lands, a refusal recorded beside its file name (R46.7). A picker that POSTed anything
// itself would be a second door with different manners.
//
// ⚠️ Ticks are KEPT across folders (the MEA import's rule): he may gather recordings from two
// acquisition folders in one go, and what is ticked but off-screen is counted out loud.
// ─────────────────────────────────────────────────────────────────────────────────────────────

import { useCallback, useState } from 'react';
import { browseRegionVideos } from '../../api';
import type { RegionVideoCandidate } from '../../api';
import { FolderPicker } from '../../core/picker/FolderPicker';
import { Button, LiveWarning, Progress, useDelayedFlag } from '../../design';
import { fmtBytes, fmtDuration } from './format';
import { useElapsedText } from './useElapsed';
import styles from './PickRegionVideos.module.css';

export interface PickRegionVideosProps {
  /** The chosen paths, in tick order. Fired on **Locate** only — never per tick. */
  onAdd: (paths: string[]) => void;
  onClose: () => void;
}

export function PickRegionVideos({ onAdd, onClose }: PickRegionVideosProps) {
  const [folder, setFolder] = useState<string | null>(null);
  const [browsing, setBrowsing] = useState(false);
  const [here, setHere] = useState<RegionVideoCandidate[]>([]);
  const [ticked, setTicked] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const [truncated, setTruncated] = useState(false);

  // ⏱️ R48.1/R48.9 — the browse PROBES every video it finds (a decode proof each), so past the
  // 400 ms grace it owes a bar. Not a filling one: the walk's count comes back only when it is
  // over, so the honest shape is the sliver plus a count-up that is true.
  const lookingWait = useDelayedFlag(loading);
  const lookingFor = useElapsedText(loading);

  /** Read a folder. ⚠️ Ticks are KEPT — see the header. */
  const look = useCallback((path: string) => {
    setFolder(path);
    setLoading(true);
    setFailure(null);
    browseRegionVideos(path)
      .then((r) => {
        setHere(r.videos ?? []);
        setTruncated(r.truncated ?? false);
        // The server's own answer for where it looked — resolved and normalised.
        if (r.path) setFolder(r.path);
      })
      .catch((e: unknown) => setFailure(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, []);

  const toggle = (path: string) =>
    setTicked((prev) => (prev.includes(path) ? prev.filter((p) => p !== path) : [...prev, path]));

  const usable = here.filter((v) => v.readable);
  const allTicked = usable.length > 0 && usable.every((v) => ticked.includes(v.path));
  const toggleAll = () =>
    setTicked((prev) => {
      const paths = usable.map((v) => v.path);
      return allTicked
        ? prev.filter((p) => !paths.includes(p))
        : [...prev, ...paths.filter((p) => !prev.includes(p))];
    });

  // Ticked but not on screen — a recording from a folder he has since browsed away from. He must
  // see it is still coming, or Locate will surprise him.
  const onScreen = new Set(here.map((v) => v.path));
  const elsewhere = ticked.filter((p) => !onScreen.has(p));

  const facts = (v: RegionVideoCandidate): string =>
    [
      v.duration_s != null && v.duration_s > 0 ? fmtDuration(v.duration_s) : null,
      v.width != null && v.height != null ? `${v.width}×${v.height}` : null,
      v.bytes ? fmtBytes(v.bytes) : null,
    ]
      .filter(Boolean)
      .join(' · ');

  return (
    <div className={styles.backdrop} onMouseDown={onClose}>
      <div
        className={styles.dialog}
        role="dialog"
        aria-modal="true"
        aria-label="Add recordings from a folder"
        data-testid="regions-pick-videos"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <h2 className={styles.title}>Add recordings from a folder</h2>

        <div className={styles.bar}>
          <Button
            variant="default"
            size="sm"
            onClick={() => setBrowsing(true)}
            data-testid="rgv-choose-folder"
          >
            Choose a folder
          </Button>
          <span className={styles.folder} data-testid="rgv-folder">
            {folder ?? 'No folder chosen yet.'}
          </span>
        </div>

        <div className={styles.list} role="group" aria-label="Recordings found">
          {loading &&
            (lookingWait ? (
              <Progress
                className={styles.state}
                label="Looking through this folder for recordings"
                pct={null}
                elapsedText={lookingFor}
                message="Camea opens every video it finds to prove it decodes."
                unstoppableWhy="this one look has to finish"
                data-testid="rgv-looking"
              />
            ) : (
              <p className={styles.state}>Looking…</p>
            ))}

          {!loading && failure && (
            <LiveWarning variant="loud" className={styles.state}>
              <span data-testid="rgv-error">{failure}</span>
            </LiveWarning>
          )}

          {!loading && !failure && folder == null && here.length === 0 && (
            <p className={styles.state} data-testid="rgv-start">
              Choose the folder your fixed-field recordings are in. Camea lists every video under
              it.
            </p>
          )}

          {!loading && !failure && folder != null && here.length === 0 && (
            <p className={styles.state} data-testid="rgv-none">
              No videos in this folder. Try the folder above it.
            </p>
          )}

          {!loading && !failure && here.length > 0 && (
            <>
              <label className={styles.all}>
                <input
                  type="checkbox"
                  checked={allTicked}
                  disabled={usable.length === 0}
                  onChange={toggleAll}
                  data-testid="rgv-tick-all"
                />
                <span>
                  {here.length} video{here.length === 1 ? '' : 's'}
                </span>
              </label>
              {here.map((v) => (
                <label
                  key={v.path}
                  className={styles.row}
                  data-testid="rgv-row"
                  data-readable={v.readable ? 'true' : 'false'}
                  data-path={v.path}
                >
                  <input
                    type="checkbox"
                    checked={ticked.includes(v.path)}
                    disabled={!v.readable}
                    onChange={() => toggle(v.path)}
                    data-testid="rgv-tick"
                  />
                  <span className={styles.rowLabel}>{v.label || v.path}</span>
                  {v.readable ? (
                    <span className={styles.facts}>{facts(v)}</span>
                  ) : (
                    // ⛔ REFUSED BY NAME, ON THE LIST — never silently dropped.
                    <span className={styles.refused} data-testid="rgv-refused" title={v.problem}>
                      {v.problem || 'does not decode as video'}
                    </span>
                  )}
                </label>
              ))}
            </>
          )}

          {truncated && (
            <p className={styles.note} data-testid="rgv-truncated">
              Only the first videos in this folder are listed. Choose a folder further in.
            </p>
          )}
        </div>

        {elsewhere.length > 0 && (
          <p className={styles.note} data-testid="rgv-elsewhere">
            {elsewhere.length} more chosen from other folders.
          </p>
        )}

        <div className={styles.foot}>
          <Button variant="ghost" onClick={onClose} data-testid="rgv-cancel">
            Cancel
          </Button>
          <Button
            variant="primary"
            disabled={ticked.length === 0}
            onClick={() => onAdd([...ticked])}
            data-testid="rgv-add"
          >
            {ticked.length > 0
              ? `Locate ${ticked.length} recording${ticked.length === 1 ? '' : 's'}`
              : 'Locate'}
          </Button>
        </div>

        {browsing && (
          <FolderPicker
            title="Where are your recordings?"
            confirmLabel="Look in this folder"
            initialPath={folder ?? undefined}
            onPick={(p) => {
              setBrowsing(false);
              look(p);
            }}
            onClose={() => setBrowsing(false)}
          />
        )}
      </div>
    </div>
  );
}

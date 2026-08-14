// ─────────────────────────────────────────────────────────────────────────────────────────────
// WHERE FROM — the last step of New project. ⭐ **ONE BOX, since R44 (2026-08-10).**
//
// His ask of 2026-07-25 was two boxes: *"I wanna put in where I wanna pull the data from and where I
// wanna save the data into."* His ruling of 2026-08-10 took the second one back — *"camea saves
// project-specific files to its own repo automatically"* — so the app answers that question itself
// and only asks the one it cannot answer: **where is your data?**
//
// No root registry, no `N under M roots`, no grid of datasets the app went looking for. He names a
// folder and is told what is in it. The dataset card is a RECEIPT for the folder he typed, not a menu.
//
// ⛔ NO DATASET KNOWLEDGE (HARD RULE 3 / BEHAVIOUR I1). Every number on the receipt is read off the
// `/api/datasets/at` response; `is_dataset` is the backend's shape test (`log.txt` + one `NNN.xml`),
// never a name match. The only paths offered back are ones HE has used before.
// ─────────────────────────────────────────────────────────────────────────────────────────────

import { useCallback, useEffect, useState } from 'react';
import { datasetsAt, getSettings } from '../../api';
import type { DatasetSummary } from '../../api';
import { Button } from '../../design/primitives/Button';
import { Help } from '../../design/primitives/Help';
import { cx } from '../../design/cx';
import { FolderPicker } from '../../core/picker/FolderPicker';
import { PathField } from './PathField';
import styles from './ProjectPaths.module.css';

const FROM_HELP =
  'Paste the folder your acquisition is in and press Enter. A dataset is any folder with a log.txt ' +
  'beside NNN.xml frames — point at one, or at a folder holding several and pick which. Type to ' +
  'complete; ◆ marks a dataset.';

export interface ProjectPathsProps {
  /** The dataset, once confirmed. ⭐ No save folder: the app owns that (R44). */
  onReady: (choice: { datasetKey: string } | null) => void;
  /** Create the project. Enabled by the parent only once `onReady` has fired with a choice. */
  onCreate: () => void;
  busy?: boolean;
}

export function ProjectPaths({ onReady, onCreate, busy }: ProjectPathsProps) {
  // ── where FROM ─────────────────────────────────────────────────────────────────
  const [found, setFound] = useState<DatasetSummary[]>([]);
  const [dataset, setDataset] = useState<DatasetSummary | null>(null);
  const [recent, setRecent] = useState<string[]>([]);
  const [browsingFrom, setBrowsingFrom] = useState(false);

  // The paths he has used before — the only thing offered back, and only ever paths.
  useEffect(() => {
    let live = true;
    getSettings()
      .then((s) => {
        if (live) setRecent(s.recent_datasets ?? []);
      })
      .catch(() => {
        /* the completions are a convenience; their absence is not worth an error */
      });
    return () => {
      live = false;
    };
  }, []);

  useEffect(() => {
    onReady(dataset ? { datasetKey: dataset.key } : null);
  }, [dataset, onReady]);

  /** ⚠️ Throws on failure ON PURPOSE — PathField shows the backend's message inline and KEEPS the
   *  typed text. A toast here would throw away what he wrote. */
  const lookAt = useCallback(async (path: string) => {
    const body = await datasetsAt(path);
    if (body.datasets.length === 0) {
      throw new Error(
        'no dataset in that folder — a dataset is a folder with a log.txt beside NNN.xml frames.',
      );
    }
    // Exactly one (or the folder IS the acquisition): take it. Several: he picks. Never guess.
    setFound(body.datasets);
    setDataset(body.datasets.length === 1 ? body.datasets[0] : null);
  }, []);

  return (
    <div className={styles.panel} data-testid="project-paths">
      {/* ── PULL DATA FROM ────────────────────────────────────────────────────── */}
      <section className={styles.step}>
        <h2 className={styles.label}>
          Pull data from
          <Help body={FROM_HELP} />
        </h2>
        <PathField
          submitLabel="Look"
          placeholder="paste the folder your data is in…"
          known={recent}
          knownLabel="Recent"
          onSubmit={lookAt}
          onBrowse={() => setBrowsingFrom(true)}
          data-testid="from-field"
        />

        {found.length > 1 && !dataset && (
          <div className={styles.choose} data-testid="dataset-choices">
            <p className={styles.chooseLede}>
              {found.length} acquisitions in that folder — which one?
            </p>
            <div className={styles.chooseRow}>
              {found.map((d) => (
                <button
                  key={d.key}
                  type="button"
                  className={styles.chooseChip}
                  data-testid="dataset-choice"
                  onClick={() => setDataset(d)}
                >
                  ◆ {d.name}
                </button>
              ))}
            </div>
          </div>
        )}

        {dataset && <DatasetReceipt ds={dataset} onClear={() => { setDataset(null); setFound([]); }} />}
      </section>

      {/* ⛔ **NO "SAVE INTO" BOX (R44).** The project goes into Camea's own store; browsing it later
          is the Outputs panel on the project screen, which is the only door to its files. */}
      <div className={styles.actions}>
        <Button
          variant="primary"
          disabled={!dataset || busy}
          onClick={onCreate}
          data-testid="np-create"
        >
          {busy ? 'Working…' : 'Create project'}
        </Button>
      </div>

      {browsingFrom && (
        <FolderPicker
          title="Where is your data?"
          confirmLabel="Use this folder"
          onPick={(p) => {
            setBrowsingFrom(false);
            void lookAt(p).catch(() => setDataset(null));
          }}
          onClose={() => setBrowsingFrom(false)}
        />
      )}
    </div>
  );
}

/**
 * The receipt: what is actually in the folder he just named. Every number read off the response —
 * this is a confirmation that he typed the right path, not a card in a browse grid.
 */
function DatasetReceipt({ ds, onClear }: { ds: DatasetSummary; onClear: () => void }) {
  const shapes = ds.shapes ?? [];
  const captured = fmtDate(ds.last_at ?? ds.first_at);
  return (
    <div className={styles.receipt} data-testid="dataset-card">
      {ds.thumbnail_url ? (
        <img className={styles.thumb} src={ds.thumbnail_url} alt="" loading="lazy" width={96} height={96} />
      ) : (
        <div className={cx(styles.thumb, styles.thumbEmpty)}>no frame</div>
      )}
      <div className={styles.receiptBody}>
        <div className={styles.receiptName} data-testid="dataset-name">
          {ds.name}
        </div>
        {ds.experiment && ds.experiment !== ds.name && (
          <div className={styles.experiment}>{ds.experiment}</div>
        )}
        <div className={styles.facts}>
          <span className={styles.fact}>
            <span className={styles.factLabel}>trials</span>
            {ds.n_trials}
          </span>
          <span className={styles.fact}>
            <span className={styles.factLabel}>snapshots</span>
            <span data-testid="dataset-snapshots">{ds.n_snapshots}</span>
          </span>
          {captured && (
            <span className={styles.fact}>
              <span className={styles.factLabel}>captured</span>
              {captured}
            </span>
          )}
        </div>
        {shapes.length > 0 && (
          <div className={styles.facts} data-testid="dataset-shapes">
            {shapes.map((s) => (
              <span className={styles.fact} key={`${s.w}x${s.h}`}>
                {s.w}×{s.h}
                <span className={styles.factLabel}>×{s.n}</span>
              </span>
            ))}
          </div>
        )}
        {ds.warnings && ds.warnings.length > 0 && (
          <ul className={styles.warnings}>
            {ds.warnings.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        )}
      </div>
      <button
        type="button"
        className={styles.clear}
        onClick={onClear}
        aria-label="Choose a different data folder"
      >
        ✕
      </button>
    </div>
  );
}

function fmtDate(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  return d.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
}

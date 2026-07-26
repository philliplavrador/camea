import { useMemo, useState } from 'react';
import { useDatasets, type DatasetSummary, type AnalysisRef } from './useDatasets';
import { FolderPicker } from './FolderPicker';
import { PathField } from './PathField';
import { useToast } from '../../app';
import { Button } from '../../design/primitives/Button';
import { Help } from '../../design/primitives/Help';
import { cx } from '../../design/cx';
import styles from './DatasetBrowser.module.css';

const ROOT_HELP =
  'Paste the folder your acquisitions are in and press Enter — a dataset is any folder with a ' +
  'log.txt beside NNN.xml frames. Point at a parent and everything beneath it is found; point at ' +
  'one acquisition and you get just that. Type to complete; ◆ marks a dataset.';

// Stable empty references so the filter memo does not see a fresh [] every render.
const EMPTY_DATASETS: DatasetSummary[] = [];
const EMPTY_ROOTS: string[] = [];

export interface DatasetPickerProps {
  /** Pick this dataset (by key). Used by the new-project flow to attach a dataset to a project. */
  onSelect: (datasetKey: string) => void;
}

/**
 * THE DATASET PICKER — the datasets found under the roots you have pointed Camea at, each a card with
 * a thumbnail, its trial/snapshot counts and frame shapes. Picking one attaches it to the project.
 *
 * (Was the home screen; since the 2026-07-24 project-manager reframe it is the "attach a dataset" step
 * of the new-project flow. The WORKSPACE is now an app-managed store chosen once in the manager, so its
 * toolbar is gone from here; a dataset stays raw and read-only either way.)
 *
 * This screen carries NO dataset knowledge (HARD RULE 3 / BEHAVIOUR I1): every number on a card is read
 * off the /api/datasets response; the roots are whatever the user chose.
 */
export function DatasetPicker({ onSelect }: DatasetPickerProps) {
  const { state, scanRoot } = useDatasets();
  const toast = useToast();
  const [picking, setPicking] = useState(false);
  const [query, setQuery] = useState('');

  const roots = state.status === 'ready' ? state.data.roots : EMPTY_ROOTS;
  const datasets = state.status === 'ready' ? state.data.datasets : EMPTY_DATASETS;

  const filtered = useMemo(() => {
    const all = state.status === 'ready' ? state.data.datasets : EMPTY_DATASETS;
    const q = query.trim().toLowerCase();
    if (!q) return all;
    return all.filter(
      (d) => d.name.toLowerCase().includes(q) || (d.experiment ?? '').toLowerCase().includes(q),
    );
  }, [state, query]);

  /** From the Browse… modal: a path we know exists. Errors go to a toast (the modal is gone by then). */
  async function handlePick(path: string) {
    setPicking(false);
    try {
      await scanRoot(path);
      toast.push(`Scanning ${path}`, { tone: 'good' });
    } catch (e) {
      toast.push(String(e instanceof Error ? e.message : e), { tone: 'danger' });
    }
  }

  /** From the paste box: it keeps the text and shows the failure inline, so let it throw. */
  async function handleTyped(path: string) {
    await scanRoot(path);
    toast.push(`Scanning ${path}`, { tone: 'good' });
  }

  return (
    <div className={styles.page} data-testid="dataset-browser">
      <header className={styles.header}>
        <div className={styles.titleRow}>
          <h1 className={styles.title}>Attach a dataset</h1>
          {state.status === 'ready' && (
            <span className={styles.count} data-testid="dataset-count">
              {datasets.length} under {roots.length} root{roots.length === 1 ? '' : 's'}
            </span>
          )}
          {datasets.length > 0 && (
            <input
              className={styles.filter}
              type="search"
              placeholder="filter…"
              aria-label="Filter datasets by name"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          )}
        </div>

        <div className={styles.toolbar}>
          <span className={styles.toolLabel}>
            Data root
            <Help body={ROOT_HELP} />
          </span>
          <PathField
            submitLabel="Add root"
            placeholder="paste a folder path, or type to complete…"
            known={roots}
            knownLabel="Your roots"
            onSubmit={handleTyped}
            onBrowse={() => setPicking(true)}
            data-testid="root-field"
          />
        </div>
      </header>

      {state.status === 'loading' && <div className={styles.state}>Scanning…</div>}

      {state.status === 'error' && (
        <div className={cx(styles.state, styles.stateError)} role="alert">
          {state.message}
        </div>
      )}

      {state.status === 'ready' && datasets.length === 0 && (
        <div className={styles.empty}>
          No datasets found.
          <div className={styles.emptyHint}>
            Paste the path above and press Enter. A dataset is any folder of NNN.xml + NNN-ccd.dat
            beside a log.txt — point at one, or at a parent that holds several.
          </div>
          <div className={styles.emptyAction}>
            <Button variant="ghost" size="sm" onClick={() => setPicking(true)}>
              Browse instead…
            </Button>
          </div>
        </div>
      )}

      {state.status === 'ready' && datasets.length > 0 && (
        <>
          {filtered.length === 0 ? (
            <div className={styles.state}>No dataset matches “{query}”.</div>
          ) : (
            <div className={styles.grid} role="list">
              {filtered.map((ds) => (
                <DatasetCard key={ds.key} ds={ds} onSelect={onSelect} />
              ))}
            </div>
          )}
          {state.data.skipped && state.data.skipped.length > 0 && (
            <div className={styles.skipped}>
              {state.data.skipped.length} folder(s) looked like a dataset but could not be read.
            </div>
          )}
        </>
      )}

      {picking && (
        <FolderPicker
          title="Choose a data folder"
          confirmLabel="Scan this folder"
          onPick={handlePick}
          onClose={() => setPicking(false)}
        />
      )}
    </div>
  );
}

function DatasetCard({ ds, onSelect }: { ds: DatasetSummary; onSelect: (key: string) => void }) {
  const shapes = ds.shapes ?? [];
  const analyses = ds.analyses ?? [];
  const captured = fmtDate(ds.last_at ?? ds.first_at);
  return (
    <button
      type="button"
      className={styles.card}
      role="listitem"
      data-testid="dataset-card"
      onClick={() => onSelect(ds.key)}
    >
      {ds.thumbnail_url ? (
        <img
          className={styles.thumb}
          src={ds.thumbnail_url}
          alt=""
          loading="lazy"
          width={240}
          height={240}
        />
      ) : (
        <div className={cx(styles.thumb, styles.thumbPlaceholder)}>no frame</div>
      )}

      <div className={styles.body}>
        <div className={styles.name} data-testid="dataset-name">
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

        {analyses.length > 0 && (
          <div className={styles.analyses} data-testid="dataset-analyses">
            {analyses.map((a) => (
              <AnalysisChip key={a.analysis_id} a={a} />
            ))}
          </div>
        )}

        {ds.warnings && ds.warnings.length > 0 && (
          <ul className={styles.warnings}>
            {ds.warnings.map((w, i) => (
              <li className={styles.warning} key={i}>
                {w}
              </li>
            ))}
          </ul>
        )}
      </div>
    </button>
  );
}

/** "you already have work here" — an existing analysis on this dataset (docs/API.md AnalysisRef). */
function AnalysisChip({ a }: { a: AnalysisRef }) {
  const bits: string[] = [];
  if (a.n_anchored != null) bits.push(`${a.n_anchored} anchored`);
  if (a.n_excluded != null && a.n_excluded > 0) bits.push(`${a.n_excluded} excluded`);
  return (
    <span className={styles.analysisChip} title={`${a.name} · modified ${fmtDate(a.modified) ?? ''}`}>
      <span className={styles.analysisFeature}>{a.feature}</span>
      {bits.length > 0 && <span className={styles.analysisStats}>{bits.join(' · ')}</span>}
    </span>
  );
}

/** Format an ISO timestamp as a short local date, defensively (the field is nullable). */
function fmtDate(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  return d.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
}

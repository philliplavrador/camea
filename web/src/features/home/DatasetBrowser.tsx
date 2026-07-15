import { useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { useDatasets, type DatasetSummary, type AnalysisRef } from './useDatasets';
import { useWorkspace } from './useWorkspace';
import { FolderPicker } from './FolderPicker';
import { useToast } from '../../app';
import { Button } from '../../design/primitives/Button';
import { Help } from '../../design/primitives/Help';
import { cx } from '../../design/cx';
import styles from './DatasetBrowser.module.css';

const WORKSPACE_HELP =
  'Where Camea writes your analyses (the .camea project files, exports and autosaves).\n' +
  'It is a folder you choose — never inside the dataset, never inside the app. A dataset stays raw ' +
  'and read-only; the workspace is everything you did to it.';

const ROOT_HELP =
  'The folders Camea scans for datasets. A dataset is any acquisition folder — a log.txt beside ' +
  'NNN.xml frames. Point at a parent folder and every acquisition beneath it is found.';

type PickerKind = 'root' | 'workspace' | null;

// Stable empty references so the filter memo does not see a fresh [] every render.
const EMPTY_DATASETS: DatasetSummary[] = [];
const EMPTY_ROOTS: string[] = [];

/**
 * THE HOME SCREEN — a dataset browser. Camea opens on your data: the datasets found under the roots
 * you have pointed it at, each a card with a thumbnail, its trial/snapshot counts, its frame shapes,
 * its capture dates and any analyses you already have. Pick one to open it into a feature (Mosaic).
 *
 * This screen carries NO dataset knowledge (HARD RULE 3 / BEHAVIOUR I1): no trial numbers, no counts,
 * no exclusion list, no hard-coded paths. Every number on a card is read off the /api/datasets
 * response; the roots and workspace are whatever the user chose.
 */
export function DatasetBrowser() {
  const { state, refetch, scanRoot } = useDatasets();
  const { workspace, setWorkspace } = useWorkspace();
  const toast = useToast();
  const [picker, setPicker] = useState<PickerKind>(null);
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

  async function handlePick(path: string) {
    const kind = picker;
    setPicker(null);
    try {
      if (kind === 'root') {
        await scanRoot(path);
        toast.push(`Scanning ${path}`, { tone: 'good' });
      } else if (kind === 'workspace') {
        await setWorkspace(path);
        refetch(); // analyses shown per card are workspace-derived — re-read them
        toast.push(`Workspace set to ${path}`, { tone: 'good' });
      }
    } catch (e) {
      toast.push(String(e instanceof Error ? e.message : e), { tone: 'danger' });
    }
  }

  return (
    <div className={styles.page} data-testid="dataset-browser">
      <header className={styles.header}>
        <div className={styles.titleRow}>
          <h1 className={styles.title}>Datasets</h1>
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
          <ToolGroup
            label="Data root"
            help={ROOT_HELP}
            action={
              <Button variant="ghost" size="sm" onClick={() => setPicker('root')} data-testid="add-root">
                {roots.length ? 'Add root…' : 'Choose a folder…'}
              </Button>
            }
          >
            {roots.length ? (
              <span className={styles.rootList} data-testid="root-list">
                {roots.map((r) => (
                  <span className={styles.rootChip} key={r} title={r}>
                    {r}
                  </span>
                ))}
              </span>
            ) : (
              <span className={styles.toolEmpty}>none yet</span>
            )}
          </ToolGroup>

          <ToolGroup
            label="Workspace"
            help={WORKSPACE_HELP}
            action={
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setPicker('workspace')}
                data-testid="set-workspace"
              >
                {workspace?.path ? 'Change…' : 'Set…'}
              </Button>
            }
          >
            {workspace?.path ? (
              <span className={styles.wsValue} data-testid="workspace-path" title={workspace.path}>
                {workspace.path}
                {!workspace.writable && <span className={styles.wsWarn}> read-only</span>}
                {workspace.n_analyses != null && workspace.n_analyses > 0 && (
                  <span className={styles.wsCount}>{workspace.n_analyses} saved</span>
                )}
              </span>
            ) : (
              <span className={styles.toolEmpty} data-testid="workspace-path">
                not set
              </span>
            )}
          </ToolGroup>
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
            Point Camea at a folder that contains acquisitions (a directory of NNN.xml + NNN-ccd.dat
            with a log.txt).
          </div>
          <div className={styles.emptyAction}>
            <Button variant="primary" size="sm" onClick={() => setPicker('root')}>
              Choose a folder…
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
                <DatasetCard key={ds.key} ds={ds} />
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

      {picker && (
        <FolderPicker
          title={picker === 'root' ? 'Choose a data folder' : 'Choose a workspace folder'}
          confirmLabel={picker === 'root' ? 'Scan this folder' : 'Use this folder'}
          initialPath={picker === 'workspace' ? (workspace?.path ?? undefined) : undefined}
          onPick={handlePick}
          onClose={() => setPicker(null)}
        />
      )}
    </div>
  );
}

function ToolGroup({
  label,
  help,
  action,
  children,
}: {
  label: string;
  help: string;
  action: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className={styles.toolGroup}>
      <span className={styles.toolLabel}>
        {label}
        <Help body={help} />
      </span>
      <div className={styles.toolValue}>{children}</div>
      {action}
    </div>
  );
}

function DatasetCard({ ds }: { ds: DatasetSummary }) {
  const shapes = ds.shapes ?? [];
  const analyses = ds.analyses ?? [];
  const captured = fmtDate(ds.last_at ?? ds.first_at);
  return (
    <Link
      to={`/dataset/${ds.key}`}
      className={styles.card}
      role="listitem"
      data-testid="dataset-card"
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
    </Link>
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

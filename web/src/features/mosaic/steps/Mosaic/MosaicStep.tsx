// STEP 6 · MOSAIC — the EXPORT screen. Choose the workspace output, tick the outputs (16-bit TIFF + its
// MANDATORY coverage sidecar, display PNG, positions.csv, ground-truth JSON, QC report), and run the
// export as a JOB. It writes SEVEN files (BEHAVIOUR R37) into a folder the user chooses — never inside
// the dataset, never inside the repo.
//
// ⭐ THE PROVENANCE STAMP (BEHAVIOUR R28 / W5) is a LIVE WARNING and it STAYS ON THE PAGE — it is a fact
// about current state, not an explanation to hide behind a `?`. It is DERIVED FROM THE DOCUMENT'S
// HISTORY (a build block, or a single tile still carrying a `machine` position), never from what the
// document CLAIMS about itself: a seeded document is stamped `independent_of_method: false` with the
// do-not-score warning, and that warning is what ships in the exported gt.json.
//
// ⛔ NO DATASET KNOWLEDGE (HARD RULE 3). Every number on screen states its BASIS — "usable = not
// excluded" is derived from the document's own tile states, never a literal 312. The app keeps no list.

import { useCallback, useEffect, useMemo, useState } from 'react';
import { Button } from '../../../../design/primitives/Button';
import { Help } from '../../../../design/primitives/Help';
import { LiveWarning } from '../../../../design/primitives/LiveWarning';
import { cx } from '../../../../design/cx';
import {
  startExport,
  getMachineEvidence,
  pollJobUntilDone,
  pickDirectory,
  type ExportRequest,
  type ExportResult,
  type MachineEvidenceResponse,
} from '../../../../api';
import { useSweepStore, counts as tileCounts } from '../../store';
import { useDocument } from '../../../../store/documentStore';
import styles from './MosaicStep.module.css';

type RenderMode = ExportRequest['render_mode'];
type OutputKey = 'tiff' | 'png' | 'positions' | 'gt' | 'qc';

/** Human labels for every exported-file kind, incl. the 7th (`qc_md`) the backend emits for the QC report. */
const KIND_LABEL: Record<string, string> = {
  tiff: '16-bit TIFF',
  coverage: 'coverage mask',
  png: 'display PNG',
  positions: 'positions.csv',
  gt: 'ground-truth JSON',
  qc: 'QC report · JSON',
  qc_md: 'QC report · Markdown',
};

/**
 * A display-only fallback for the provenance warning, used ONLY if the server's machine-evidence call
 * did not return one while the document is machine-derived. In practice the backend supplies the exact
 * `PROVENANCE_WARNING` string, which is what ships in the file (R28); this keeps the on-page stamp from
 * ever rendering empty. It is not dataset knowledge.
 */
const FALLBACK_PROVENANCE_WARNING =
  'NOT AN INDEPENDENT GROUND TRUTH. Every position started as the solver’s output. Never score the ' +
  'solver (or any method derived from it) with this — the score would be 100 % by construction.';

function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  const units = ['KB', 'MB', 'GB'];
  let v = n / 1024;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i += 1;
  }
  return `${v < 10 ? v.toFixed(1) : Math.round(v)} ${units[i]}`;
}

/** One selectable output pill — a `role="switch"` button (its own testid) with an adjacent `?`. The `?`
 *  lives OUTSIDE the button because a button may not nest a button. */
function OutputChip({
  testid,
  label,
  on,
  onToggle,
  help,
}: {
  testid: string;
  label: string;
  on: boolean;
  onToggle: () => void;
  help?: string;
}) {
  return (
    <div className={styles.chipRow}>
      <button
        type="button"
        role="switch"
        aria-checked={on}
        data-testid={testid}
        className={cx(styles.chip, on && styles.chipOn)}
        onClick={onToggle}
      >
        <span className={styles.chipMark} aria-hidden="true" />
        <span className={styles.chipLabel}>{label}</span>
      </button>
      {help ? <Help body={help} /> : null}
    </div>
  );
}

export function MosaicStep() {
  const doc = useSweepStore((s) => s.doc);
  const sessionId = useSweepStore((s) => s.sessionId);
  const order = useSweepStore((s) => s.order);
  const autosave = useDocument((s) => s.autosave);

  // ── output destination ──
  const [dir, setDir] = useState('');
  const [basename, setBasename] = useState('');
  // Seed the basename from the document's own dataset name once (a runtime value, not a hard-coded one).
  useEffect(() => {
    if (doc && basename === '') setBasename(doc.dataset || 'mosaic');
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [doc]);

  // ── outputs / render options ──
  const [sel, setSel] = useState({ tiff: true, png: true, positions: true, gt: true, qc: true });
  const [renderMode, setRenderMode] = useState<RenderMode>('feather');
  const [includeUnverified, setIncludeUnverified] = useState(true);
  const [umPerPx, setUmPerPx] = useState('');

  // ── the export job ──
  const [exporting, setExporting] = useState(false);
  const [phase, setPhase] = useState<string | null>(null);
  const [result, setResult] = useState<ExportResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  // ── provenance evidence (derived from HISTORY, on the server) ──
  const [ev, setEv] = useState<MachineEvidenceResponse | null>(null);
  useEffect(() => {
    if (!doc) {
      setEv(null);
      return;
    }
    let alive = true;
    getMachineEvidence(doc)
      .then((r) => {
        if (alive) setEv(r);
      })
      .catch(() => {
        // The endpoint hiccuped — fall back to the client-side history derivation below.
        if (alive) setEv(null);
      });
    return () => {
      alive = false;
    };
  }, [doc]);

  const toggle = useCallback((k: OutputKey) => setSel((s) => ({ ...s, [k]: !s[k] })), []);

  const outputs = useMemo<NonNullable<ExportRequest['outputs']>>(() => {
    const o: NonNullable<ExportRequest['outputs']> = [];
    if (sel.tiff) o.push('tiff', 'coverage'); // coverage is the MANDATORY sidecar of the TIFF (R37)
    if (sel.png) o.push('png');
    if (sel.positions) o.push('positions');
    if (sel.gt) o.push('gt');
    if (sel.qc) o.push('qc');
    return o;
  }, [sel]);

  // ── denominators — every number states its basis (usable = NOT excluded) ──
  const c = doc ? tileCounts(doc.tiles, order) : null;
  const inDocument = c ? c.anchored + c.unverified + c.unplaced + c.excluded : 0;
  const usable = c ? inDocument - c.excluded : 0;
  const willRender = c ? c.anchored + (includeUnverified ? c.unverified : 0) : 0;

  // ── provenance: machine-derived is a fact about HISTORY, never a self-declaration ──
  const machineFromHistory = useMemo(() => {
    if (!doc) return false;
    if (doc.build) return true;
    return Object.values(doc.tiles).some((t) => Array.isArray(t?.machine));
  }, [doc]);
  const machineDerived = ev ? ev.independent_of_method === false : machineFromHistory;
  const warningText = ev?.warning ?? doc?.provenance?.warning ?? FALLBACK_PROVENANCE_WARNING;

  // ── µm/px — pixels only by default; a typed number is written and stamped "by hand" on the server ──
  const umTrim = umPerPx.trim();
  const umValue = umTrim === '' ? null : Number(umTrim);
  const umValid = umValue == null || (Number.isFinite(umValue) && umValue > 0);

  const nothingSelected = outputs.length === 0;
  const canExport =
    !!doc &&
    !!sessionId &&
    !exporting &&
    dir.trim() !== '' &&
    basename.trim() !== '' &&
    !nothingSelected &&
    umValid;

  const onBrowse = useCallback(async () => {
    const picked = await pickDirectory({ title: 'Choose an output folder', start: dir || null });
    if (picked) setDir(picked);
  }, [dir]);

  const onExport = useCallback(async () => {
    if (!doc || !sessionId) return;
    setError(null);
    setResult(null);
    setExporting(true);
    setPhase('starting…');
    try {
      const req: ExportRequest = {
        session_id: sessionId,
        dir: dir.trim(),
        basename: basename.trim(),
        doc,
        outputs,
        render_mode: renderMode,
        include_unverified: includeUnverified,
        ...(umValue != null ? { um_per_px: umValue } : {}),
      };
      const ref = await startExport(req);
      const job = await pollJobUntilDone(ref.job_id, {
        onUpdate: (j) => setPhase(j.message ?? j.phase ?? 'exporting…'),
      });
      const res = job.result;
      if (res && res.kind === 'export') setResult(res);
      else setError('Export finished but returned no files.');
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setExporting(false);
      setPhase(null);
    }
  }, [doc, sessionId, dir, basename, outputs, renderMode, includeUnverified, umValue]);

  if (!doc) {
    return (
      <div className={styles.pane}>
        <div className={styles.inner}>
          <p className={styles.empty}>No document open.</p>
        </div>
      </div>
    );
  }

  const exportedProv = result?.doc?.provenance;

  return (
    <div className={styles.pane}>
      <div className={styles.inner}>
        <header className={styles.head}>
          <h1 className={styles.h1}>Export the mosaic</h1>
        </header>

        {/* ── PROVENANCE — a live warning about current state (W5), on the page ── */}
        <section className={styles.section} data-testid="provenance-panel">
          <div className={styles.legendRow}>
            <span className={styles.legend}>Provenance</span>
            <Help
              body={
                'How this document was authored. The stamp below is derived from its HISTORY (a solver build, or a tile still at a machine position) — never from what the file claims about itself.'
              }
            />
          </div>

          <dl className={styles.facts}>
            <div className={styles.fact}>
              <dt className={styles.factLabel}>Authored by</dt>
              <dd className={styles.factValue}>{doc.provenance.authored_by || '—'}</dd>
            </div>
            <div className={styles.fact}>
              <dt className={styles.factLabel}>Workflow</dt>
              <dd className={styles.factValue}>{doc.provenance.workflow || '—'}</dd>
            </div>
            <div className={styles.fact}>
              <dt className={styles.factLabel}>Machine positions</dt>
              <dd className={styles.factValue}>
                {ev ? ev.n_machine_tiles : machineFromHistory ? 'yes' : '0'}
              </dd>
            </div>
          </dl>

          {machineDerived ? (
            <div data-testid="provenance-stamp">
              <LiveWarning
                variant="loud"
                help={
                  'This project has destroyed one benchmark exactly this way. The warning ships in every exported file (R28).'
                }
              >
                {warningText}
              </LiveWarning>
            </div>
          ) : (
            <p className={styles.independent}>
              Independent of method — no machine positions in this document.
            </p>
          )}
        </section>

        {/* ── DENOMINATORS — usable = not excluded (never a literal count) ── */}
        <section className={styles.section}>
          <div className={styles.legendRow}>
            <span className={styles.legend}>This mosaic</span>
          </div>
          <dl className={styles.facts}>
            <div className={styles.fact}>
              <dt className={styles.factLabel}>In document</dt>
              <dd className={styles.factValue}>{inDocument}</dd>
            </div>
            <div className={styles.fact}>
              <dt className={styles.factLabel}>
                Usable
                <Help
                  body={
                    'Every tile you did NOT exclude. The app keeps no exclusion list of its own and has no default count — this is derived from the document’s own tile states.'
                  }
                />
              </dt>
              <dd className={styles.factValue}>
                {usable} <span className={styles.factBasis}>= not excluded</span>
              </dd>
            </div>
            <div className={styles.fact}>
              <dt className={styles.factLabel}>Excluded</dt>
              <dd className={styles.factValue}>{c ? c.excluded : 0}</dd>
            </div>
            <div className={styles.fact}>
              <dt className={styles.factLabel}>
                Will render
                <Help
                  body={
                    'anchored + unverified (iff “include unverified”). excluded and unplaced tiles are never rendered (R37).'
                  }
                />
              </dt>
              <dd className={styles.factValue}>{willRender}</dd>
            </div>
          </dl>
        </section>

        {/* ── OUTPUT DESTINATION ── */}
        <section className={styles.section}>
          <div className={styles.legendRow}>
            <span className={styles.legend}>Output folder</span>
            <Help
              body={
                'A workspace folder you choose. The export is never written inside the dataset or the repository.'
              }
            />
          </div>
          <div className={styles.row}>
            <input
              type="text"
              data-testid="mosaic-dir"
              className={styles.input}
              placeholder="C:\\path\\to\\workspace"
              value={dir}
              onChange={(e) => setDir(e.target.value)}
              spellCheck={false}
            />
            <Button variant="default" data-testid="mosaic-browse" onClick={onBrowse}>
              Browse…
            </Button>
          </div>
          <div className={styles.field}>
            <label className={styles.fieldLabel} htmlFor="mosaic-basename">
              Basename
            </label>
            <input
              id="mosaic-basename"
              type="text"
              data-testid="mosaic-basename"
              className={styles.input}
              value={basename}
              onChange={(e) => setBasename(e.target.value)}
              spellCheck={false}
            />
          </div>
        </section>

        {/* ── OUTPUTS ── */}
        <section className={styles.section}>
          <div className={styles.legendRow}>
            <span className={styles.legend}>Outputs</span>
          </div>
          <div className={styles.chips}>
            <OutputChip
              testid="mosaic-out-tiff"
              label="16-bit TIFF + coverage mask"
              on={sel.tiff}
              onToggle={() => toggle('tiff')}
              help={
                'The coverage mask is MANDATORY, not optional: 13.1 % of the canvas is background encoded as exactly 0.0, indistinguishable from a black pixel, and a TIFF has no alpha channel. Without the sidecar, “empty” and “black” merge forever (R37).'
              }
            />
            <OutputChip
              testid="mosaic-out-png"
              label="display PNG"
              on={sel.png}
              onToggle={() => toggle('png')}
              help={
                'An 8-bit render through the global tone window — for looking at, not for measuring.'
              }
            />
            <OutputChip
              testid="mosaic-out-csv"
              label="positions.csv"
              on={sel.positions}
              onToggle={() => toggle('positions')}
              help={'trial, x, y, state — top-left world corners, one row per placed tile.'}
            />
            <OutputChip
              testid="mosaic-out-gt"
              label="ground-truth JSON"
              on={sel.gt}
              onToggle={() => toggle('gt')}
              help={'The scoreable ground-truth document. It carries the provenance stamp above.'}
            />
            <OutputChip
              testid="mosaic-out-qc"
              label="QC report"
              on={sel.qc}
              onToggle={() => toggle('qc')}
              help={
                'What the human did vs what the machine said — written as both JSON and Markdown.'
              }
            />
          </div>
        </section>

        {/* ── RENDER OPTIONS ── */}
        <section className={styles.section}>
          <div className={styles.legendRow}>
            <span className={styles.legend}>Render</span>
          </div>

          <div className={styles.field}>
            <label className={styles.fieldLabel} htmlFor="mosaic-render-mode">
              Mode
              <Help
                body={
                  'feather is the seamless default. median de-seams heavy overlap; alpha lays tiles straight over. Only feather is fast enough to be interactive.'
                }
              />
            </label>
            <select
              id="mosaic-render-mode"
              data-testid="mosaic-render-mode"
              className={styles.select}
              value={renderMode}
              onChange={(e) => setRenderMode(e.target.value as RenderMode)}
            >
              <option value="feather">Feather — seamless (~1 s)</option>
              <option value="median">Median — de-seams overlap (~42 s)</option>
              <option value="alpha">Alpha — straight over (~74 s)</option>
            </select>
          </div>

          <div className={styles.switchRow}>
            <button
              type="button"
              role="switch"
              aria-checked={includeUnverified}
              data-testid="mosaic-include-unverified"
              className={cx(styles.chip, includeUnverified && styles.chipOn)}
              onClick={() => setIncludeUnverified((v) => !v)}
            >
              <span className={styles.chipMark} aria-hidden="true" />
              <span className={styles.chipLabel}>include unverified</span>
            </button>
            <Help
              body={
                'On: unverified (placed but not certified) tiles are rendered and exported. Off: only anchored tiles ship. excluded and unplaced never render either way.'
              }
            />
          </div>

          <div className={styles.field}>
            <label className={styles.fieldLabel} htmlFor="mosaic-umperpx">
              µm / px
              <Help
                body={
                  'Blank = pixels only (no scale bar, no OME-TIFF PhysicalSize). A number you type IS written, and stamped “user-supplied by hand, not measured” — the absolute scale is not yet safe to assert automatically.'
                }
              />
            </label>
            <input
              id="mosaic-umperpx"
              type="number"
              step="0.001"
              min="0"
              data-testid="mosaic-umperpx"
              className={cx(styles.input, styles.inputNarrow, !umValid && styles.inputBad)}
              placeholder="pixels only"
              value={umPerPx}
              onChange={(e) => setUmPerPx(e.target.value)}
            />
            {!umValid && (
              <span className={styles.inlineBad}>enter a positive number, or leave blank</span>
            )}
          </div>
        </section>

        {/* ── EXPORT ── */}
        <section className={styles.section}>
          <div className={styles.exportRow}>
            <Button
              variant="primary"
              size="lg"
              data-testid="mosaic-export"
              disabled={!canExport}
              onClick={onExport}
            >
              {exporting ? 'Exporting…' : 'Export'}
            </Button>
            {phase && <span className={styles.phase}>{phase}</span>}
          </div>

          {/* Autosave note — the rolling crash-net, SEPARATE from Save… (R5.4). Loud on failure (W4). */}
          {autosave.state === 'failed' ? (
            <div data-testid="mosaic-autosave-note" className={styles.autosaveWrap}>
              <LiveWarning variant="loud">
                autosave: FAILED{autosave.message ? ` — ${autosave.message}` : ''}. Save by hand
                (Ctrl+S).
              </LiveWarning>
            </div>
          ) : (
            <p data-testid="mosaic-autosave-note" className={styles.autosaveNote}>
              <span className={styles.autosaveLabel}>autosave</span>
              <span className={styles.autosaveValue}>{AUTOSAVE_TEXT[autosave.state]}</span>
              <Help
                body={
                  'A rolling crash-net into the workspace — NOT your project file. Use Save… in the top bar (or Ctrl+S) for a file you control (R5.4).'
                }
              />
            </p>
          )}

          {error && (
            <div className={styles.errorWrap}>
              <LiveWarning variant="loud">Export failed: {error}</LiveWarning>
            </div>
          )}
        </section>

        {/* ── RESULT — the written files ── */}
        {result && (
          <section className={styles.section}>
            <div className={styles.legendRow}>
              <span className={styles.legend}>Written {result.files.length} files</span>
            </div>
            <ul className={styles.files} data-testid="export-files">
              {result.files.map((f) => (
                <li
                  key={f.path}
                  className={styles.file}
                  data-testid="export-file"
                  data-kind={f.kind}
                  data-path={f.path}
                >
                  <span className={styles.fileKind}>{KIND_LABEL[f.kind] ?? f.kind}</span>
                  <span className={styles.filePath} title={f.path}>
                    {f.path}
                  </span>
                  <span className={styles.fileBytes}>{fmtBytes(f.bytes)}</span>
                </li>
              ))}
            </ul>
            {exportedProv && (
              <p className={styles.stampConfirm}>
                Exported GT stamped{' '}
                <span className={styles.mono}>
                  independent_of_method: {String(exportedProv.independent_of_method)}
                </span>
                {exportedProv.warning ? ' — do-not-score warning included.' : '.'}
              </p>
            )}
            {result.warnings && result.warnings.length > 0 && (
              <ul className={styles.warnings}>
                {result.warnings.map((w, i) => (
                  <li key={i}>{w}</li>
                ))}
              </ul>
            )}
          </section>
        )}
      </div>
    </div>
  );
}

const AUTOSAVE_TEXT: Record<string, string> = {
  idle: 'not started',
  pending: 'pending…',
  saving: 'saving…',
  ok: 'saved',
  failed: 'FAILED',
};

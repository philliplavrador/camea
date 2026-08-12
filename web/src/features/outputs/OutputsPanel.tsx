// ─────────────────────────────────────────────────────────────────────────────────────────────
// OUTPUTS — ⭐ **THE ONLY DOOR TO A PROJECT'S FILES** (his ruling, 2026-08-10 — BEHAVIOUR R44).
//
//   *"if users want to browse their project data they have to do it through the app itself"*
//   *"click into a project and browse your outputs, select the one(s) you want and save it into
//    somewhere"*
//
// So this panel is the whole of "browse your project data": what the project built, what each file
// is, a look at the images, and one action — take a copy of the ones you ticked, to a folder you
// name right here. ⛔ There is no "Open folder" button anywhere in Camea any more; `revealPath` and
// `POST /api/fs/reveal` were deleted the same day.
//
// ⚠️ **It lists the DIRECTORY, not the document.** `build.outputs` says what the last build wrote;
// this has to say what is *there* — a file an older Camea wrote under a different name, or one
// deleted underneath us, shows up as it actually is.
//
// 🔴 **THE COPY IS THE ONLY WRITE, AND ITS REFUSALS ARE SHOWN VERBATIM.** The backend refuses a
// destination inside a dataset (never onto the evidence) and refuses to overwrite anything already
// in his folder, naming the files. Both messages are worth reading, so they land inline — never a
// toast that scrolls away while he is looking at the path he typed.
// ─────────────────────────────────────────────────────────────────────────────────────────────

import { useCallback, useEffect, useState } from 'react';
import { copyOutputs, listOutputs, outputUrl } from '../../api';
import type { OutputEntry } from '../../api';
import { Help } from '../../design/primitives/Help';
import { FolderPicker } from '../home/FolderPicker';
import { PathField } from '../home/PathField';
import { shortPath } from '../home/pathText';
import styles from './OutputsPanel.module.css';

const OUTPUTS_HELP =
  'Everything this project has built. Camea keeps these files itself, so this panel is how you ' +
  'look at them. Tick the ones you want and choose a folder to copy them into — the project keeps ' +
  'its own copy either way.';

export interface OutputsPanelProps {
  analysisId: string;
  /** Changes when a build finishes, so the list refreshes and image previews bust their cache. */
  version?: string | null;
  /** Heading copy, for a feature screen that wants its own wording. */
  title?: string;
}

export function OutputsPanel({ analysisId, version, title = 'Outputs' }: OutputsPanelProps) {
  const [outputs, setOutputs] = useState<OutputEntry[] | null>(null);
  const [chosen, setChosen] = useState<Set<string>>(new Set());
  const [preview, setPreview] = useState<string | null>(null);
  const [browsing, setBrowsing] = useState(false);
  const [copiedTo, setCopiedTo] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    setLoadError(null);
    listOutputs(analysisId)
      .then((r) => {
        if (!live) return;
        const found = r.outputs ?? [];
        setOutputs(found);
        // Drop ticks for files that are gone — a stale selection would copy a 404.
        setChosen((prev) => new Set([...prev].filter((n) => found.some((o) => o.name === n))));
      })
      .catch((e: unknown) => {
        if (live) setLoadError(e instanceof Error ? e.message : String(e));
      });
    return () => {
      live = false;
    };
  }, [analysisId, version]);

  const toggle = useCallback((name: string) => {
    setCopiedTo(null);
    setChosen((prev) => {
      const next = new Set(prev);
      if (!next.delete(name)) next.add(name);
      return next;
    });
  }, []);

  /** ⚠️ Throws on failure ON PURPOSE — `PathField` shows the backend's reason inline and KEEPS the
   *  typed path. A refusal here ("that folder already contains mosaic.png") is exactly the message
   *  he needs to read while deciding where else to put it. */
  const copyInto = useCallback(
    async (dest: string) => {
      const res = await copyOutputs(analysisId, [...chosen], dest);
      setCopiedTo(res.dest);
    },
    [analysisId, chosen],
  );

  const all = outputs ?? [];
  const nChosen = chosen.size;

  return (
    <section className={styles.panel} data-testid="outputs-panel">
      <h2 className={styles.label}>
        {title}
        <Help body={OUTPUTS_HELP} />
      </h2>

      {loadError && <p className={styles.error}>Could not read this project's outputs: {loadError}</p>}

      {outputs !== null && all.length === 0 && !loadError && (
        <p className={styles.empty} data-testid="outputs-empty">
          Nothing built yet. When this project produces files, they appear here.
        </p>
      )}

      {all.length > 0 && (
        <>
          <ul className={styles.list} data-testid="outputs-list">
            {all.map((o) => (
              <li key={o.name} className={styles.row} data-testid="output-row" data-name={o.name}>
                <label className={styles.pick}>
                  <input
                    type="checkbox"
                    checked={chosen.has(o.name)}
                    onChange={() => toggle(o.name)}
                    aria-label={`Select ${o.name}`}
                    data-testid="output-pick"
                  />
                </label>
                <span className={styles.name} title={o.name}>
                  {o.name}
                </span>
                <span className={styles.meta}>{formatBytes(o.bytes)}</span>
                <span className={styles.meta}>{formatWhen(o.modified)}</span>
                {o.previewable ? (
                  <button
                    type="button"
                    className={styles.look}
                    onClick={() => setPreview(preview === o.name ? null : o.name)}
                    data-testid="output-look"
                  >
                    {preview === o.name ? 'Hide' : 'Look'}
                  </button>
                ) : (
                  <span className={styles.look} aria-hidden="true" />
                )}
              </li>
            ))}
          </ul>

          {preview && (
            <figure className={styles.preview} data-testid="output-preview">
              <img
                className={styles.previewImg}
                src={outputUrl(analysisId, preview, { v: version ?? undefined })}
                alt={preview}
              />
              <figcaption className={styles.previewCap}>{preview}</figcaption>
            </figure>
          )}

          {/* ── SAVE A COPY INTO… — the one place work leaves Camea ─────────────── */}
          <div className={styles.copy} data-testid="outputs-copy">
            <p className={styles.copyLede}>
              {nChosen === 0
                ? 'Tick the files you want to take a copy of.'
                : `${nChosen} selected — where should the ${nChosen === 1 ? 'copy' : 'copies'} go?`}
            </p>
            {nChosen > 0 && (
              <PathField
                submitLabel="Save a copy"
                placeholder="paste a folder to copy them into…"
                onSubmit={copyInto}
                onBrowse={() => setBrowsing(true)}
                data-testid="copy-into-field"
              />
            )}
            {copiedTo && (
              <p className={styles.copied} data-testid="outputs-copied">
                Copied into <span className={styles.copiedPath}>{shortPath(copiedTo, 52)}</span>
              </p>
            )}
          </div>
        </>
      )}

      {browsing && (
        <FolderPicker
          title="Where should the copies go?"
          confirmLabel="Copy here"
          onPick={(p) => {
            setBrowsing(false);
            // Swallowed: the picker is gone by now, so there is no inline slot to show a refusal in.
            // The typed box is the drivable path and the one that reports (R38).
            void copyInto(p).catch(() => undefined);
          }}
          onClose={() => setBrowsing(false)}
        />
      )}
    </section>
  );
}

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} kB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

function formatWhen(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  return d.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

export default OutputsPanel;

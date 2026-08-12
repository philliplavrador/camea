import { useEffect, useState } from 'react';
import { useSweepStore, counts as computeCounts } from '../../store';
import { pickDirectory } from '../../../../api';
import { useToast } from '../../../../app';
import { Button, Help } from '../../../../design';
import type { LoadStepProps } from '../types';
import shell from '../step.module.css';
import styles from './LoadStep.module.css';

const DIR_HELP =
  'A vscope acquisition directory: the trial .dat files plus log.txt.\n\nNothing in it is ever written to.';
const RESUME_HELP =
  'A project file is the app’s ONLY memory. It carries your exclusions, every placement, which ' +
  'tiles you anchored, where you were in the sweep, and the build.\n\nLoad one and you pick up exactly ' +
  'where you left off. The app itself remembers nothing between runs.';

const errMsg = (e: unknown): string => (e instanceof Error ? e.message : String(e));

/**
 * 1 · LOAD — confirm the dataset the browser opened, or point at another one (BEHAVIOUR §2 step 1).
 *
 * The dataset arrived from the home browser (opening a card navigates straight into the feature, with
 * the sweep store hydrated — R4.5), so this screen's FIRST job is to say, honestly, what is open: the
 * name, the trial count that is on disk, and 0 excluded (R2.1/R2.2 — never "N usable of M, K thrown
 * out"). Its secondary affordances (open a different directory, `Load a project…`) drive the session
 * lifecycle the shell owns, delegated up via callbacks.
 *
 * ⛔ There is NO `#load-result`: opening a directory NAVIGATES (R4.5/§6.6); it never reveals a result
 * block in place.
 */
export function LoadStep({ onOpenDirectory, onLoadProject, openPhase }: LoadStepProps) {
  const doc = useSweepStore((s) => s.doc);
  const order = useSweepStore((s) => s.order);
  const toast = useToast();

  const [dir, setDir] = useState('');
  const [busy, setBusy] = useState(false);
  const [phase, setPhase] = useState<string | null>(null);

  // Seed the directory field from the opened dataset once, without fighting the user's typing.
  useEffect(() => {
    if (doc?.data_dir && dir === '') setDir(doc.data_dir);
  }, [doc?.data_dir, dir]);

  const excluded = doc ? computeCounts(doc.tiles, order).excluded : 0;
  const activePhase = openPhase ?? phase;

  async function browse() {
    const picked = await pickDirectory({ start: dir || doc?.data_dir || null });
    if (picked) setDir(picked);
  }

  async function open() {
    const target = dir.trim();
    if (!target) {
      toast.push('Pick a directory first.', { tone: 'danger' });
      return;
    }
    if (!onOpenDirectory) {
      toast.push('Open a dataset from the Camea home (the dataset browser).', { tone: 'default' });
      return;
    }
    setBusy(true);
    setPhase('opening…');
    try {
      await onOpenDirectory(target); // the shell opens the session, hydrates, and lands on Range
    } catch (e) {
      toast.push(`Open failed: ${errMsg(e)}`, { tone: 'danger' });
    } finally {
      setBusy(false);
      setPhase(null);
    }
  }

  async function loadProject() {
    if (!onLoadProject) {
      // ⚠️ Nothing has passed `onLoadProject` since the 2026-07-24 project-manager reframe: your work
      // is auto-saved into the project and you resume it by opening it. (The old message pointed at
      // "the dataset browser", a screen removed on 2026-07-25.) Importing a `.camea.json` someone
      // sent you is not wired up yet — say so plainly rather than appearing to do nothing.
      toast.push('Your work is saved automatically — reopen this project from the home screen.', {
        tone: 'default',
      });
      return;
    }
    setBusy(true);
    try {
      await onLoadProject();
    } catch (e) {
      toast.push(`Load failed: ${errMsg(e)}`, { tone: 'danger' });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className={shell.pane}>
      <header className={shell.head}>
        <h1 className={shell.h1}>
          Load
          <Help body={DIR_HELP} />
        </h1>
        <p className={shell.lede}>The dataset that is open. Point at another to start fresh.</p>
      </header>

      {doc && (
        <div className={styles.confirm}>
          <div className={styles.confirmName} data-testid="load-open-dataset">
            {doc.dataset}
          </div>
          <div className={styles.confirmFacts}>
            <span className={styles.stat}>
              <b className={styles.statN}>{order.length}</b> trials
            </span>
            <span className={styles.statSep}>&middot;</span>
            <span className={styles.stat}>
              <b className={styles.statN}>{excluded}</b> excluded
            </span>
          </div>
          {doc.data_dir && (
            <div className={styles.confirmPath} title={doc.data_dir}>
              {doc.data_dir}
            </div>
          )}
        </div>
      )}

      <div className={shell.inline}>
        <label className={`${shell.field} ${shell.grow}`}>
          <span className={shell.fieldLabel}>directory</span>
          <input
            className={shell.input}
            type="text"
            spellCheck={false}
            placeholder="D:/…/acquisition"
            value={dir}
            onChange={(e) => setDir(e.target.value)}
            data-testid="load-dir"
          />
        </label>
        <Button variant="default" onClick={browse} data-testid="load-browse" disabled={busy}>
          Browse…
        </Button>
        <Button variant="primary" onClick={open} data-testid="load-open" disabled={busy}>
          Open
        </Button>
      </div>

      <div className={styles.phase} data-testid="load-phase" aria-live="polite">
        {activePhase}
      </div>

      <h2 className={shell.h2}>
        Resume
        <Help body={RESUME_HELP} />
      </h2>
      <div className={styles.resume}>
        <Button variant="default" onClick={loadProject} data-testid="load-project" disabled={busy}>
          Load a project…
        </Button>
        <span className={shell.muted}>&hellip;or open a directory above to start fresh.</span>
      </div>
    </div>
  );
}

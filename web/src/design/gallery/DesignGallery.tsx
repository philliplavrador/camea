import { useState } from 'react';
import type { ReactNode } from 'react';
import '../index.css';
import {
  Badge,
  Button,
  Card,
  Help,
  IconButton,
  Kbd,
  LiveWarning,
  MOSAIC_STEPS,
  Panel,
  PerfReadout,
  Reticle,
  StatusBar,
  StatusItem,
  Stepper,
  Toggle,
} from '../index';
import styles from './DesignGallery.module.css';

const SURFACES: Array<[string, string]> = [
  ['--canvas', 'canvas · the stage'],
  ['--bg', 'bg'],
  ['--bg-raised', 'bg-raised · chrome'],
  ['--bg-card', 'bg-card'],
  ['--bg-inset', 'bg-inset'],
];

const DATA_HUES: Array<[string, string]> = [
  ['--anchored', 'anchored'],
  ['--unverified', 'unverified'],
  ['--thin-margin', 'thin-margin'],
  ['--cursor', 'cursor'],
  ['--alt', 'alt'],
  ['--diverted', 'diverted'],
  ['--excluded', 'excluded'],
  ['--accent', 'accent'],
];

function Swatch({ token, label }: { token: string; label: string }) {
  return (
    <div className={styles.swatch}>
      <span className={styles.chip} style={{ background: `var(${token})` }} />
      <span className={styles.swMeta}>
        <span className={styles.swName}>{label}</span>
        <span className={styles.swToken}>{token}</span>
      </span>
    </div>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className={styles.section}>
      <h2 className={styles.sectionTitle}>{title}</h2>
      {children}
    </section>
  );
}

/** Every primitive, once. Rendered inside each themed column. Interactive so state can be exercised. */
function Showcase() {
  const [cache, setCache] = useState(true);
  const [outstanding, setOutstanding] = useState(false);
  const [diff, setDiff] = useState(false);
  const [step, setStep] = useState('sweep');

  return (
    <div className={styles.body}>
      <Section title="Signature · the reticle over the true-black stage">
        <Reticle />
        <p className={styles.caption}>
          The sweep cursor locks onto the tile&rsquo;s <strong>top-left</strong> corner (positions are
          corners, never centres). The four numbers beside it are the only thing he acts on.
        </p>
        <div className={styles.reticlePair}>
          <div>
            <Reticle x={-268} y={432} ncc={0.907} margin={0.42} />
            <p className={styles.captionSm}>confident</p>
          </div>
          <div>
            <Reticle x={-14} y={176} ncc={0.761} margin={0.06} thin />
            <p className={styles.captionSm}>thin margin — the alias ghosts in, the readout goes red</p>
          </div>
        </div>
      </Section>

      <Section title="Surfaces · the two blacks">
        <div className={styles.swatchGrid}>
          {SURFACES.map(([t, l]) => (
            <Swatch key={t} token={t} label={l} />
          ))}
        </div>
      </Section>

      <Section title="Data palette · every hue is a tile state">
        <div className={styles.swatchGrid}>
          {DATA_HUES.map(([t, l]) => (
            <Swatch key={t} token={t} label={l} />
          ))}
        </div>
      </Section>

      <Section title="Type · the instrument readout inversion">
        <div className={styles.typeRow}>
          <span className={styles.readoutLg}>0.907</span>
          <span className={styles.typeLabel}>NCC · the measurement is the figure</span>
        </div>
        <div className={styles.typeRow}>
          <span className={styles.readout}>(-268, 432)</span>
          <span className={styles.typeLabel}>top-left · mono, tabular</span>
        </div>
        <div className={styles.typeRow}>
          <span className={styles.bodyText}>Certified against a 5-anchor field.</span>
          <span className={styles.typeLabel}>humanist sans · the quiet ground</span>
        </div>
      </Section>

      <Section title="Buttons">
        <div className={styles.row}>
          <Button variant="primary">Place the tiles</Button>
          <Button>Load a project</Button>
          <Button variant="ghost">Cancel</Button>
          <Button variant="danger">Skip — place by hand</Button>
          <Button disabled>Disabled</Button>
        </div>
        <div className={styles.row}>
          <Button variant="primary" kbd="Space">
            Next
          </Button>
          <Button kbd="A">Anchor</Button>
          <Button variant="danger" kbd="E">
            Exclude
          </Button>
          <Button size="sm">Small</Button>
          <Button size="lg" variant="primary">
            Large
          </Button>
        </div>
      </Section>

      <Section title="Icon buttons · toggles · keycaps">
        <div className={styles.row}>
          <IconButton aria-label="Fit to viewport">
            <FitIcon />
          </IconButton>
          <IconButton aria-label="Undo" variant="ghost">
            <UndoIcon />
          </IconButton>
          <IconButton aria-label="Remove" variant="danger">
            <CrossIcon />
          </IconButton>
          <Toggle checked={cache} onChange={setCache}>
            use cache
          </Toggle>
          <Toggle checked={outstanding} onChange={setOutstanding}>
            outstanding only
          </Toggle>
          <Toggle checked={diff} onChange={setDiff} kbd="D">
            Difference
          </Toggle>
        </div>
        <div className={styles.row}>
          <Kbd>A</Kbd>
          <Kbd>E</Kbd>
          <Kbd wide>Space</Kbd>
          <Kbd>1</Kbd>
          <Kbd>9</Kbd>
          <span className={styles.inline}>
            Snap <Kbd>S</Kbd> re-runs the matcher locally.
          </span>
        </div>
      </Section>

      <Section title="Tile-state badges">
        <div className={styles.row}>
          <Badge state="anchored">anchored</Badge>
          <Badge state="unverified">unverified</Badge>
          <Badge state="diverted">diverted</Badge>
          <Badge state="excluded">excluded</Badge>
          <Badge state="unplaced">unplaced</Badge>
          <Badge state="blank">blank</Badge>
          <Badge state="cursor">cursor</Badge>
          <Badge state="gpu">GPU</Badge>
        </div>
      </Section>

      <Section title="Help · the one explanation surface">
        <p className={styles.inline}>
          Everything explanatory hides behind a hover <Help body={'use cache is a SPEED switch, not a correctness one.\nwarm ≈ 25 s · cold ≈ 3 min.\nA trial-list/config mismatch is refused, not repaired.'} />{' '}
          — assume he knows; if he does not, he can hover.
          <span className={styles.inline}>
            {' '}
            A <code>?</code> with an empty body{' '}
            <Help body="" />
            hides itself.
          </span>
        </p>
      </Section>

      <Section title="Live warnings · they stay on the page">
        <LiveWarning>
          <b>THE BUILD IS STALE.</b> 3 excluded since the build (12, 15, 18). Re-solve, or knowingly
          do not.
        </LiveWarning>
        <LiveWarning variant="loud" help={'best − second < 0.10 is the signature of a surviving grid alias.\nThe electrode grid repeats every 256 px. Check D and V before you anchor.'}>
          <b>THIN MARGIN.</b> best &minus; second is <b>0.06</b>. The correlator found a second position
          almost as good.
        </LiveWarning>
        <LiveWarning variant="info">
          <b>SOLVER&rsquo;S POSITION, NOT THE MATCHER&rsquo;S.</b> The match was not confident and
          disagreed by 41 px. The matcher wanted (188, 94).
        </LiveWarning>
        <LiveWarning variant="loud">
          <b>No anchors left</b> — press <b>A</b> on a placed tile to certify one.
        </LiveWarning>
        <LiveWarning>
          <b>REFUSED — blank.</b> The matcher gets no vote here (texture 84 &lt; threshold 140). Drop
          it by hand, or exclude it.
        </LiveWarning>
        <LiveWarning>
          <b>NOT AN INDEPENDENT GROUND TRUTH.</b> Every position started as the solver&rsquo;s output.
          Never score the method with this file.
        </LiveWarning>
      </Section>

      <Section title="Stepper · a progress indicator, not a menu">
        <Stepper
          steps={MOSAIC_STEPS}
          current={step}
          reachable={5}
          onStepClick={(id, locked) => {
            if (!locked) setStep(id);
          }}
        />
        <p className={styles.captionSm}>
          Sweep is reachable with a session; Mosaic is locked until something is placed. A locked click
          toasts, it does not navigate.
        </p>
      </Section>

      <Section title="Panels · the rail unit">
        <div className={styles.panelRow}>
          <Card flush className={styles.railCard}>
            <Panel title="Evidence" help="He watches the evidence strengthen; he does not take it on faith.">
              <dl className={styles.stat}>
                <div className={styles.statRow}>
                  <dt>NCC</dt>
                  <dd className={styles.statVal}>0.907</dd>
                </div>
                <div className={styles.statRow}>
                  <dt>margin</dt>
                  <dd className={styles.statVal}>0.42</dd>
                </div>
                <div className={styles.statRow}>
                  <dt>anchors</dt>
                  <dd className={styles.statVal}>5</dd>
                </div>
                <div className={styles.statRow}>
                  <dt>took</dt>
                  <dd className={styles.statVal}>31 ms</dd>
                </div>
              </dl>
            </Panel>
            <Panel title="Keys">
              <div className={styles.row}>
                <Kbd>A</Kbd>
                <Kbd>E</Kbd>
                <Kbd wide>Space</Kbd>
                <Kbd>D</Kbd>
                <Kbd>V</Kbd>
                <Kbd>S</Kbd>
              </div>
            </Panel>
          </Card>
        </div>
      </Section>

      <Section title="Status bar · the footer readout (must read ~6 ms)">
        <StatusBar>
          <StatusItem label="trial">12</StatusItem>
          <StatusItem>
            <Badge state="unverified">unverified</Badge>
          </StatusItem>
          <StatusItem label="pass">1</StatusItem>
          <StatusItem label="top-left">(-268, 432)</StatusItem>
          <PerfReadout msPerFrame={6.1} fps={60} />
        </StatusBar>
      </Section>
    </div>
  );
}

/* Minimal inline icons — the design system carries no icon dependency; these demonstrate IconButton. */
function FitIcon() {
  return (
    <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
      <path d="M2 6V2h4M14 6V2h-4M2 10v4h4M14 10v4h-4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
function UndoIcon() {
  return (
    <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
      <path d="M6 4L2.5 7.5 6 11M2.5 7.5H10a3.5 3.5 0 0 1 0 7H7" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
function CrossIcon() {
  return (
    <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
      <path d="M4 4l8 8M12 4l-8 8" strokeLinecap="round" />
    </svg>
  );
}

/**
 * The /design gallery — every primitive, in BOTH themes, for screenshotting. Each column re-themes its
 * subtree via a nested `data-theme` attribute (the token file answers `[data-theme]` at any depth).
 */
export function DesignGallery() {
  return (
    <div className={styles.page}>
      <header className={styles.head}>
        <h1 className={styles.h1}>Camea design system</h1>
        <p className={styles.sub}>
          The instrument vocabulary — tokens, type, and primitives. Left: dark (the working theme).
          Right: light (the bright bench).
        </p>
      </header>
      <div className={styles.themes}>
        <div className={styles.themeCol} data-theme="dark">
          <div className={styles.themeLabel}>Dark</div>
          <Showcase />
        </div>
        <div className={styles.themeCol} data-theme="light">
          <div className={styles.themeLabel}>Light</div>
          <Showcase />
        </div>
      </div>
    </div>
  );
}

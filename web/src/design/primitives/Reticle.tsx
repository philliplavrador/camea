import { cx } from '../cx';
import styles from './Reticle.module.css';

export interface ReticleProps {
  /** The tile's TOP-LEFT world coordinate — positions in Camea are corners, never centres (R19). */
  x?: number;
  y?: number;
  ncc?: number;
  margin?: number;
  /** A thin margin — the readout goes red and the surviving alias ghosts in (BEHAVIOUR W2). */
  thin?: boolean;
  className?: string;
}

/**
 * THE SIGNATURE (see docs/DESIGN_BRIEF.md §4). The sweep cursor: a corner reticle locked onto the
 * TOP-LEFT of the tile under judgement, a mono readout beside it, over a true-black stage where the
 * certified field feathers into one seamless strip. Static here — the live canvas is the Sweep
 * feature's to wire; this is the vocabulary it is built from, not a feature screen.
 */
export function Reticle({ x = -268, y = 432, ncc = 0.907, margin = 0.42, thin = false, className }: ReticleProps) {
  const tx = 170;
  const ty = 70;
  const tw = 130;
  const th = 130;
  const b = 18; // reticle bracket arm length

  return (
    <div className={cx(styles.stage, className)}>
      <svg
        className={styles.svg}
        viewBox="0 0 400 250"
        preserveAspectRatio="xMidYMid meet"
        role="img"
        aria-label={`Sweep cursor — top-left (${x}, ${y}), NCC ${ncc.toFixed(3)}, margin ${margin.toFixed(2)}`}
      >
        <defs>
          <filter id="reticleSoft" x="-20%" y="-20%" width="140%" height="140%">
            <feGaussianBlur stdDeviation="7" />
          </filter>
        </defs>

        {/* the certified field — feathered into a seamless strip (R10) */}
        <g filter="url(#reticleSoft)">
          <rect className={styles.field} x="34" y="64" width="156" height="150" rx="12" />
          <rect className={styles.field} x="150" y="94" width="152" height="120" rx="12" />
        </g>

        {/* the faint 512-px world grid */}
        <g className={styles.grid}>
          <line x1="42" y1="26" x2="42" y2="228" />
          <line x1="298" y1="26" x2="298" y2="228" />
          <line x1="6" y1="70" x2="394" y2="70" />
        </g>

        {/* the surviving alias, only when the margin is thin */}
        {thin && <rect className={styles.alias} x={tx + 7} y={ty + 5} width={tw} height={th} />}

        {/* the ONE tile under judgement — crisp, never feathered (R10.2) */}
        <rect className={styles.tile} x={tx} y={ty} width={tw} height={th} />

        {/* corner reticle brackets, all four corners */}
        <path
          className={styles.bracket}
          d={`M${tx} ${ty + b} L${tx} ${ty} L${tx + b} ${ty}
              M${tx + tw - b} ${ty} L${tx + tw} ${ty} L${tx + tw} ${ty + b}
              M${tx} ${ty + th - b} L${tx} ${ty + th} L${tx + b} ${ty + th}
              M${tx + tw - b} ${ty + th} L${tx + tw} ${ty + th} L${tx + tw} ${ty + th - b}`}
        />

        {/* the crosshair centred on the TOP-LEFT corner (the anchor point, R19) */}
        <path
          className={styles.cross}
          d={`M${tx} ${ty - 26} L${tx} ${ty - 8} M${tx} ${ty + 8} L${tx} ${ty + 26}
              M${tx - 26} ${ty} L${tx - 8} ${ty} M${tx + 8} ${ty} L${tx + 26} ${ty}`}
        />
        <circle className={styles.dot} cx={tx} cy={ty} r="2.4" />

        {/* the readout — the only thing he acts on, in mono */}
        <rect className={styles.readout} x="250" y="8" width="134" height="58" rx="6" />
        <text className={styles.rLabel} x="258" y="27">TOP-LEFT</text>
        <text className={cx(styles.rVal, styles.rEnd)} x="376" y="27">{`(${x}, ${y})`}</text>
        <text className={styles.rLabel} x="258" y="42">NCC</text>
        <text className={cx(styles.rVal, styles.rEnd)} x="376" y="42">{ncc.toFixed(3)}</text>
        <text className={styles.rLabel} x="258" y="57">MARGIN</text>
        <text className={cx(styles.rVal, styles.rEnd, thin && styles.rBad)} x="376" y="57">
          {margin.toFixed(2)}
        </text>
      </svg>
    </div>
  );
}

import { Link, Outlet, useLocation } from 'react-router-dom';
import { ToastProvider } from './ToastProvider';
import { SaveControllerProvider, SaveButton } from './SaveController';
import { ThemeToggle } from './ThemeToggle';
import styles from './AppShell.module.css';

/**
 * The application shell. Camea's home is a DATASET BROWSER; MOSAIC is the first feature reached from
 * a dataset, and it will not be the last (segmentation, annotation). So the shell is deliberately
 * feature-agnostic: a quiet top bar plus a routed feature area. Nothing here knows about tiles,
 * anchors or passes — that vocabulary belongs to the mosaic feature inside <Outlet/>.
 *
 * Two cross-cutting shell services wrap the whole tree so both the top bar and the feature share them:
 *   • ToastProvider — the transient-message channel (locked-step nudge, resume confirmation…).
 *   • SaveControllerProvider — Save reachable from EVERY screen (R5): the shell owns the button and
 *     the global Ctrl/⌘+S; the feature registers WHAT to save.
 */
export function AppShell() {
  return (
    <ToastProvider>
      <SaveControllerProvider>
        <ShellFrame />
      </SaveControllerProvider>
    </ToastProvider>
  );
}

function ShellFrame() {
  // A feature is open on any route below the home index. The shell owns routing, so this is a
  // structural fact, not dataset knowledge — no path or key is hard-coded.
  const inFeature = useLocation().pathname !== '/';

  return (
    <div className={styles.shell}>
      <header className={styles.topbar} data-testid="topbar">
        <Link to="/" className={styles.brand} data-testid="home-link" aria-label="Camea home">
          <span className={styles.wordmark}>CAMEA</span>
          <span className={styles.tagline}>microscopy mosaics</span>
        </Link>
        <div className={styles.spacer} />
        <div className={styles.actions}>
          {/* Save… is present the whole time a feature is open — on every one of its screens (R5.1). */}
          {inFeature && <SaveButton />}
          <ThemeToggle />
        </div>
      </header>
      <main className={styles.main}>
        <Outlet />
      </main>
    </div>
  );
}

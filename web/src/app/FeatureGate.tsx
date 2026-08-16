// ─────────────────────────────────────────────────────────────────────────────────────────────
// FEATURE GATE — `/project/:id` dispatches on the project's FEATURE (2026-08-07). The route cannot
// know what a project is (mosaic? videomosaic?) until the server says so: this asks the server for
// that one project and mounts the feature that owns it. Features stay ignorant of each other — only
// this seam names them. MosaicFeature mounts exactly as the router used to mount it (it fetches its
// own document); VideoMosaicFeature takes the summary this gate already holds.
//
// ⚠️ It fetches the project BY ID, not by filtering `GET /api/projects`. A video mosaic that is
// still building is a DRAFT — reachable, but deliberately not on the home screen (R43.3) — so the
// old list-and-find would have answered "Project not found" for a project it had just created.
// ─────────────────────────────────────────────────────────────────────────────────────────────

import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { getProject } from '../api';
import type { AnalysisSummary } from '../api';
import { Button, Card, Progress, useDelayedFlag } from '../design';
// ⭐ RETIRED, STILL MOUNTED (2026-08-11): the SNAPSHOT builder moved to `src/legacy/mosaic` and is
// no longer offered on the New-project screen — but a project already built with it must still
// open, so this gate keeps dispatching `feature === 'mosaic'` to it. ⛔ Do not remove this arm.
import { MosaicFeature } from '../legacy/mosaic/MosaicFeature';
import { VideoMosaicFeature } from '../features/videomosaic/VideoMosaicFeature';
import { MeaFeature } from '../features/mea/MeaFeature';
import styles from './FeatureGate.module.css';

type GateState =
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'ready'; project: AnalysisSummary | null };

export function FeatureGate() {
  const { id } = useParams<{ id: string }>();
  const [state, setState] = useState<GateState>({ status: 'loading' });
  // ⏱️ R48.1 — one round trip, usually well under the 400 ms grace; a bar that flashed on every
  // project click would be worse than none. R48.9 — the read is a single request with no denominator
  // and nothing to poll, so it is the travelling sliver, not a filling bar.
  const opening = useDelayedFlag(state.status === 'loading');

  useEffect(() => {
    let live = true;
    setState({ status: 'loading' });
    if (!id) {
      setState({ status: 'ready', project: null });
      return;
    }
    getProject(id).then(
      (project) => {
        if (live) setState({ status: 'ready', project });
      },
      (e: unknown) => {
        // 404 is "no such project" — the card below says so. Anything else is a real failure and
        // must not be dressed up as a missing project.
        if (!live) return;
        const message = e instanceof Error ? e.message : String(e);
        if (/not found|no project with id/i.test(message))
          setState({ status: 'ready', project: null });
        else setState({ status: 'error', message });
      },
    );
    return () => {
      live = false;
    };
  }, [id]);

  if (state.status === 'loading') {
    return opening ? (
      <div className={styles.loading}>
        <Progress
          data-testid="gate-progress"
          label="Opening the project"
          pct={null}
          // R48.7 — one request with nothing to poll; the reason, not a dead button.
          unstoppableWhy="opening a project cannot be stopped once it starts"
        />
      </div>
    ) : null;
  }
  if (state.status === 'error') {
    return <GateCard title="Could not open the project" body={state.message} />;
  }
  const project = state.project;
  if (!project) {
    return (
      <GateCard
        title="Project not found"
        body="It may have been removed, or its folder is on a drive that is not plugged in."
      />
    );
  }
  if (project.feature === 'mosaic') return <MosaicFeature />;
  if (project.feature === 'videomosaic') return <VideoMosaicFeature project={project} />;
  // ⭐ The third task (2026-08-14): a MaxWell recording opened on its own. It takes the summary
  // this gate already holds, like the video feature — there is no document for it to fetch yet.
  if (project.feature === 'mea') return <MeaFeature project={project} />;
  return (
    <GateCard
      title="Unknown task"
      body={`This project's task ("${project.feature}") is not one this build of Camea can open.`}
    />
  );
}

function GateCard({ title, body }: { title: string; body: string }) {
  const navigate = useNavigate();
  return (
    <Card className={styles.gate} data-testid="feature-gate-error" role="alert">
      <h2 className={styles.gateTitle}>{title}</h2>
      <p className={styles.gateBody}>{body}</p>
      <div>
        <Button variant="ghost" onClick={() => navigate('/')}>
          ← Back to projects
        </Button>
      </div>
    </Card>
  );
}

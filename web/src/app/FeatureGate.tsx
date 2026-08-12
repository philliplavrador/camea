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
import { Button, Card } from '../design';
import { MosaicFeature } from '../features/mosaic/MosaicFeature';
import { VideoMosaicFeature } from '../features/videomosaic/VideoMosaicFeature';
import styles from './FeatureGate.module.css';

type GateState =
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'ready'; project: AnalysisSummary | null };

export function FeatureGate() {
  const { id } = useParams<{ id: string }>();
  const [state, setState] = useState<GateState>({ status: 'loading' });

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
    return <p className={styles.loading}>Opening project…</p>;
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

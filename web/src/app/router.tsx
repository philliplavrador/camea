import { createBrowserRouter } from 'react-router-dom';
import { AppShell } from './AppShell';
import { FeatureGate } from './FeatureGate';
import { ProjectManager } from '../features/home/ProjectManager';
import { NewProjectFlow } from '../features/home/NewProjectFlow';
import { DesignGallery } from '../design/gallery/DesignGallery';

/**
 * Routes (2026-07-24 project-manager reframe). The shell wraps every screen. The home index is the
 * PROJECT MANAGER ("what do you want to do today?"); `/new` is the create flow; a project opens into a
 * feature at `/project/:id` (the id is the analysis id) — the FeatureGate asks the server WHICH
 * feature owns the id (mosaic · videomosaic) and mounts it. React Router is the pick: a small,
 * standard nested-route model that maps onto "shell → project → step".
 */
export const router = createBrowserRouter([
  {
    path: '/',
    element: <AppShell />,
    children: [
      { index: true, element: <ProjectManager /> },
      { path: 'new', element: <NewProjectFlow /> },
      { path: 'project/:id', element: <FeatureGate /> },
    ],
  },
  // The design-system gallery — a full-page reference of every primitive in both themes, outside the
  // app shell so it reads as the standalone artefact it is. Owned by web/src/design/**.
  { path: '/design', element: <DesignGallery /> },
]);

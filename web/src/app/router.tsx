import { createBrowserRouter } from 'react-router-dom';
import { AppShell } from './AppShell';
import { ProjectManager } from '../features/home/ProjectManager';
import { NewProjectFlow } from '../features/home/NewProjectFlow';
import { MosaicFeature } from '../features/mosaic/MosaicFeature';
import { DesignGallery } from '../design/gallery/DesignGallery';

/**
 * Routes (2026-07-24 project-manager reframe). The shell wraps every screen. The home index is the
 * PROJECT MANAGER ("what do you want to do today?"); `/new` is the create flow; a project opens into a
 * feature at `/project/:id` (the id is the analysis id). Today the only task is Mosaic. React Router is
 * the pick: a small, standard nested-route model that maps onto "shell → project → step".
 */
export const router = createBrowserRouter([
  {
    path: '/',
    element: <AppShell />,
    children: [
      { index: true, element: <ProjectManager /> },
      { path: 'new', element: <NewProjectFlow /> },
      { path: 'project/:id', element: <MosaicFeature /> },
    ],
  },
  // The design-system gallery — a full-page reference of every primitive in both themes, outside the
  // app shell so it reads as the standalone artefact it is. Owned by web/src/design/**.
  { path: '/design', element: <DesignGallery /> },
]);

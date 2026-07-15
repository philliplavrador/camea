import { createBrowserRouter } from 'react-router-dom';
import { AppShell } from './AppShell';
import { DatasetBrowser } from '../features/home/DatasetBrowser';
import { MosaicFeature } from '../features/mosaic/MosaicFeature';
import { DesignGallery } from '../design/gallery/DesignGallery';

/**
 * Routes. The shell wraps every screen; the home index is the dataset browser; a dataset opens into
 * a feature. Today the only feature is Mosaic (a placeholder here — the six-step wizard mounts into
 * it). React Router is the pick: a small, standard nested-route model that maps exactly onto
 * "shell → feature → step", with typed params (:key) and no framework lock-in.
 */
export const router = createBrowserRouter([
  {
    path: '/',
    element: <AppShell />,
    children: [
      { index: true, element: <DatasetBrowser /> },
      { path: 'dataset/:key', element: <MosaicFeature /> },
    ],
  },
  // The design-system gallery — a full-page reference of every primitive in both themes, outside the
  // app shell so it reads as the standalone artefact it is. Owned by web/src/design/**.
  { path: '/design', element: <DesignGallery /> },
]);

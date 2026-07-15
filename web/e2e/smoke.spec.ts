import { test, expect } from '@playwright/test';

/**
 * SMOKE — proves the whole plumbing end to end: the Vite-built shell loads, it calls /api/datasets
 * through the dev proxy, the backend (headless, pointed at tests/fixtures) returns the committed
 * synthetic dataset, and the dataset browser renders it. Then opening the card navigates into the
 * mosaic feature. If this passes, the frontend ↔ backend contract is wired correctly.
 */
test('the dataset browser renders the synthetic fixture and opens it', async ({ page }) => {
  await page.goto('/');

  await expect(page.getByRole('heading', { name: 'Datasets' })).toBeVisible();

  const card = page.getByTestId('dataset-card').filter({ hasText: 'synthetic' });
  await expect(card).toBeVisible();

  // The counts come straight off /api/datasets — the fixture is a 10-tile run (11–20) plus a stray
  // snapshot and one off-shape frame = 12 readable snapshots, in two shape groups.
  await expect(card.getByTestId('dataset-snapshots')).toHaveText('12');
  await expect(card.getByTestId('dataset-shapes')).toContainText('512×512');

  // The thumbnail is served by the backend (one frame, no session), proxied through Vite.
  await expect(card.locator('img')).toHaveAttribute('src', /thumbnail\.png$/);

  // Opening a dataset navigates into a feature (Mosaic today).
  await card.click();
  await expect(page).toHaveURL(/\/dataset\/synthetic-/);
  await expect(page.getByRole('heading', { name: 'Mosaic' })).toBeVisible();
});

import { test, expect } from '@playwright/test';
import { readFileSync, existsSync } from 'node:fs';
import { Sweep, Wizard, TID, byId, enterMosaic, runBuild } from './pages';
import { SHORT } from './fixture';

/**
 * THE PROVENANCE STAMP survives an export (R28, W5): a document that started as a solver's output is
 * stamped `independent_of_method: false` with the warning, derived from HISTORY not from what it
 * claims. The export writes SEVEN files with the mandatory coverage mask (R37). "Skip — place by
 * hand" is destructive after a build (R27).
 *
 * @slow — these run a real build.
 */
test.describe('R28 / R37 — provenance + export', { tag: '@slow' }, () => {
  test('R28/W5: a seeded document is stamped NOT AN INDEPENDENT GROUND TRUTH on the Mosaic step', async ({
    page,
  }) => {
    await enterMosaic(page);
    await runBuild(page); // machine positions → the doc is now machine-seeded
    const wizard = new Wizard(page);
    await wizard.goto('mosaic');
    const stamp = byId(page, TID.provenanceStamp);
    await expect(stamp).toBeVisible({ timeout: SHORT });
    await expect(stamp).toContainText(/not an independent ground truth/i);
    // The frozen backend's PROVENANCE_WARNING reads "…MUST NEVER be used to score that method… the
    // score would be 100 % by construction." (BEHAVIOUR W5 paraphrases it "Never score t33 with this".)
    // Match the do-not-score intent against the backend's actual wording rather than an adjacent literal.
    await expect(stamp).toContainText(/never.*score|score.*by construction/i);
  });

  test('R28/R37: the exported gt.json is stamped independent_of_method:false, and 7 files are written', async ({
    page,
  }) => {
    await enterMosaic(page);
    await runBuild(page);

    // Certify at least one tile so there is real placed content to export.
    const wizard = new Wizard(page);
    await wizard.goto('sweep');
    const sweep = new Sweep(page);
    await sweep.focus();
    await sweep.press('a');

    await wizard.goto('mosaic');
    // ⭐ **NO OUTPUT FOLDER TO FILL IN** (R44): the export lands in this project's own outputs/, and
    // the Files panel below is how it leaves Camea. `basename` is what those files are CALLED.
    await expect(page.getByTestId('mosaic-dir')).toHaveCount(0);
    await byId(page, TID.mosaicBasename).fill('run');
    await byId(page, TID.mosaicExport).click();

    // The export writes exactly SEVEN files, and the coverage mask is mandatory (R37).
    const files = byId(page, TID.exportFile);
    await expect(files).toHaveCount(7, { timeout: 180_000 });
    const kinds = await files.evaluateAll((els) => els.map((e) => e.getAttribute('data-kind')));
    const paths = await files.evaluateAll((els) => els.map((e) => e.getAttribute('data-path')));
    // The frozen backend labels BOTH qc files (qc.json AND qc.md) with kind "qc" — it emits six distinct
    // kinds across the seven files, not a separate "qc_md" kind. Assert R37's real contract: the six
    // required kinds are all present (coverage mandatory), and the QC report ships as both JSON and
    // Markdown (a .md among the seven written paths).
    expect(new Set(kinds)).toEqual(new Set(['tiff', 'coverage', 'png', 'positions', 'gt', 'qc']));
    expect(paths.some((p) => (p ?? '').toLowerCase().endsWith('.md'))).toBe(true);

    // Read the gt.json the backend wrote and assert the provenance stamp survived (R28).
    // (data-kind / data-path sit on the export-file element itself.)
    const gtPath = await page
      .locator(`[data-testid="${TID.exportFile}"][data-kind="gt"]`)
      .getAttribute('data-path');
    expect(gtPath, 'the gt export must expose its written path').toBeTruthy();
    expect(existsSync(gtPath!)).toBe(true);
    const gt = JSON.parse(readFileSync(gtPath!, 'utf8'));
    expect(gt.provenance.independent_of_method).toBe(false);
    expect(gt.provenance.warning, 'the warning must ship in the file').toBeTruthy();

    // ⭐ **R44: and the Outputs panel lists exactly what was written**, so he can look at it and copy
    // out whichever files he wants. What the panel shows IS what is on disk — it reads the directory.
    const panel = page.getByTestId('outputs-panel');
    await expect(panel).toBeVisible({ timeout: 30_000 });
    const listed = await panel
      .getByTestId('output-row')
      .evaluateAll((els) => els.map((e) => e.getAttribute('data-name')));
    expect(new Set(listed)).toEqual(new Set(paths.map((f) => (f ?? '').split(/[\\/]/).pop())));

    // …and every one of them sits in the PROJECT's folder, which the user never named.
    for (const f of paths) expect(f).toMatch(/[\\/]outputs[\\/]/);
  });

  test('R27: "Skip — place by hand" after a build is DESTRUCTIVE and confirms with a count', async ({
    page,
  }) => {
    await enterMosaic(page);
    await runBuild(page);
    const wizard = new Wizard(page);
    await wizard.goto('place');

    // Skip must confirm (it discards every machine position) — never a silent laundering of a build
    // into an "independent" truth. We capture the confirm and DISMISS it (leave the build intact).
    let confirmMsg = '';
    page.once('dialog', (d) => {
      confirmMsg = d.message();
      return d.dismiss();
    });
    await byId(page, TID.placeSkip).click();
    await expect.poll(() => confirmMsg, { timeout: SHORT }).toMatch(/discard|\d+/i);
  });
});

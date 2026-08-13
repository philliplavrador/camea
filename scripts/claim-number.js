#!/usr/bin/env node
// Claim the next free NNN for an issue or a plan, atomically.
//
// Three commands file into these directories — /bug-hunter, /resolve and /build — and they
// run at the same time. Reading the directory yourself and adding one is a race: two
// sessions read `008`, both decide on `009`, and one silently overwrites the other's file.
// Two issues sharing a number is miserable to unpick by hand afterwards, because there is
// no record that a second one ever existed.
//
// The fix is one line: fs.writeFileSync(path, '', { flag: 'wx' }). The `wx` flag creates
// the file only if it does not already exist and throws EEXIST otherwise, instead of
// truncating what is there. Creation-or-fail is a single filesystem operation, so when two
// sessions try for 009 at the same instant exactly one wins; the loser catches EEXIST,
// increments to 010 and tries again. Nobody has to coordinate, and no lock is involved.
//
// THE FILE IT CREATES IS EMPTY, on purpose. The claim has to be instantaneous — anything
// this script wrote first would be a window in which the number is taken but the file
// looks unclaimed. The caller writes the body immediately afterwards, into the path this
// prints. An empty claimed file left behind by a crashed session is the obvious failure:
// you can see at a glance that it is a stub, and deleting it costs nothing.
//
// Usage:
//   node scripts/claim-number.js issue <high|medium|low> <slug>
//   node scripts/claim-number.js plan <slug>
//
// Prints the claimed path on stdout and nothing else, so it can be captured directly.
//
// Imported from the Labstock workflow, 2026-08-13. The only change is the repo layout:
// this file lives at scripts/, one level under the root, not app/scripts/.

const fs = require('fs');
const path = require('path');

// This file lives at scripts/, so the repo root is ONE level up. workflow/ sits at the root.
const ROOT = path.resolve(__dirname, '..');

// An issue's tier is its directory, and a plan's state is its directory, so a number is
// only free if it is unused across ALL of a kind's directories. Scanning just the one
// you are about to write into would hand out a number that a resolved issue already has.
const KINDS = {
  // `resolved` MUST be scanned: an issue is referred to by number in commits, plans and
  // other issues, so handing 312 out twice is the unpickable mess this script exists to
  // prevent — a closed issue's number is spent forever.
  issue: {
    dirs: ['high', 'medium', 'low', 'resolved'].map((d) => `workflow/issues/${d}`),
  },
  // 'parked' is a real plan state (interviewed enough to keep, not enough to build) and its
  // numbers are spent, so it MUST be scanned — a parked plan left out here would have its
  // number handed to the next `/plan`, and two different plans would answer to one id.
  plan: { dirs: ['queued', 'active', 'done', 'parked'].map((d) => `workflow/plans/${d}`) },
};

const TIERS = new Set(['high', 'medium', 'low']);

// Lowercase, digits and hyphens. Rejected rather than sanitized: a slug quietly rewritten
// from what you typed is a filename you will not find again when you go looking for it.
const SLUG = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;

// 50 is far more than any real collision needs — a genuine race is two or three sessions,
// not fifty. Running out means something else is wrong (an unwritable directory, say),
// and looping forever would hide it.
const MAX_RETRIES = 50;

const USAGE =
  'Usage: node scripts/claim-number.js issue <high|medium|low> <slug>\n' +
  '       node scripts/claim-number.js plan <slug>';

function die(msg) {
  console.error(`✗ ${msg}`);
  process.exit(1);
}

const kind = process.argv[2];
if (!kind) die(`No kind given — expected "issue" or "plan".\n${USAGE}`);
if (!KINDS[kind]) die(`Unknown kind "${kind}" — expected "issue" or "plan".\n${USAGE}`);

let tier = null;
let slug;

const args = process.argv.slice(2);

if (kind === 'issue') {
  tier = args[1];
  slug = args[2];
  if (!tier) die(`No tier given — expected one of high, medium, low.\n${USAGE}`);
  if (!TIERS.has(tier)) {
    die(
      `Unknown tier "${tier}" — expected one of high, medium, low.\n` +
        '  Tiers are judged against the science and against hours of hand-verification\n' +
        '  sitting in a saved project — see workflow/issues/README.md.\n' +
        `${USAGE}`,
    );
  }
  if (!slug) die(`No slug given.\n${USAGE}`);
} else {
  slug = args[1];
  if (!slug) die(`No slug given.\n${USAGE}`);
}

if (!SLUG.test(slug)) {
  die(
    `Bad slug "${slug}" — use lowercase letters, digits and single hyphens only.\n` +
      '  No uppercase, no underscores, no spaces, no leading or trailing hyphen.\n' +
      `  Try: ${slug
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, '-')
        .replace(/^-|-$/g, '')}`,
  );
}

// A plan is claimed into queued/ — /build is what moves it to active/. An issue is
// claimed straight into its tier.
const destDir = path.join(
  ROOT,
  kind === 'issue' ? `workflow/issues/${tier}` : 'workflow/plans/queued',
);
if (!fs.existsSync(destDir)) die(`No such directory: ${destDir}`);

// Highest NNN anywhere in this kind's directories, so numbers are never reused. A file
// that does not start with three digits and a hyphen (README.md, TEMPLATE.md, .gitkeep)
// is not a numbered one and is skipped.
let highest = 0;
for (const dir of KINDS[kind].dirs) {
  const full = path.join(ROOT, dir);
  if (!fs.existsSync(full)) continue; // a state directory can be legitimately absent
  for (const name of fs.readdirSync(full)) {
    const m = /^(\d{3})-/.exec(name);
    if (m) highest = Math.max(highest, Number(m[1]));
  }
}

for (let n = highest + 1; n <= highest + MAX_RETRIES; n++) {
  const num = String(n).padStart(3, '0');
  const claimed = path.join(destDir, `${num}-${slug}.md`);
  try {
    // The atomic step. See the header: `wx` fails rather than overwriting, so exactly
    // one caller wins each number.
    fs.writeFileSync(claimed, '', { flag: 'wx' });
    console.log(path.relative(ROOT, claimed).split(path.sep).join('/'));
    process.exit(0);
  } catch (err) {
    if (err.code === 'EEXIST') continue; // somebody else got this number — take the next
    die(`Could not create ${claimed}: ${err.message}`);
  }
}

die(
  `Gave up after ${MAX_RETRIES} attempts starting at ${String(highest + 1).padStart(3, '0')}.\n` +
    '  That many collisions is not a race — check that the directory is writable and that\n' +
    '  nothing is creating files there in a loop.',
);

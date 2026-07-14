/* ⭐ Camea Mosaic Builder — THE VERIFICATION SWEEP. This is the actual app.
 *
 * OWNER: agent 5. index.html and style.css are the CONTRACT and they are FINAL — read them, do not
 * edit them. CONTRACT: app/API.md — §2 (the tile state machine), §7 (the anchor-composite
 * primitive), §7.4 (the prefetch and its correctness trap), §15 (front-end obligations).
 *
 * THE BOUNDARY (see viewer.js's header): sweep.js owns the DOCUMENT, the undo/redo stack, the
 * keyboard map, every fetch(), the prefetch and the panels. It drives `window.Viewer` through its
 * public methods and NEVER touches its canvases.
 *
 *
 * ⛔⛔ THREE RULINGS FROM THE USER, 2026-07-14. They are why this file looks the way it does.
 * ------------------------------------------------------------------------------------------
 * 1. **THE APP KNOWS NOTHING ABOUT ANY DATASET.** *"The app itself shouldn't store the exclusions
 *    for this experiment."* There is NO built-in exclusion list, no "is this 260620d?" detection, no
 *    ruling, no auto-exclusion — not from the blank scan either, which only RECOMMENDS. **Every
 *    trial starts `unplaced`.** The ONLY things that ever exclude a frame are the human, here, now
 *    (`E`, or a tick on Screen) — and a PROJECT FILE he loaded. The project file is the app's entire
 *    memory: it is the one place an exclusion can come from, and `exportDoc()` writes no other.
 *
 * 2. **THE APP IS A TOOL, NOT AN EXPLAINER.** *"Assume the user knows. If they don't, they have the
 *    option to hover."* Every explanation lives behind a `?` (`.help[data-help]` -> `#help-tip`);
 *    every toast, banner and error is ONE SHORT CLAUSE.
 *
 *    🔴 **THE ONE EXCEPTION: A LIVE WARNING ABOUT THE CURRENT STATE IS NOT AN EXPLANATION.** A stale
 *    build · a thin margin · a diverted tile · a failed autosave · the provenance stamp. Those fire
 *    only when something is ACTUALLY WRONG and they change what he would DO. They stay on the page,
 *    loud. Their BACKGROUND may move onto a `?` on the warning; the fact that they are FIRING may
 *    not. Do not "tidy" one of them into a tooltip — every one of them is here because it, or its
 *    absence, has already cost this project real work.
 *
 * 3. **SIX STEPS.** Load -> Range -> Screen -> Place -> Sweep -> Mosaic. The header is a PROGRESS
 *    INDICATOR, not a menu: a step is locked until the ones before it are ready (`lockSteps`).
 *
 *
 * THE LOOP
 * --------
 *  1. The user picks the first snapshot he wants. It lands on a BLANK CANVAS and defines the
 *     origin — position [0, 0]. He presses `A`.
 *  2. For the tile currently under judgement:
 *       `A` — ANCHOR it.  Accept as ground truth. It joins the anchored background that everything
 *                         after it is judged against.
 *       `E` — EXCLUDE it. Dropped. (Too blurry, blank, whatever his eye says.)
 *       `Space` — ADVANCE to the next consecutive snapshot, skipping any already excluded.
 *  3. `Space` places the next snapshot and FADES IT IN OVER A FULL SECOND, transparent -> opaque.
 *     ⭐ *That fade is the whole point:* watching the tile materialise on top of the anchored
 *     background is how the user SEES whether it lines up.
 *  4. Repeat. `A` / `E` / `Space` — a very quick verification rhythm. No dialog, no confirmation,
 *     no spinner in the middle of it.
 *
 *
 * ⭐ SPACE WITHOUT A DECISION LEAVES THE TILE `unverified` — placed, drawn dimmer, **NOT part of
 *    the anchor field**, and it **does not block progress.** Deferring a hard tile must never stall
 *    the sweep. The header carries the outstanding-`unverified` counter. (API.md §2.)
 *
 *
 * 🔴🔴 THE PREFETCH, AND THE CORRECTNESS TRAP IN IT — READ THIS TWICE
 * -------------------------------------------------------------------
 * Every `Space` costs **1,068 ms (GPU) / 1,562 ms (CPU)** — a dead keyboard. We fire tile N+1's
 * match the instant tile N is DISPLAYED (not judged — displayed); it hides inside the 1 s fade AND
 * the user's own think-time. Perceived latency -> **~0 ms**.
 *
 *   🔴 **THE PREFETCH MUST INCLUDE THE TILE CURRENTLY UNDER JUDGEMENT IN `anchors`** — i.e. it must
 *      assume the user will press `A`. That branch is **exact by construction**.
 *
 *      Prefetching from the composite **WITHOUT** the current tile **disagrees with the truth in
 *      18 % of presses and is CATASTROPHICALLY WRONG (up to 1,143 px) in 6 %.**
 *
 *      **If the user presses `E` instead, THROW THE PREFETCH AWAY AND RECOMPUTE.**
 *      This is a CORRECTNESS requirement, not a speed choice.
 *
 * How this file obeys it without having to think about it: **THERE IS NO CLIENT-SIDE PREFETCH
 * CACHE.** `prefetchNext()` fires the *same* `POST /api/match/anchor` the foreground will fire, and
 * then **throws the answer away**. The server memoises on a hash of the anchor set (API.md §7.4), so
 * the foreground call is a ~1 ms memo HIT when — and only when — the anchor set it sends is the one
 * the prefetch assumed. Press `E`, or defer with `Space`, and the anchor set genuinely differs, the
 * key differs, the memo MISSES, and the server recomputes honestly. A wrong-composite answer can
 * never be *shown*, because nothing on this side ever stores one.
 *   ⇒ **NEVER add a `Map` keyed on the trial number here.** That is precisely how the trap gets
 *     sprung, and it would look like a harmless optimisation in review.
 *
 *
 * ⚠️ THE APERTURE IS SMALL AT THE START — SURFACE THE EVIDENCE.
 * With one anchor down, "match against the anchor composite" IS a tile-pair, and at tile-pair
 * aperture the exact-NCC argmax is >20 px wrong 5 % of the time, at scores up to 0.760 (222 vs 250:
 * the 0.760 winner is 757 px wrong; the truth is the runner-up at 0.677). What saves the opening is
 * that CONSECUTIVE snapshots overlap ~78 % and consecutive whole-frame matches are the alias-robust
 * ones. So we show, on EVERY placement: n_anchors, the composite area, the ncc, and the best-vs-
 * second margin — and flag `margin_thin` (< 0.10) LOUDLY.
 *
 * ⚠️ THE ANCHORING HAZARD — the app shows the machine's answer and the user confirms it. That is the
 * right call for a mosaic-building tool, and it is EXACTLY how pass 1's ground truth got tiles
 * 128/129/130/148 wrong. So when a tile is still sitting exactly where the machine put it, the UI
 * SAYS SO ("at the machine's position, untouched"). It does not pretend the human independently
 * agreed.
 *
 *
 * ⭐⭐ THE SOLVER FALLBACK — the user's ruling, 2026-07-12:
 * --------------------------------------------------------
 *     "i still want it to place at where the solver thinks it is but i dont want it to anchor it
 *      without user approval"
 *
 * THE PROBLEM, measured live: early in the sweep — and ESPECIALLY in the *defer* flow, where he
 * Spaces past tiles without anchoring them, so the field stays 1-2 tiles — the anchor composite is a
 * weak tile-pair aperture and the match lies CONFIDENTLY. Reproduced exactly, against the real
 * matcher: with only trial 11 anchored, trial 13 lands **284.8 px** off the (correct) solver answer
 * at margin **0.0129**. Typical margin is 0.39. At a thin aperture the anchor-composite match is
 * WORSE than the batch solve, which scores 312/312.
 *
 * THE RULE (`decidePlacement`):
 *   * `Space` ALWAYS places the tile and ALWAYS fades it in. The rhythm never stalls.
 *   * Match CONFIDENT            -> use it. Today's behaviour, unchanged. The anchor field is
 *                                   human-certified and it has the bigger aperture: it is the answer.
 *   * Match NOT confident, and it DISAGREES with the solver by > 10 px
 *                                -> place at the SOLVER's position, fade it in, and SAY SO, loudly,
 *                                   with the evidence (ncc · margin · aperture · the px gap).
 *   * Match NOT confident but it AGREES with the solver -> no-op: the match stands.
 *   * NO solver position at all  -> use the match anyway and say so. A tile with no position is
 *                                   useless.
 *   * ⛔ NOTHING IS EVER AUTO-ANCHORED. A diverted tile lands `unverified` — dimmer, dashed, and
 *      NOT in the anchor field. Anchoring is, and stays, the user pressing `A`. He can always drag,
 *      `S`-snap or `V` an alternative to overrule it.
 *
 * WHY THESE NUMBERS — 411 real `POST /api/match/anchor` calls, scored against the human GT:
 *   * 311 = the full sweep, 11 -> 347, one tile at a time, with the anchors AT THE GROUND TRUTH
 *     (an ORACLE field — a best case the app never actually has).
 *   * 104 = the DEFER flow: sparse fields of 1-12 anchors with the target 1-3 steps out.
 *   Of the 43 matches that came out > 10 px wrong, the WORST scored **margin 0.1962** and the WORST
 *   scored **ncc 0.6392**. So `margin < 0.20 || ncc < 0.65` catches **43/43**.
 *
 *   🔴 **THE TWO TESTS ARE NOT REDUNDANT. NEITHER MAY BE REMOVED.** This comment used to claim they
 *   were (every one of those 43 tripped both), and that claim was an artefact of the ORACLE field.
 *   Re-measured on the 298 wrong matches the REAL defer flow produces (field `{11}`, self-anchored —
 *   the flow this rule was written for): 286 trip both, **4 trip ONLY margin** (worst: t105, 353 px
 *   wrong at ncc 0.7450 — sails past the NCC gate), **8 trip ONLY ncc** (worst: t182, **2,042 px**
 *   wrong at margin 0.3230 — sails past the margin gate), 0 trip neither. The OR still catches
 *   **298/298**; it does so because it is an OR of two INDEPENDENT signals. Delete `SOLVER_NCC_MIN`
 *   as "dead weight" and trial 182 is judged CONFIDENT and placed 2,042 px from the human with no
 *   banner and no warning.
 *
 *   Neither signal separates on its own (correct matches go down to margin 0.0139 / ncc 0.5282): the
 *   test HAS to be permissive, and what makes permissiveness free is the DISAGREEMENT GATE.
 *   Measured: 51 of the 368 correct matches trip the not-confident test — and **0** of them are
 *   diverted, because every one of them agrees with the solver. The largest gap between a CORRECT
 *   match and the solver is **11.1 px**; the smallest gap at a WRONG one is **15.1 px**.
 *   Consequence on the full 312-tile sweep: **7 tiles diverted, 7 right, 0 wrong** — 304/311 -> 310/311
 *   within 10 px of the human. Re-run on a SELF-anchoring field (the harder, honest test): same
 *   answer — 310/311, 7 diverts, 7 rescues, **0** correct matches thrown away. With the fallback
 *   REMOVED: **162/311** (t119 anchors 798 px wrong and the field cascades). It is load-bearing.
 *   See the report; do not re-tune these from a vibe.
 */
'use strict';

window.Sweep = (function () {

  // ---------------------------------------------------------------------------------------
  // Constants. API.md §1.1 — these MUST NOT diverge from the backend's.
  // ---------------------------------------------------------------------------------------
  const TILE            = 512;
  const FADE_MS         = 1000;    // the placement fade. The fade is the point; do not shorten it.
  const THIN_MARGIN     = 0.10;    // margin < this = the signature of a surviving alias. LOUD.
  const SNAP_RADIUS     = 64;
  /* The re-check's agreement tolerance. Failure on this data is BINARY — a tile is either
   * sub-pixel right or it is hundreds of px wrong — so anything past a few px is a disagreement,
   * not a refinement. (5 px is well inside the 10 px grading bar and well outside the ~1 px the
   * matcher actually resolves.) */
  const RECHECK_TOL_PX  = 5.0;

  /* ⭐ THE SOLVER FALLBACK (his ruling, 2026-07-12 — see the header). "Not confident" is defined
   * from 411 measured matches against the real backend, scored on the human GT. All three numbers
   * are load-bearing; the report has the derivation.
   *
   *   SOLVER_MARGIN_MIN  the worst best-vs-second margin at which a match came out >10 px WRONG was
   *                      **0.1962** (a 822 px error, 2-anchor field). 0.20 sits just above it.
   *   SOLVER_NCC_MIN     the worst NCC at which a match came out >10 px WRONG was **0.6392** (trial
   *                      126, 530 px off, 112 anchors — the failures are NOT only at the opening).
   *                      0.65 sits just above it.
   *                      ⚠️ Neither number separates right from wrong ON ITS OWN — correct matches
   *                      run down to margin 0.0139 and ncc 0.5282. That is WHY both are permissive
   *                      and OR'd.
   *                      🔴 AND THEY ARE **NOT** REDUNDANT — see the header. On the real defer flow,
   *                      12 of 298 wrong matches are caught by EXACTLY ONE of them (t182 is 2,042 px
   *                      wrong at margin 0.3230; t105 is 353 px wrong at ncc 0.7450). Removing either
   *                      test ships a confident, unbannered, 2,000 px error. Remove NEITHER.
   *   SOLVER_DISAGREE_PX the gate that makes permissiveness free, and it does nearly all the work.
   *                      A tile is only diverted if the match also DISAGREES with the solver. Failure
   *                      here is binary — measured, the largest gap between a CORRECT match and the
   *                      solver is 11.12 px and the smallest gap at a WRONG one is 15.1 px.
   *                      ⚠️ 10.0 is BELOW that void, deliberately and asymmetrically: it is the
   *                      project's own grading bar (benchmark/score.py DEFAULT_TOL), and the two
   *                      errors it can make are NOT equal. Diverting a WRONG match is the whole
   *                      point. Diverting a CORRECT one costs only the matcher's sub-pixel refit —
   *                      the divert target is t33's position, which on this dataset is within
   *                      9.94 px of the human on all 312 tiles, so a divert cannot by itself break
   *                      the 10 px bar. (⚠️ that bound is a property of the BUILD, not of this rule:
   *                      regress the 312/312 and it evaporates.) In-sample it never fires anyway —
   *                      0 of 368 correct matches sit >10 px from the solver on the oracle field,
   *                      and the largest such gap on a self-anchoring sweep is 7.14 px. 51 of 368
   *                      correct matches trip the not-confident test; the gate absorbs ALL 51. */
  const SOLVER_MARGIN_MIN  = 0.20;
  const SOLVER_NCC_MIN     = 0.65;
  const SOLVER_DISAGREE_PX = 10.0;

  /* The Difference-mode banner. It only means anything because the tone window is GLOBAL — that is
   * the `?` on the Tone panel's business, not a paragraph over the canvas. */
  const DIFF_MSG = 'Difference: |tile − background|. <b>Misalignment shows as bright doubling.</b>';

  const MAX_CANDIDATES  = 8;
  const UNDO_DEPTH      = 100;
  const FOLD_MS         = 700;     // tagged folding, as in the bench (template.html:1649)
  const AUTOSAVE_MS     = 2000;    // debounce; plus UNCONDITIONALLY on every A and E
  const SCORE_DEBOUNCE  = 150;     // live NCC during a drag
  const POLL_MS         = 500;     // job polling
  const APP_VERSION     = '1.0.0';

  // ---------------------------------------------------------------------------------------
  // State
  // ---------------------------------------------------------------------------------------
  let session   = null;   // GET /api/session
  let doc       = null;   // THE DOCUMENT (project_schema.json). The backend keeps no copy.
  let cursor    = null;   // the trial under judgement
  let gpu       = null;
  let toneVersion = 1;
  /* 🔴 THE PIXEL CACHE-BUSTER. `?v=` used to be `tone.version` alone — and `tone.version` is a
   * fresh-dataclass default, so it RESETS TO 1 on every session open and every run change, while the
   * pixels behind the URL change (a narrower run = a different tone window). The tile PNGs are served
   * `Cache-Control: public, max-age=31536000, immutable`: the browser will not revalidate for a YEAR.
   * Same URL, different bytes. Open a second acquisition directory whose trial numbers overlap and
   * the mosaic would render the FIRST dataset's pixels — and this whole app is "the human looks at
   * the pixels". So the buster now identifies the SESSION as well: `{nonce}.{tone_version}`. */
  let cacheKey  = '1';
  const bustKey = () => (session && session.nonce ? session.nonce : '0') + '.' + toneVersion;

  /* {trial: the last /api/match/anchor response}.
   *
   * 🔴 THIS IS A CACHE KEYED ON THE TRIAL NUMBER — the exact thing the header forbids — and it very
   * nearly sprang the trap it warns about. `showAlternatives()` (`V`) served this list, and clicking
   * a candidate MOVES THE TILE THERE. The candidates are WORLD COORDINATES computed against the
   * anchor field AS IT WAS when the tile was judged. Move an anchor afterwards and every one of them
   * is a lie: measured on a 5-anchor field, after correcting a 400 px mis-anchor, the cached list's
   * rank 0 was a confident **ncc 0.9298 at 399.7 px from the truth**, while an honest recompute put
   * rank 0 **0.9 px** from it. Every candidate in the served list was 186–606 px out.
   *
   * ⇒ SO EVERY ENTRY IS STAMPED WITH THE ANCHOR FIELD IT WAS MEASURED AGAINST (`_field`), and
   *   anything that would ACT on it (`V`) re-fetches unless the field is bit-for-bit the one it
   *   assumed. The server memo makes that re-fetch ~1 ms when nothing has changed, so the check is
   *   free — and when something HAS changed, the memo misses and the server recomputes honestly.
   *   It is the same discipline as the prefetch: never trust a trial number; key on the field. */
  let evidence  = {};
  let lastCandidates = null;   // for `V`
  let diffOn    = false;
  let altsOn    = false;
  let matchSeq  = 0;      // guards against a stale foreground response landing after a newer one
  let inflight  = 0;      // foreground matches in flight (for the busy cursor)
  let buildJobId = null;
  let dragTag   = null;   // the trial whose drag has already pushed an undo entry
  let lastPrefetchKey = null;   // a KEY, never a RESULT. See prefetchNext().
  let seqCounter = 0;     // judgement order, for staleness (API.md §7.5)
  let screen    = 'load';
  let viewerOk  = false;

  const undoStack = [], redoStack = [];
  let lastTag = null, lastPushT = 0;
  let autosaveTimer = null, scoreTimer = null;

  const el = {};

  // ---------------------------------------------------------------------------------------
  // Tiny helpers
  // ---------------------------------------------------------------------------------------
  const API   = () => (window.CAMEA_API || location.origin).replace(/\/$/, '');
  const $     = (id) => document.getElementById(id);
  const iso   = () => new Date().toISOString().replace(/\.\d+Z$/, 'Z');
  const K     = (t) => String(t);
  const fmt   = (v, n) => (v === null || v === undefined || !isFinite(v)) ? '—' : (+v).toFixed(n);

  async function api(path, opts) {
    const r = await fetch(API() + path, Object.assign({
      headers: { 'Content-Type': 'application/json' },
    }, opts || {}));
    let body = null;
    const ct = r.headers.get('content-type') || '';
    if (ct.includes('json')) { try { body = await r.json(); } catch (_) { body = null; } }
    if (!r.ok) {
      const e = new Error((body && body.error && body.error.message) || (r.status + ' ' + path));
      e.status = r.status;
      e.code = body && body.error && body.error.code;
      e.body = body;
      throw e;
    }
    return body;
  }
  const GET  = (p)      => api(p);
  const POST = (p, b)   => api(p, { method: 'POST',  body: JSON.stringify(b || {}) });
  const PUT  = (p, b)   => api(p, { method: 'PUT',   body: JSON.stringify(b || {}) });
  const PATCH= (p, b)   => api(p, { method: 'PATCH', body: JSON.stringify(b || {}) });

  // The visual vocabulary is style.css's (agent 4's). We only set the classes it defines:
  //   .toast.show / .toast.bad   .warn / .warn.loud / .warn.info   .badge.<state>   .chip.on
  let toastTimer = null;
  function toast(msg, kind) {
    if (!el.toast) return;
    el.toast.textContent = msg;
    el.toast.className = 'toast show' + (kind === 'bad' ? ' bad' : '');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { el.toast.className = 'toast'; }, 4200);
  }
  function banner(msg, kind) {
    if (!el.banner) return;
    if (!msg) { el.banner.className = 'warn info hidden'; return; }
    el.banner.innerHTML = '<div>' + msg + '</div>';
    el.banner.className = 'warn ' + (kind === 'warn' ? 'loud' : 'info');
    el.banner.style.margin = '0';
  }

  // =========================================================================================
  // ⭐ HELP — "THE APP IS A TOOL, NOT AN EXPLAINER" (his ruling, 2026-07-14)
  //     "Assume the user knows. If they don't, they have the option to hover."
  // =========================================================================================
  /* Every explanation that used to be a paragraph on the page is the body of a tooltip on a small
   * `?` beside the thing it explains. Nothing was deleted — it moved.
   *
   * 🔴 THE ONE EXCEPTION IS A LIVE WARNING ABOUT THE CURRENT STATE — a stale build, a thin margin,
   *    a diverted tile, a failed autosave, the provenance stamp. Those fire only when something is
   *    actually wrong and they change what he would DO, so they stay on the page in a `.warn`.
   *    BACKGROUND to a warning may go behind a `?` ON the warning. The fact that it is FIRING may
   *    not. Do not "tidy" one of them into a tooltip.
   *
   * ⚠️ ONE delegated listener per event, never a per-node bind: the rails and the blank list are
   *    re-rendered constantly, so any `?` may be destroyed and rebuilt under our feet.
   * ⚠️ #help-tip is body-level and `position: fixed` BY NECESSITY, not by taste: every pane and rail
   *    is `overflow: auto`, and a bubble nested inside one gets CLIPPED at the pane's edge. */
  const Help = (function () {
    const GAP = 8, MARGIN = 8;
    let cur = null;

    const textOf = (n) => (n && n.dataset && n.dataset.help) ? n.dataset.help : '';

    function place(node) {
      const tip = el.helpTip;
      const r = node.getBoundingClientRect();
      const w = tip.offsetWidth, h = tip.offsetHeight;   // measured with the text already in
      const vw = window.innerWidth, vh = window.innerHeight;
      let x = r.right + GAP;
      if (x + w > vw - MARGIN) x = r.left - w - GAP;                 // flip to the left
      x = Math.max(MARGIN, Math.min(x, vw - w - MARGIN));            // and never off the edge
      let y = r.top + r.height / 2 - h / 2;
      y = Math.max(MARGIN, Math.min(y, vh - h - MARGIN));
      tip.style.left = Math.round(x) + 'px';
      tip.style.top  = Math.round(y) + 'px';
    }

    function show(node) {
      if (!el.helpTip || !node) return;
      const txt = textOf(node);
      if (!txt) { hide(); return; }        // a `?` never promises an explanation it cannot give
      cur = node;
      // textContent, not innerHTML: the body of a tooltip can be a backend `why` string, and
      // style.css sets `white-space: pre-wrap`, so a `\n` in data-help IS a line break.
      el.helpTip.textContent = txt;
      el.helpTip.classList.add('show');
      place(node);
    }
    function hide() {
      if (el.helpTip) el.helpTip.classList.remove('show');
      cur = null;
    }

    const target = (e) => (e.target && e.target.closest) ? e.target.closest('[data-help]') : null;

    function init() {
      document.addEventListener('mouseover', (e) => {
        const n = target(e);
        if (n === cur) return;
        if (n) show(n); else if (cur) hide();
      });
      document.addEventListener('focusin', (e) => { const n = target(e); if (n) show(n); else hide(); });
      document.addEventListener('focusout', hide);
      document.addEventListener('keydown', (e) => { if (e.key === 'Escape') hide(); });
      // CAPTURE. A `?` inside an `overflow: auto` pane scrolls away from a FIXED bubble, and a
      // scroll inside a pane does not bubble to window.
      window.addEventListener('scroll', hide, true);
      window.addEventListener('resize', hide);
      reindex();
    }

    /** Keyboard-reachable, set from JS so the HTML stays clean. Idempotent. */
    function reindex(root) {
      (root || document).querySelectorAll('.help').forEach((n) => {
        if (!n.hasAttribute('tabindex')) n.setAttribute('tabindex', '0');
      });
    }

    /** Fill a `?` from a string the BACKEND measured. Empty = the `?` hides itself (style.css). */
    function set(node, txt) {
      if (!node) return;
      node.dataset.help = txt || '';
      if (node === cur) hide();
    }

    return { init, show, hide, reindex, set };
  })();

  // =========================================================================================
  // THE DOCUMENT
  // =========================================================================================

  /** A fresh document for the open session.
   *
   *  ⛔ EVERY TRIAL STARTS `unplaced`. THE APP EXCLUDES NOTHING (his ruling, 2026-07-14: "the app
   *     itself shouldn't store the exclusions for this experiment"). There is no built-in exclusion
   *     list, no dataset detection, no auto-exclude — not from the blank scan either, which only
   *     RECOMMENDS (API.md §9). The only things that ever exclude a frame are the human, in this
   *     session, and a project file he loaded. The project file is the app's entire memory. */
  function newDoc() {
    const blanks = new Set((session.blank && session.blank.blank) || []);
    const tiles = {};
    for (const t of session.run.trials) {
      tiles[K(t)] = {
        status: 'unplaced', state: 'unplaced', x: null, y: null,
        r: 96,
        pass: (session.pass_split && t <= session.pass_split.value) ? 1 : 2,
        // ⚠️ A MEASUREMENT about the pixels, not a judgement and not an exclusion. It is what the
        // matcher refuses to score (API.md §7.3); it excludes nothing and it never will.
        blank: blanks.has(t),
        machine: null,
      };
    }
    return {
      schema_version: 'camea-project-1.0',
      app: { name: 'Camea Mosaic Builder', version: APP_VERSION },
      dataset: session.dataset,
      /* THE ACQUISITION'S OWN NAME — `log.txt`'s `New experiment:` line. `dataset` is the FOLDER
       * NAME, a label a human typed, and a restored backup or a junction makes it lie. Both are
       * recorded so the file says which acquisition it describes; NEITHER decides anything. */
      experiment: session.experiment || session.dataset,
      data_dir: session.data_dir,
      tile_px: TILE,
      created: iso(),
      modified: iso(),
      trial_range: [session.run.lo, session.run.hi],
      pass_split: session.pass_split ? session.pass_split.value : null,
      gaps: (session.gaps || []).map((g) => g.slice()),
      // ⚠️ FROM THE SESSION, WHICH DERIVED IT FROM THIS ACQUISITION'S XML — never hard-coded. The
      // reader flips CONDITIONALLY (ax=-1/ay=-1); a hard-coded "180deg-flipped" note would be a
      // false claim about the coordinate frame on any acquisition that declares no flip. (All 342
      // XMLs of 260620d do declare it, so today the two strings are identical.)
      coordinates: session.coordinates ||
                   ('RELATIVE. Tile TOP-LEFT in px, measured FROM origin_trial at (0,0), in the ' +
                    'vscope-displayed (180deg-flipped) frame.'),
      origin_trial: null,
      tolerance_px: { anchor: 96, region_default: 256, grading: 10 },
      /* ⛔ THE ONLY EXCLUSION LIST THAT EXISTS. It starts EMPTY and it only ever grows from what the
       * HUMAN does — `E` in the sweep, or a tick on the Screen page. `exportDoc()` rebuilds it from
       * live tile state on every save. There is no other exclusion list anywhere in this app: no
       * built-in ruling, no dataset detection, nothing seeded at load. (His ruling, 2026-07-14.) */
      unusable_tiles: [],
      run: {
        detected: !!session.run.detected,
        why: session.run.why,
        pass_split_detected: !!(session.pass_split && session.pass_split.detected),
        pass_split_why: session.pass_split && session.pass_split.why,
        n_trials: session.run.n,
      },
      cursor: null,
      tone: session.tone || null,
      blank_scan: session.blank ? {
        threshold: session.blank.threshold,
        measure: session.blank.measure,
        // `scanned` = what the MEASURE said (it never changes). `blank` = what the MATCHER refuses
        // (the human may overrule it, per frame). `overruled_by_user` = the record of that act.
        scanned: (session.blank.scanned || session.blank.blank || []).slice(),
        blank: (session.blank.blank || []).slice(),
        overruled_by_user: [],
        accepted: false,
      } : undefined,
      build: null,
      provenance: {
        authored_by: 'Camea Mosaic Builder',
        app_version: APP_VERSION,
        workflow: 'hand placement from scratch',
        seeded_from: null,
        independent_of_method: true,
      },
      audits: [],
      tiles,
    };
  }

  const tileOf   = (t) => doc.tiles[K(t)];
  const trials   = () => (session ? session.run.trials : []);
  const anchored = () => trials().filter((t) => tileOf(t) && tileOf(t).state === 'anchored');
  const counts   = () => {
    const c = { anchored: 0, unverified: 0, unplaced: 0, excluded: 0, diverted: 0 };
    for (const t of trials()) {
      const tl = tileOf(t);
      if (tl.state in c) c[tl.state]++;
      /* ⭐ `diverted` is NOT a state — it is a fact ABOUT an unverified tile: it is sitting on the
       * SOLVER's answer because the matcher was not trustworthy there. It has to be countable, or
       * the defer flow (where it can be 302 of 311 tiles) shows the user nothing at all.
       * ⚠️ ONLY the still-`unverified` ones: an ANCHORED tile keeps its `diverted` record on purpose
       * (that is its provenance, and the QC export counts it), but the human has since approved it —
       * it is not outstanding work and it must not nag from the header. */
      if (tl.diverted && tl.state === 'unverified' && tl.x !== null) c.diverted++;
    }
    return c;
  };
  // ⚠️ Guarded: the step-lock (`READY.sweep`) asks this before a document necessarily exists.
  const anyPlaced = () => !!doc && trials().some((t) => tileOf(t) && tileOf(t).x !== null);

  /** The anchor field a match against `target` would actually see — the anchored set MINUS the
   *  target (a tile is never an anchor for its own match; see `matchAnchor`), with its positions.
   *  This string IS the memo key's payload in spirit, and it is what every cached `evidence` entry
   *  is stamped with. Two calls agree ⟺ the server would return the same answer. */
  function fieldSig(target) {
    // Hashed, not stored raw: at 312 anchors the literal string is ~6 kB, and it is snapshotted
    // into all 100 undo entries. djb2 over the same payload the server's memo key is built from.
    let h = 5381;
    const anc = anchored();
    for (let i = 0; i < anc.length; i++) {
      const t = anc[i];
      if (t === target) continue;
      const tl = tileOf(t);
      const s = t + ':' + (+tl.x).toFixed(3) + ',' + (+tl.y).toFixed(3) + '|';
      for (let k = 0; k < s.length; k++) h = (((h << 5) + h) ^ s.charCodeAt(k)) >>> 0;
    }
    return h.toString(16) + '.' + anc.length;
  }
  /** Is this tile's recorded evidence still evidence *about the field the app now has*? */
  function evidenceIsCurrent(t) {
    const res = evidence[K(t)];
    return !!(res && res._field !== undefined && res._field === fieldSig(t));
  }

  /** ⭐ The state machine (API.md §2.1). THE ONLY PLACE A TILE'S STATE IS EVER WRITTEN. */
  function setState(t, state, x, y) {
    const tile = tileOf(t);
    const STATUS = { anchored: 'anchor', unverified: 'unverified', unplaced: 'unplaced', excluded: 'excluded' };
    tile.state  = state;
    tile.status = STATUS[state];
    /* 🔴 A TILE THAT LEAVES `excluded` MUST STOP CLAIMING IT WAS THROWN OUT. `setState` wrote
     * `state`/`status`/`x`/`y` and left `excluded`/`excluded_reason`/`unusable_reason` behind, so
     * `E` then `A` on the same tile produced a record reading
     *     status: "anchor"   excluded: true   excluded_reason: "the user's eye"
     * — and `score.load_gt` keeps every `status == "anchor"`, so that self-contradicting tile went
     * into the exported GROUND TRUTH still asserting it was unusable. (`exportDoc` rebuilds the
     * top-level `unusable_tiles`/`gaps` from live state, so only the tile record was wrong — which
     * is the copy a reader actually believes.) The claim is a judgement; it dies with the judgement.
     * ⚠️ `blank` is NOT cleared: that is a MEASUREMENT about the pixels, not a judgement. */
    if (state !== 'excluded') {
      delete tile.excluded;
      delete tile.excluded_reason;
      delete tile.unusable_reason;
      delete tile.last_xy;
    }
    if (state === 'excluded' || state === 'unplaced') { tile.x = null; tile.y = null; }
    else { tile.x = +x; tile.y = +y; }
    if (state === 'anchored' || state === 'unverified') tile.seq = ++seqCounter;
    delete tile.recheck_px;          // a re-check measures where it WAS; it has just been re-placed
    // Keep the QC number honest wherever the position was written from: `machine` is what t33 said,
    // `moved_px` is how far the human-certified answer ended up from it. The QC report and the
    // provenance's human_edits block are both built on this.
    if (tile.machine && tile.x !== null) {
      tile.moved_px = Math.hypot(tile.x - tile.machine[0], tile.y - tile.machine[1]);
    }
    doc.modified = iso();
    if (viewerOk) Viewer.setTile(t, tile);
  }
  function setPos(t, x, y) {
    const tile = tileOf(t);
    tile.x = +x; tile.y = +y;
    delete tile.recheck_px;
    /* 🔴 A HAND (a drag, `S`, an arrow nudge, a `V` alternative) HAS TAKEN THE TILE OVER. It is no
     * longer sitting on the solver's answer because the app overruled the matcher, so the divert
     * claim is dead — and it must die HERE, at the single place a position is rewritten. Leave it and
     * the rail keeps shouting "THIS IS THE SOLVER'S POSITION" over a tile the user has just dragged
     * somewhere else, `rejected_match` keeps quoting a px-gap to a position it no longer has, and
     * the exported QC counts a human correction as a machine diversion. */
    delete tile.diverted;
    delete tile.divert_reason;
    delete tile.rejected_match;
    if (tile.machine) {
      const dx = tile.x - tile.machine[0], dy = tile.y - tile.machine[1];
      tile.moved_px = Math.hypot(dx, dy);
    }
    doc.modified = iso();
    if (viewerOk) Viewer.setTile(t, tile);
  }

  /** ⚠️ Any change to the excluded set MUST recompute the acquisition gaps, or the serpentine
   *  one-step prior gets applied across a multi-step jump and the next solve is silently poisoned
   *  (283->297, 298->311 on this data). This mirrors `excluded.gaps()`: consecutive pairs in the
   *  *surviving* trial list that are not one acquisition step apart. */
  function recomputeGaps() {
    const live = trials().filter((t) => tileOf(t).state !== 'excluded');
    const g = [];
    for (let i = 1; i < live.length; i++) if (live[i] - live[i - 1] !== 1) g.push([live[i - 1], live[i]]);
    doc.gaps = g;
    return g;
  }

  /** The next non-excluded trial after `t`. No wrapping — at the end, the sweep is done. */
  function nextTrial(t) {
    const ts = trials();
    let i = t === null ? -1 : ts.indexOf(t);
    for (let j = i + 1; j < ts.length; j++) if (tileOf(ts[j]).state !== 'excluded') return ts[j];
    return null;
  }
  function prevTrial(t) {
    const ts = trials();
    let i = t === null ? ts.length : ts.indexOf(t);
    for (let j = i - 1; j >= 0; j--) if (tileOf(ts[j]).state !== 'excluded') return ts[j];
    return null;
  }

  // =========================================================================================
  // ⭐⭐ The anchor-composite primitive — ONE call, FOUR features (API.md §7)
  // =========================================================================================

  /** POST /api/match/anchor. THE call: place-next · alternatives · rescue · snap.
   *  `anchors` is ALWAYS the current `anchored` set — never `unverified`. That is the whole point
   *  of the unverified state: a tile the human has not certified does not get a vote.
   *  The endpoint is a pure function of this body (API.md §0), which is what makes the prefetch
   *  correct by construction. */
  async function matchAnchor(target, mode, near, opts) {
    /* ⚠️ A TILE IS NEVER AN ANCHOR FOR ITS OWN MATCH. `anchored()` is the whole certified field, and
     * once the user has pressed A on this tile it is IN that field — so snapping or re-matching an
     * ALREADY-ANCHORED tile shipped the target inside its own `anchors` list and the server
     * (correctly) answered 400. The drag then stuck and the snap silently did nothing: the tile was
     * left exactly where the hand dropped it, un-snapped, still flagged as certified ground truth.
     * Correcting an anchor is an EXPECTED flow — API.md §2 is explicit that a drag never demotes an
     * anchor, because the user is the authority — so this must work, and it must work here rather
     * than at each of the four call sites. Filtering the target out also leaves the prefetch's
     * A-branch untouched (there the target is the NEXT tile, never the one being certified), so the
     * memo key still matches by construction. */
    const anc = ((opts && opts.anchors) || anchored()).filter((t) => t !== target);
    if (!anc.length) return { target, candidates: [], best: null, margin: null, n_anchors: 0,
                              refused: { reason: 'no_anchors', trials: [],
                                         message: 'No anchors yet. Press A on this tile to make it the origin.' } };
    const positions = {};
    for (const t of anc) { const tl = tileOf(t); positions[K(t)] = [tl.x, tl.y]; }
    return POST('/api/match/anchor', {
      target, anchors: anc, positions,
      mode: mode || 'global',
      near: near || null,
      radius: SNAP_RADIUS,
      max_candidates: MAX_CANDIDATES,
    });
  }

  /** 🔴 THE PREFETCH. Fire the match for the tile AFTER `judged`, ASSUMING THE USER WILL PRESS `A`
   *  — i.e. with `judged` INCLUDED in `anchors`, at its current position. Exact by construction.
   *
   *  FIRE AND FORGET. We deliberately DISCARD the answer: the server memoises on the anchor set, so
   *  the foreground `advance()` re-POSTs and gets a ~1 ms hit *iff* it means the same anchor set.
   *  Press `E`, or defer with `Space`, and the anchor set differs -> the key differs -> the memo
   *  misses -> the server recomputes honestly. There is nothing here to throw away, because there is
   *  nothing here. DO NOT "optimise" this into a client-side cache. */
  function prefetchNext(judged) {
    if (!session || buildJobId) return;
    const nxt = nextTrial(judged);
    if (nxt === null) return;
    const jt = judged === null ? null : tileOf(judged);
    // NB `lastPrefetchKey` below stores a KEY and never a RESULT. It exists only to stop us firing
    // the byte-identical POST twice (we prefetch once when the tile is DISPLAYED and again when it
    // is JUDGED, and those are usually the same anchor set). It cannot serve a stale answer, because
    // it has no answer to serve. Do not "upgrade" it into a result cache. See the header.

    // The A-branch: assume `judged` is about to become an anchor at exactly where it sits now.
    // (If it has no position, or the user already excluded it, it cannot be in the field — then the
    //  honest anchor set is just the anchored set, and that is what we warm.)
    let anc = anchored();
    if (jt && jt.state !== 'excluded' && jt.x !== null && !anc.includes(judged)) anc = anc.concat([judged]);
    if (!anc.length) return;

    // If the next tile is already placed AND certified, there is nothing to place. Still worth
    // warming nothing — bail.
    if (tileOf(nxt).state === 'anchored') return;

    const positions = {};
    for (const t of anc) { const tl = tileOf(t); positions[K(t)] = [tl.x, tl.y]; }

    const key = nxt + '|' + anc.map((t) => t + ':' + tileOf(t).x.toFixed(3) + ',' + tileOf(t).y.toFixed(3)).join('|');
    if (key === lastPrefetchKey) return;      // the identical POST is already in flight / answered
    lastPrefetchKey = key;

    POST('/api/match/anchor', {
      target: nxt, anchors: anc, positions,
      mode: 'global', near: null, radius: SNAP_RADIUS, max_candidates: MAX_CANDIDATES,
    }).then(() => { /* the ANSWER IS DISCARDED on purpose — see the header */ })
      .catch(() => { /* a prefetch failure is never user-visible; the foreground call will speak */ });
  }

  /** POST /api/match/score — "you dropped it HERE; here's what the pixels say." Debounced, live
   *  during a drag. `ncc: null` means NOT MEASURABLE (too little overlap) — show "—", never 0.0. */
  async function scoreAt(trial, x, y) {
    const anc = anchored().filter((t) => t !== trial);
    if (!anc.length) return null;
    const positions = {};
    for (const t of anc) { const tl = tileOf(t); positions[K(t)] = [tl.x, tl.y]; }
    return POST('/api/match/score', { target: trial, anchors: anc, positions, at: [x, y] });
  }

  // =========================================================================================
  // ⭐⭐ THE SOLVER FALLBACK — his ruling, 2026-07-12. See the file header for the measurements.
  //     "i still want it to place at where the solver thinks it is but i dont want it to anchor it
  //      without user approval"
  // =========================================================================================

  /** The batch solve's answer for this tile, in the DOCUMENT's frame, or null.
   *  `machine` is written by `loadBuildResult()` and is already translated onto the human's field,
   *  so it is directly comparable with `tile.x/y`. Null when no build has run, or when the solver
   *  failed to place this tile. */
  function solverXY(t) {
    const tl = tileOf(t);
    return (tl && Array.isArray(tl.machine) && tl.machine.length === 2 &&
            isFinite(tl.machine[0]) && isFinite(tl.machine[1])) ? [+tl.machine[0], +tl.machine[1]] : null;
  }

  /** Is the anchor-composite match good enough to be allowed to OVERRULE the batch solve?
   *  Permissive on purpose (see the constants): neither signal separates alone, so both are OR'd and
   *  the disagreement gate in `decidePlacement` is what stops a permissive test from costing
   *  anything. Returns the REASONS too — the user is shown exactly why, never just a verdict. */
  function matchConfidence(res) {
    const why = [];
    if (!res || !res.best) {
      why.push(res && res.refused
        ? 'matcher refused (' + (res.refused.reason || 'refused') + ')'
        : 'no candidate at all');
      return { confident: false, none: true, why };
    }
    const m = (res.margin === undefined) ? null : res.margin;
    // ⚠️ The NUMBERS stay — this string is also written to `tile.divert_reason` and shipped in the
    // QC report, and "not confident" without the measurement is an assertion, not evidence.
    if (m !== null && m < SOLVER_MARGIN_MIN) {
      why.push('margin <b>' + fmt(m, 4) + '</b> &lt; ' + SOLVER_MARGIN_MIN.toFixed(2));
    }
    if (isFinite(res.best.ncc) && res.best.ncc < SOLVER_NCC_MIN) {
      why.push('NCC <b>' + fmt(res.best.ncc, 4) + '</b> &lt; ' + SOLVER_NCC_MIN.toFixed(2));
    }
    return { confident: why.length === 0, none: false, why };
  }

  /** ⭐ WHERE DOES THE TILE GO? The one place that answers it.
   *
   *  {xy, diverted, conf, sv, d, noSolver} — `xy` is where the tile is about to be placed, and
   *  `diverted` says it is the SOLVER's position rather than the matcher's.
   *
   *  ⛔ This decides a POSITION. It never decides a STATE. Everything it places lands `unverified`
   *     — dimmer, dashed, outside the anchor field, with no vote. Only `A` anchors, and only the
   *     user presses `A`. (He explicitly rejected gating `A` behind an extra click: it fights the
   *     A/E/Space rhythm.) */
  function decidePlacement(t, res) {
    const conf = matchConfidence(res);
    const sv   = solverXY(t);
    const best = (res && res.best) ? [res.best.x, res.best.y] : null;
    const d    = (best && sv) ? Math.hypot(best[0] - sv[0], best[1] - sv[1]) : null;

    // CONFIDENT -> the match wins. This is the whole design: the anchor field is human-certified and
    // it is a big aperture, and a big trusted reference does not lie the way a tile-pair does. The
    // sweep gets MORE accurate as it goes, and this branch is what makes that true.
    if (conf.confident) return { xy: best, diverted: false, conf, sv, d };

    // NOT confident, and there is nothing to fall back to. Use the match and SAY SO — a tile with no
    // position at all is useless, and the human can see a bad one and drag it.
    if (!sv) return { xy: best, diverted: false, noSolver: true, conf, sv: null, d: null };

    // NOT confident and there is NO match at all (blank refusal / empty candidate list). The solver's
    // answer is the only position there is.
    if (conf.none) return { xy: sv, diverted: true, conf, sv, d: null };

    // NOT confident, but the matcher and the solver AGREE. Nothing to divert away from — the match
    // stands. Measured: this is 51 of the 368 correct matches, and diverting them would be a no-op
    // anyway. Leaving the match in place keeps `tiles[*].ncc` honest and keeps the sub-pixel refit.
    if (d !== null && d <= SOLVER_DISAGREE_PX) return { xy: best, diverted: false, conf, sv, d };

    // NOT confident AND it disagrees with the solver by more than the grading bar. One of the two is
    // catastrophically wrong, and at a thin aperture it is overwhelmingly the matcher. DIVERT.
    return { xy: sv, diverted: true, conf, sv, d };
  }

  /** Record the evidence for a placement that may have been DIVERTED.
   *
   *  🔴 `tiles[*].ncc` is defined by the schema as the NCC **at the tile's final position**. On a
   *     divert the tile is NOT at `res.best`, so writing `res.best.ncc` onto it would attribute the
   *     REJECTED alias's score to the position we actually shipped — the identical bug `pickAlternative`
   *     was fixed for (rank 0's NCC at rank 1's position). So we throw that number away and MEASURE
   *     the tile where it really is, with one `POST /api/match/score` (~31 ms, and only on the handful
   *     of tiles that divert). The rejected match is kept, in full, under `rejected_match` — it is the
   *     evidence FOR the divert and the QC report needs it. */
  async function recordPlacement(t, res, dec) {
    stashEvidence(t, res);
    const tile = tileOf(t);
    tile.n_anchors = (res && res.n_anchors !== undefined) ? res.n_anchors : anchored().length;
    tile.margin    = (!res || res.margin === undefined) ? null : res.margin;
    delete tile.alt_rank;

    if (!dec.diverted) {
      tile.ncc  = res && res.best ? res.best.ncc  : null;
      tile.npix = res && res.best ? res.best.npix : null;
      delete tile.diverted;
      delete tile.divert_reason;
      delete tile.rejected_match;
      // the canvas outline follows the flag (see below). Cheap and idempotent.
      if (viewerOk) Viewer.setDiverted(t, false);
      showEvidence(t);
      return;
    }

    tile.diverted      = true;
    /* ⭐ AND SAY SO ON THE MOSAIC. `setState` (which ran a beat ago, in the caller) synced the tile
     * to the viewer BEFORE this flag existed, so without this the diverted tile is drawn exactly
     * like a confidently-matched one — and in the DEFER flow that is 302 of 311 tiles sitting on the
     * solver's answer with nothing on the canvas to say so. The rail block, the banner and the QC
     * export all told the truth; the pixels did not. Magenta outline (--c-diverted). */
    if (viewerOk) Viewer.setDiverted(t, true);
    tile.divert_reason = dec.conf.why.map((s) => s.replace(/<[^>]+>/g, '')).join('; ');
    tile.rejected_match = (res && res.best) ? {
      x: res.best.x, y: res.best.y, ncc: res.best.ncc,
      margin: (res.margin === undefined) ? null : res.margin,
      px_from_solver: dec.d,
    } : null;
    tile.ncc = null; tile.npix = null;
    showEvidence(t);                              // paint immediately; the honest NCC lands in ~31 ms
    let s = null;
    try { s = await scoreAt(t, dec.xy[0], dec.xy[1]); } catch (e) { s = null; }
    // ⚠️ `ncc: null` from /api/match/score means NOT MEASURABLE (too little overlap, or the tile is
    // blank and the scorer refuses). That is the honest answer and it must stay null — never 0.0.
    if (s && s.ncc !== null && s.ncc !== undefined && isFinite(s.ncc)) {
      tile.ncc = s.ncc; tile.npix = s.npix;
    }
    /* 🔴 REPAINT ON THE TILE, NOT ON THE CURSOR. This used to be `if (cursor === t)` — and in
     * `_advance` the cursor is deliberately NOT committed until the answer is in hand, so at this
     * moment `cursor` is still the PREVIOUS tile and the guard was always false. Result: the honest
     * NCC (measured where the tile really sits) reached the document but NEVER reached the rail, which
     * sat on `—` for every diverted tile. Driven: trial 13 diverted, `tiles["13"].ncc = 0.7435`,
     * `#ev-ncc` = "—". The rail is the whole point of the divert — it is where he sees that the
     * position he is being shown scores BETTER than the one that was rejected.
     * The stash check is the re-entrancy guard: if a newer match has already restashed this tile's
     * evidence, that call owns the rail, not this one. */
    if (evidence[K(t)] === res) showEvidence(t);
  }

  /** Say — plainly, loudly — WHICH position is on the screen and WHY. Returns {msg, kind} or null,
   *  rather than bannering directly, because `A`'s tail (`afterJudge`) owns the banner and would
   *  otherwise wipe it. */
  function placementMessage(t, dec) {
    if (dec.noSolver && !dec.conf.confident) {
      return { kind: 'warn', msg:
        '<b>Trial ' + t + ': match not confident</b> (' + dec.conf.why.join(', ') + ') and there is ' +
        'no solver position to fall back on. Check it (<kbd class="kbd">D</kbd>) before ' +
        '<kbd class="kbd">A</kbd>.' };
    }
    if (!dec.diverted) return null;              // the confident path banners elsewhere

    return { kind: 'warn', msg:
      '<b>Trial ' + t + ' — diverted to the solver.</b> ' +
      (dec.conf.none
        ? 'The matcher gave nothing (' + dec.conf.why.join(', ') + ').'
        : 'Match not confident (' + dec.conf.why.join(', ') + '), ' + fmt(dec.d, 0) +
          ' px from the solver.') +
      ' Unverified. <kbd class="kbd">D</kbd> to check, <kbd class="kbd">A</kbd> to accept, ' +
      '<kbd class="kbd">V</kbd> for the matcher\'s answer, or drag it.' };
  }

  /** The Space path: banner it now. (`A` routes the same message through `afterJudge`.) */
  function announcePlacement(t, res, dec) {
    const m = placementMessage(t, dec);
    if (m) banner(m.msg, m.kind);
  }

  // =========================================================================================
  // A / E / Space — the rhythm
  // =========================================================================================

  /** `A` — anchor the cursor tile. It joins the anchor field: everything after it is judged
   *  against it. If it has no position yet, match it first and take candidates[0]. If NO tile
   *  anywhere has a position, this tile IS the origin: [0, 0]. */
  async function anchor() {
    if (busyPlacing('anchor')) return;
    const t = cursor;
    if (t === null || !tileOf(t)) return;
    const tile = tileOf(t);
    let msg = null;                 // `afterJudge` owns the banner; a divert notice rides through it
    let refusedNote = null;         // a blank tile anchored at the solver's answer must still shout

    if (tile.x === null) {
      if (!anyPlaced()) {
        pushUndo('anchor:' + t);
        setState(t, 'anchored', 0, 0);
        tile.source = 'origin tile';
        tile.judged_at = iso();
        doc.origin_trial = t;
        // Every OTHER placement path fades. Watching the tile materialise is the whole point, and
        // the origin landing on an empty canvas is the one the user has least reason to expect.
        if (viewerOk) Viewer.fadeIn(t, 0, 0);
        afterJudge(t, 'Origin — trial ' + t + ' is (0, 0).');
        return;
      }
      /* ⭐ `A` on a tile that has NO POSITION YET has to place it before it can certify it — and the
       * same hazard applies: at a thin aperture the match lies confidently. So it goes through
       * `decidePlacement` too, and if the matcher is not trustworthy the tile is anchored where the
       * SOLVER put it, not on an alias. This is NOT auto-anchoring: the user pressed `A`. It only
       * changes WHICH position the `A` he pressed certifies — from the matcher's (measured: up to
       * 2,969 px wrong) to the solver's (312/312). It is announced, loudly, either way. */
      const res = await foregroundMatch(t, 'global', null);
      const dec = decidePlacement(t, res);
      if (!dec.xy) {
        toast('Trial ' + t + ': no match, no solver answer. Drag it into place, then A.', 'bad');
        return;
      }
      pushUndo('anchor:' + t);
      setState(t, 'anchored', dec.xy[0], dec.xy[1]);
      tile.source = dec.diverted
        ? "anchored at the SOLVER's position (the anchor-composite match was not confident) — A"
        : 'placed against the anchor composite (A)';
      await recordPlacement(t, res, dec);
      msg = placementMessage(t, dec);
      if (dec.diverted && res && res.refused && res.refused.reason !== 'no_anchors') {
        refusedNote = res.refused;
      }
      if (viewerOk) Viewer.fadeIn(t, dec.xy[0], dec.xy[1]);     // a placement always fades
    } else {
      pushUndo('anchor:' + t);
      setState(t, 'anchored', tile.x, tile.y);
      if (!tile.source) tile.source = 'accepted at its current position (A)';
    }
    tile.judged_at = iso();
    tile.stale = false;
    if (doc.origin_trial === null) doc.origin_trial = t;
    afterJudge(t, msg && msg.msg, msg && msg.kind);
    // `afterJudge` -> `refresh()` -> `showEvidence()` hides the refusal panel. A BLANK tile anchored
    // at the solver's answer still has to SHOUT that it is blank, so re-assert it last.
    if (refusedNote) showRefusal(t, refusedNote);
  }

  /** `E` — exclude the cursor tile. Not drawn, not matched, not rendered, not exported.
   *  The old position goes to `last_xy` so undo (and the un-exclude affordance) restores it.
   *  ⚠️ EXCLUDING A TILE OPENS AN ACQUISITION GAP — recompute them, and say so.
   *  🔴 And the prefetch assumed `A`: it is invalid. We do not have one to throw away (there is no
   *     client cache) — we simply re-warm the honest anchor set. */
  async function exclude() {
    if (busyPlacing('exclude')) return;
    const t = cursor;
    if (t === null || !tileOf(t)) return;
    const tile = tileOf(t);
    pushUndo('exclude:' + t);
    const wasAnchored = tile.state === 'anchored';
    const oldSeq = tile.seq;
    if (tile.x !== null) tile.last_xy = [tile.x, tile.y];
    setState(t, 'excluded');
    tile.excluded = true;
    // Two channels, two kinds of claim: `blank` is MEASURED, everything else is the user's eye.
    // We never *assert* blur from a metric — no metric reproduces that call.
    tile.unusable_reason = tile.blank ? 'blank' : 'other';
    tile.excluded_reason = tile.blank
      ? 'measured blank (band-passed std below threshold) — and the user excluded it'
      : "the user's eye";
    tile.judged_at = iso();

    /* 🔴 EXCLUDING AN ANCHOR IS A BIGGER CHANGE TO THE FIELD THAN MOVING ONE, AND IT MARKED NOTHING.
     * `move()` on an anchor marks every later tile stale — "matched against a field that no longer
     * exists". `E` on that same anchor removes its pixels from the composite ENTIRELY, which is a
     * strictly larger change, and it used to mark nothing at all. So: anchor 55, sweep 56-60 (each
     * matched against a composite CONTAINING 55), then go back and press `E` on 55 because it is
     * blurry — and 56-60 kept `stale: false`, kept positions derived from a frame the user had just
     * declared NOT DATA, and exported an `ncc`/`n_anchors` measured against it. Same for un-excluding
     * (undo), which puts the pixels back. */
    const nStale = (wasAnchored && oldSeq !== undefined) ? markStaleAfter(oldSeq, t, false) : 0;

    const g = recomputeGaps();
    doc.unusable_tiles = trials().filter((x) => tileOf(x).state === 'excluded');
    afterJudge(t, 'Excluded ' + t + '. ' +
      (g.length ? g.length + ' gap' + (g.length === 1 ? '' : 's') + ': ' +
        g.map((p) => p[0] + '→' + p[1]).join(', ') + '.' : 'No gaps.') +
      // ⚠️ A LIVE WARNING, not an explanation: its pixels have LEFT the composite that N tiles were
      // matched against. It changes what he does next (re-check them), so it stays on the page.
      (nStale ? ' <b>' + t + ' was an anchor</b> — ' + nStale + ' tile' +
                (nStale === 1 ? '' : 's') + ' flagged stale.' : ''),
      nStale ? 'warn' : 'ok');
  }

  /** Shared tail of A and E: autosave unconditionally, refresh, prefetch the NEXT tile's match. */
  function afterJudge(t, msg, kind) {
    if (msg) banner(msg, kind || 'ok'); else banner(null);
    refresh();
    autosaveNow();
    prefetchNext(t);   // 🔴 A-branch: `t` is (or was) the tile under judgement.
  }

  /** 🔴 THE JUDGEMENT KEYS ARE DEAD WHILE A PLACEMENT IS IN FLIGHT — and that is the fix, not a
   *  limitation. `_advance()` awaits a match that costs 0.4-1.1 s on a memo miss, and it used to
   *  move `cursor` to the NEXT tile *before* that await. So for up to a second:
   *    * the canvas still showed the PREVIOUS tile as the cursor, while `A`/`E`/`S`/`V` acted on a
   *      tile the user could not see; and
   *    * when the response landed, `setState(nxt, 'unverified', ...)` fired from a stale closure with
   *      no re-check and **silently overwrote the judgement the user had just made**. Driven, real
   *      HTTP: `Space` then `E` at +120 ms -> the tile came back `unverified`, on the canvas, still
   *      carrying `excluded: true`. `Space` then `A` -> the tile came back `unverified`, the anchor
   *      counter fell back, and the tile the user had CERTIFIED was dropped from the exported GT
   *      (`score.load_gt` keeps only `status == "anchor"`) and from the field every later match is
   *      measured against.
   *  Two changes kill it: `cursor` no longer moves until the answer is in hand (below), and a
   *  judgement offered mid-flight is REFUSED OUT LOUD rather than applied to the wrong tile. With
   *  the A-branch prefetch warm the foreground match is a ~1 ms memo hit, so this window is normally
   *  invisible; it only opens when the memo genuinely misses — which is exactly when it is unsafe. */
  function busyPlacing(what) {
    if (!advancing) return false;
    toast('Still placing — ' + what + ' ignored.', 'bad');
    return true;
  }

  /** `Space` — ADVANCE.
   *   * If the CURRENT tile is `unplaced`, place it first and mark it `unverified`
   *     (so a hard tile can be deferred without stalling the sweep, and without vanishing).
   *   * It does NOT otherwise change the current tile's state. Space without a decision leaves it
   *     `unverified`: placed, dimmer, NOT in the anchor field, NOT blocking.
   *   * Then place the NEXT tile against the anchor composite and FADE IT IN over a full second.
   *   * Then, the moment it is DISPLAYED, prefetch the one after — assuming `A` on it.
   */
  /** 🔴 RE-ENTRANCY. A second `Space` inside the ~1 s match used to start a second `advance()`. The
   *  `matchSeq` guard made the LOSING call's match return null — but the loser still ran its tail
   *  (`setCursorUI` + `Viewer.fadeIn` on the older tile), yanking the viewer's cursor backwards and
   *  re-fading a tile the sweep had already moved past; and the tile the loser dropped was silently
   *  NOT re-placed against the anchor field even though the user believed it had been. One flag. */
  let advancing = false;

  async function advance() {
    if (!session || cursor === null) return;
    if (advancing) return;                     // ignore Space while a placement is in flight
    advancing = true;
    try { await _advance(); } finally { advancing = false; }
  }

  async function _advance() {
    const cur = cursor;
    const curTile = tileOf(cur);

    // 1. The current tile: place it if it has nowhere to be. Never change a judged state.
    //    ⭐ SPACE ALWAYS PLACES IT (his ruling). If the match is not confident, `decidePlacement`
    //    hands back the SOLVER's position instead — and if there is no solver position and no match
    //    either, only THEN does it stay unplaced and the cursor still advances (API.md §2.1).
    if (curTile.state === 'unplaced' && anchored().length) {
      const res = await foregroundMatch(cur, 'global', null);
      const dec = decidePlacement(cur, res);
      if (dec.xy) {
        pushUndo('place:' + cur);
        setState(cur, 'unverified', dec.xy[0], dec.xy[1]);
        curTile.source = dec.diverted
          ? "the SOLVER's position (the anchor-composite match was not confident) — Space"
          : 'placed against the anchor composite (Space)';
        await recordPlacement(cur, res, dec);
        announcePlacement(cur, res, dec);
        if (res && res.refused) showRefusal(cur, res.refused);   // divert-aware; keeps the rail
      }
    }

    // 2. The next tile.
    const nxt = nextTrial(cur);
    if (nxt === null) {
      banner('End of the run. <b>' + counts().unverified + '</b> still unverified.', 'ok');
      refresh();
      return;
    }
    /* 🔴 THE CURSOR DOES NOT MOVE UNTIL THE ANSWER IS IN HAND. It used to move HERE, before the
     * ~1 s match below — see `busyPlacing()` for what that cost. Committing it at the point of
     * DISPLAY is the only moment at which "the tile under judgement" and "the tile on the screen"
     * are the same tile. */
    const commitCursor = () => { cursor = nxt; doc.cursor = nxt; setCursorUI(nxt); };
    const tile = tileOf(nxt);

    // ⭐⭐ RE-PLACE IT AGAINST THE ANCHOR FIELD — even if the build already placed it.
    // This is the core of the design, not an optimisation: the anchor field is HUMAN-CERTIFIED and
    // it is a big aperture, and a big trusted reference field does not lie the way a 0.5 Mpx
    // tile-pair does (of 719 overlapping pairs, the exact-NCC argmax is >20 px wrong for 5 %, at
    // scores up to 0.760). **The batch solve is the FALLBACK and the CROSS-CHECK, not the answer.**
    // That is what makes the sweep get MORE ACCURATE AS IT GOES.
    //   * `anchored` tiles are NEVER re-placed — the human already certified them; they are truth.
    //   * 🔴 NEITHER IS A TILE THE HUMAN HAS ALREADY MOVED BY HAND. It used to be: only `anchored`
    //     was protected, so a tile the user dragged, snapped, and then DEFERRED with Space (which is
    //     exactly the flow PLAN.md Step 4 prescribes for a hard tile — you correct it *and* you
    //     defer it) was silently re-placed on the next visit, throwing the hand-placement away and
    //     leaving `source` claiming the matcher had put it there. Demonstrated: 13 hand-moved to the
    //     ground truth, `back` then `Space` → snapped straight back to the matcher's answer. When the
    //     user drags a tile it is usually *because the matcher was wrong*; re-running the matcher
    //     puts it straight back on the wrong answer. `A` and `E` are the only things that judge; a
    //     hand position is the human's, and only the human may replace it (drag again, `S`, or `V`).
    //   * A refusal (blank) or an empty candidate list falls back to whatever position it had.
    if (tile.state === 'anchored') {
      showEvidence(nxt);
    } else if (tile.human && tile.x !== null) {
      showEvidence(nxt);
      banner('Trial ' + nxt + ' is <b>where you put it</b> — not re-matched. ' +
             '<kbd class="kbd">S</kbd> to snap, <kbd class="kbd">V</kbd> for alternatives, ' +
             '<kbd class="kbd">A</kbd> to certify.', 'ok');
    } else if (!anchored().length) {
      // Nothing to match against yet. The user has to anchor an origin first.
      commitCursor();
      banner('No anchors — <kbd class="kbd">A</kbd> makes trial ' + nxt + ' the origin (0, 0).', 'warn');
      refresh();
      return;
    } else {
      const res = await foregroundMatch(nxt, 'global', null);
      const dec = decidePlacement(nxt, res);
      if (dec.xy) {
        pushUndo('place:' + nxt);
        setState(nxt, 'unverified', dec.xy[0], dec.xy[1]);
        tile.source = dec.diverted
          ? "the SOLVER's position (the anchor-composite match was not confident) — Space"
          : (tile.machine
              ? 't33 build, re-placed against the anchor composite (Space)'
              : 'placed against the anchor composite (Space)');
        await recordPlacement(nxt, res, dec);
        announcePlacement(nxt, res, dec);
        if (res && res.refused) showRefusal(nxt, res.refused);   // divert-aware; keeps the rail

        // The CROSS-CHECK, for the CONFIDENT branch only. `machine` keeps t33's own answer, so
        // moved_px — and the evidence rail's machine note — say exactly how far the human-certified
        // field disagrees with the solver. (When we DIVERTED, moved_px is 0 by construction and
        // `announcePlacement` has already said the louder thing.)
        if (!dec.diverted && tile.machine && tile.moved_px > 20) {
          banner('Trial ' + nxt + ': the anchor field disagrees with the solver by <b>' +
                 fmt(tile.moved_px, 0) + ' px</b>, but the match is <b>confident</b> (NCC ' +
                 fmt(tile.ncc, 4) + ', margin ' + fmt(tile.margin, 4) + ') — so the field wins. ' +
                 'Check it (<kbd class="kbd">D</kbd>) before you anchor.', 'warn');
        }
      } else if (tile.x === null) {
        commitCursor();
        refresh();
        return;   // no match, no solver position, nowhere to be: stays unplaced; the cursor advanced.
      } else {
        // Refused (blank) and no solver answer either, but it already had a position. Keep it.
        showEvidence(nxt);
      }
    }

    // 3. ⭐ THE FADE. Transparent -> opaque over a full second. Watching the tile materialise over
    //    the anchored background is HOW HE SEES whether it lines up. Do not await it — the point of
    //    the prefetch is to hide the next match INSIDE it.
    commitCursor();
    if (viewerOk) Viewer.fadeIn(nxt, tile.x, tile.y);

    // 4. 🔴 The moment it is DISPLAYED (not judged — displayed), warm the next one, A-branch.
    prefetchNext(nxt);

    refresh();
    scheduleAutosave();
  }

  /** A foreground match: shows the wait, guards against a stale response, surfaces a refusal. */
  async function foregroundMatch(target, mode, near) {
    const my = ++matchSeq;
    inflight++;
    document.body.classList.add('busy');
    try {
      const res = await matchAnchor(target, mode, near);
      if (my !== matchSeq) return null;    // a newer request has overtaken this one
      if (res.refused) {
        showRefusal(target, res.refused);
        return res;
      }
      banner(null);
      return res;
    } catch (e) {
      if (e.code === 'busy' || e.status === 409) {
        toast('A build is running — it owns the GPU.', 'bad');
      } else {
        toast('Match failed: ' + e.message, 'bad');
      }
      return null;
    } finally {
      inflight--;
      if (!inflight) document.body.classList.remove('busy');
    }
  }

  /** ⛔ BLANK TILES ARE REFUSED, NOT SCORED. Two blank frames 136 trials apart correlate +0.43 at
   *  zero shift — what they share is fixed-pattern SENSOR structure, which does not move with the
   *  stage. They register confidently and WRONGLY. There is no force flag and there will not be one.
   *  The human eye may still drag it into place; the correlator may not. */
  function showRefusal(target, refused) {
    lastCandidates = null;
    if (!el.refused) return;
    const tl = tileOf(target);
    // ⭐ THE TILE MAY HAVE BEEN PLACED ANYWAY, at the SOLVER's position (his ruling: Space always
    //    places). The refusal is still true and still loud — the CORRELATOR gets no vote on a blank
    //    frame — but "refused" must not read as "and so nothing happened", because something did.
    const placedAnyway = !!(tl && tl.diverted && tl.x !== null);
    if (refused.reason === 'no_anchors') {
      el.refused.className = 'warn info';
      el.refused.innerHTML = '<div><b>No anchor field yet.</b> ' + (refused.message || '') + '</div>';
    } else {
      el.refused.className = 'warn loud';
      el.refused.innerHTML =
        '<div><b>REFUSED — ' + (refused.reason || 'blank') + '.</b> The matcher gets no vote here.' +
        // The background — WHY a blank frame is refused — is a hover, not a paragraph.
        '<span class="help" data-help="Two blank frames 136 trials apart correlate +0.43 at ZERO ' +
        'SHIFT: what they share is fixed-pattern SENSOR structure, which does not move with the ' +
        'stage. They register confidently and wrongly.&#10;&#10;There is no force flag. Your eye may ' +
        'still drag it into place; the correlator may not."></span>' +
        (refused.texture !== undefined
          ? '<div class="muted mono" style="font-size:11px;margin-top:4px">texture ' +
            fmt(refused.texture, 2) + ' &lt; threshold ' + fmt(refused.threshold, 2) + '</div>' : '') +
        (placedAnyway
          ? '<div class="warn info" style="margin-top:8px"><b>Placed anyway, at the solver\'s ' +
            'position</b> (' + fmt(tl.x, 1) + ', ' + fmt(tl.y, 1) + '). Unverified, and it will not ' +
            '<kbd class="kbd">S</kbd>-snap. Drag it if it is wrong.</div>'
          : '') +
        '<div class="row tight" style="margin-top:8px">' +
        (placedAnyway ? '' : '<button class="btn sm" id="btn-handplace">Drop it by hand</button>') +
        '<button class="btn sm danger" id="btn-refuse-exclude">Exclude it</button></div></div>';
      const hp = $('btn-handplace');
      if (hp) hp.onclick = () => handPlace(target);
      const ex = $('btn-refuse-exclude');
      if (ex) ex.onclick = () => exclude();
      Help.reindex(el.refused);     // the `?` we just injected must be keyboard-reachable too
    }
    el.refused.classList.remove('hidden');
    // Only wipe the rail when there is genuinely nothing to show. A tile placed at the solver's
    // position HAS honest evidence (the NCC measured where it actually sits) and must keep it.
    if (!placedAnyway) clearEvidence();
  }

  /** A blank tile the matcher refuses can still be placed BY HAND — a human eye is allowed to do
   *  what the correlator must not. Drop it on top of the previous placed tile so it exists on the
   *  canvas and can be dragged. It gets no NCC, because there is no honest one. */
  function handPlace(t) {
    const p = prevTrial(t);
    const src = p !== null && tileOf(p).x !== null ? tileOf(p) : null;
    if (!src) { toast('Nothing placed nearby to drop it beside.', 'bad'); return; }
    pushUndo('handplace:' + t);
    setState(t, 'unverified', src.x, src.y);
    tileOf(t).source = 'hand-dragged (no snap — blank tile, matcher refused)';
    tileOf(t).ncc = null; tileOf(t).margin = null;
    tileOf(t).human = true;         // a blank tile the correlator refuses: the eye is the authority
    // The hand has taken over, so any earlier divert claim is dead (as in `setPos`). `setState` does
    // NOT clear these — anchoring a diverted tile must KEEP the record of how it got there.
    delete tileOf(t).diverted; delete tileOf(t).divert_reason; delete tileOf(t).rejected_match;
    if (viewerOk) Viewer.setDiverted(t, false);   // and the magenta outline goes with the claim
    banner('Trial ' + t + ' dropped by hand. <b>It will not snap</b> — blank frames are refused. ' +
           'Drag it.', 'warn');
    if (viewerOk) Viewer.fadeIn(t, src.x, src.y);
    refresh();
    scheduleAutosave();
  }

  /** Keep the response for the rail and for `V`, STAMPED WITH THE FIELD IT WAS MEASURED AGAINST.
   *  It does NOT touch the tile's own numbers — a search's `best` is only the tile's NCC if the
   *  tile is actually being moved there. (`V` looks; it does not move.) */
  function stashEvidence(t, res) {
    if (!res) return;
    res._field = fieldSig(t);
    evidence[K(t)] = res;
    lastCandidates = res.candidates || null;
  }

  /** Record what the pixels said about a placement THE TILE IS BEING MOVED TO. DISPLAY +
   *  PROVENANCE — never a source of truth for a position. `tiles[*].ncc` is defined by the schema
   *  as the NCC **at the tile's final position**, so only a caller that is putting the tile on
   *  `res.best` may call this. */
  function recordEvidence(t, res) {
    stashEvidence(t, res);
    const tile = tileOf(t);
    tile.ncc       = res.best ? res.best.ncc : null;
    tile.npix      = res.best ? res.best.npix : null;
    tile.margin    = (res.margin === undefined) ? null : res.margin;
    tile.n_anchors = res.n_anchors !== undefined ? res.n_anchors : anchored().length;
    delete tile.alt_rank;
    showEvidence(t);
  }

  // =========================================================================================
  // Drag · snap · nudge · alternatives
  // =========================================================================================

  /** A drag or an arrow-key nudge. ⭐ **NEVER DEMOTES AN ANCHOR.** If the user moves an anchored
   *  tile he is CORRECTING it — he is the authority — and it stays anchored. Only `A` and `E` change
   *  state. But every tile matched against the field AFTER that anchor was placed was matched
   *  against a field that no longer exists: mark them stale and offer a re-check. */
  function move(trial, x, y) {
    const tile = tileOf(trial);
    if (!tile || tile.state === 'excluded') return;
    const wasAnchored = tile.state === 'anchored';
    const oldSeq = tile.seq;

    // ONE undo entry per gesture. A drag has already pushed on its first pointermove (`dragTag`),
    // so it does not push again on drop. Everything else that moves a tile — an arrow nudge, a click
    // on an alternative, a programmatic move — pushes here, and the 700 ms tag folding collapses a
    // held arrow key into a single step. `move()` owning this is deliberate: a caller that forgets
    // would silently make the move un-undoable.
    if (dragTag !== trial) pushUndo('move:' + trial);

    if (tile.state === 'unplaced') {
      setState(trial, 'unverified', x, y);
      tile.source = 'hand-dragged';
    } else {
      setPos(trial, x, y);
    }
    // ⭐ THIS POSITION IS THE HUMAN'S. `advance()` will not re-match over it. (Only `A`/`E` judge;
    //    a hand position is only ever replaced by the human — another drag, `S`, or `V`.)
    tile.human = true;
    // Say who put it there. It used to keep claiming "placed against the anchor composite (Space)"
    // after the human had dragged it — crediting the matcher for the human's correction.
    if (!/corrected|hand/.test(tile.source || '')) {
      tile.source = tile.machine ? 't33 build, corrected by hand'
                                 : (tile.source ? tile.source + ', corrected by hand' : 'hand-dragged');
    }

    if (wasAnchored && oldSeq !== undefined) markStaleAfter(oldSeq, trial);
    doc.modified = iso();
    refresh();
    scheduleAutosave();
  }

  /** API.md §7.5 — staleness. The backend does not track it (the memo key already guarantees any
   *  NEW request gets an honest recompute); the front end must. */
  function markStaleAfter(seq, exceptTrial, announce) {
    let n = 0;
    for (const t of trials()) {
      const tl = tileOf(t);
      if (t === exceptTrial) continue;
      if ((tl.state === 'anchored' || tl.state === 'unverified') && tl.seq > seq) {
        tl.stale = true;
        // 🔴 AND ITS EVIDENCE DIES WITH IT. `evidence[t]` holds CANDIDATE WORLD COORDINATES measured
        // against the field that just changed, and `V` will happily move the tile onto one of them.
        // A stale flag the code does not act on is decoration. (`fieldSig` catches this anyway; this
        // is the second belt, and it stops the rail printing an obsolete NCC as if it were current.)
        delete evidence[K(t)];
        n++;
      }
    }
    // ⚠️ A LIVE WARNING: N tiles were matched against a field that no longer exists. It stays.
    if (n && announce !== false) {
      banner('Anchor moved — <b>' + n + '</b> tile' + (n === 1 ? '' : 's') + ' may be stale.', 'warn');
    }
    return n;
  }

  /** `S` / the snap button — sub-pixel-perfect against the anchor composite, near where he dropped
   *  it. ⚠️ The committed number is the SERVER's: real spectralign-grade SWIM on 16-bit pixels, on
   *  the GPU. A browser-side JS NCC is alias-safe only within ~±48 px (the electrode grid repeats
   *  every 256 px) and past that it locks onto a confident, WRONG alias. ~1 s per click is accepted:
   *  CORRECT BEATS FAST (his ruling). And a BLANK tile REFUSES to snap. */
  async function snap() {
    if (busyPlacing('snap')) return;
    const t = cursor;
    if (t === null) return;
    const tile = tileOf(t);
    if (tile.x === null) { toast('Trial ' + t + ' has no position to snap.', 'bad'); return; }
    const res = await foregroundMatch(t, 'local', [tile.x, tile.y]);
    if (!res || res.refused || !res.best) return;
    pushUndo('snap:' + t);
    const before = [tile.x, tile.y];
    setPos(t, res.best.x, res.best.y);
    tile.human = true;              // the human asked for this refinement AT this drop point
    // ⚠️ The guard must test for `snapped`, NOT for `corrected`. `move()` has already written
    // "…corrected by hand" by the time the user presses `S` — and drag-then-snap is THE prescribed
    // flow (PLAN.md step 4) — so a `/corrected/` guard meant the snap could never record itself and
    // the QC report claimed a hand-dropped position on every tile the matcher had actually refined.
    if (!/snapped/.test(tile.source || '')) {
      tile.source = tile.machine ? 't33 build, corrected by hand + snapped against the anchor composite'
                                 : 'hand-dragged + snapped against the anchor composite';
    }
    recordEvidence(t, res);
    const d = Math.hypot(res.best.x - before[0], res.best.y - before[1]);
    banner('Snapped ' + d.toFixed(2) + ' px. NCC <b>' + fmt(res.best.ncc, 4) + '</b>' +
           (res.margin !== null && res.margin !== undefined ? ', margin ' + fmt(res.margin, 3) : '') +
           '.', res.margin_thin ? 'warn' : 'ok');
    if (viewerOk) Viewer.fadeIn(t, tile.x, tile.y);
    refresh();
    scheduleAutosave();
  }

  /** `V` — the ranked runner-ups ("did you mean here instead?").
   *
   *  🔴 IT MUST NOT SERVE A CACHED LIST MEASURED AGAINST A FIELD THAT NO LONGER EXISTS. Clicking a
   *  candidate MOVES THE TILE THERE, so a stale list is not a stale *display*, it is a wrong
   *  *placement* offered to the user with a confident NCC beside it. `evidenceIsCurrent()` compares
   *  the stamped anchor field with the one the app has right now; anything else is re-fetched, and
   *  the server memo makes that ~1 ms when nothing has actually changed. */
  async function showAlternatives() {
    if (busyPlacing('alternatives')) return;
    const t = cursor;
    if (t === null) return;
    altsOn = !altsOn;
    if (el.btnAlts) el.btnAlts.classList.toggle('on', altsOn);
    if (!altsOn) { if (viewerOk) Viewer.clearAlternatives(); renderAlts(null); return; }
    let res = evidenceIsCurrent(t) ? evidence[K(t)] : null;
    if (!res || !res.candidates) res = await foregroundMatch(t, 'global', null);
    if (!res || res.refused) { altsOn = false; if (el.btnAlts) el.btnAlts.classList.remove('on'); return; }
    // The list is now, by construction, a list about the CURRENT field. Stash it and drop the stale
    // flag: the tile has just been re-measured against the field it will be judged against.
    stashEvidence(t, res);
    tileOf(t).stale = false;
    showEvidence(t);
    if (viewerOk) Viewer.showAlternatives(t, res.candidates || []);
    renderAlts(res.candidates || []);
  }

  /** The rescue list: every `unplaced` tile. The SAME call — there is no special path. And the same
   *  ruling: if the matcher is not confident, the tile is rescued to the SOLVER's position, not to
   *  an alias. It lands `unverified` either way — a rescue is a placement, never a judgement. */
  async function rescue(trial) {
    setCursor(trial);
    const res = await foregroundMatch(trial, 'global', null);
    const dec = decidePlacement(trial, res);
    if (!dec.xy) return;
    pushUndo('rescue:' + trial);
    setState(trial, 'unverified', dec.xy[0], dec.xy[1]);
    tileOf(trial).source = dec.diverted
      ? "rescued to the SOLVER's position (the anchor-composite match was not confident)"
      : 'rescued against the anchor composite';
    await recordPlacement(trial, res, dec);
    announcePlacement(trial, res, dec);
    if (dec.diverted && res && res.refused) showRefusal(trial, res.refused);
    if (viewerOk) Viewer.fadeIn(trial, dec.xy[0], dec.xy[1]);
    refresh();
    scheduleAutosave();
  }

  // =========================================================================================
  // Undo / redo — the bench's engine (template.html:1649). 100-deep, tagged folding at 700 ms,
  // and a drag pushes ONCE, on the first pointermove.
  // =========================================================================================
  /* ⚠️ THE EVIDENCE IS PART OF THE STATE, SO IT IS PART OF THE SNAPSHOT. `restore()` used to swap
   * the document out and leave `evidence` untouched — so undoing a correction left the rail, and
   * `V`'s candidate list, describing a field the document no longer had. (`fieldSig` would now catch
   * the acting-on-it case, but an undo that silently changes what the evidence *means* is exactly
   * the class of bug this whole pass is about. Snapshot it.) */
  function snapshot() { return JSON.stringify({ doc, cursor, seq: seqCounter, evidence }); }
  function restore(s) {
    const o = JSON.parse(s);
    doc = o.doc; cursor = o.cursor; seqCounter = o.seq; evidence = o.evidence || {};
    if (viewerOk) { Viewer.setTiles(doc.tiles); Viewer.setCursor(cursor); }
    refresh();
  }
  function pushUndo(tag) {
    const now = performance.now();
    if (tag && tag === lastTag && (now - lastPushT) < FOLD_MS) { lastPushT = now; return; }
    undoStack.push(snapshot());
    if (undoStack.length > UNDO_DEPTH) undoStack.shift();
    redoStack.length = 0;
    lastTag = tag; lastPushT = now;
  }
  function undo() {
    if (!undoStack.length) { toast('Nothing to undo.'); return; }
    redoStack.push(snapshot());
    restore(undoStack.pop());
    lastTag = null;
    scheduleAutosave();
  }
  function redo() {
    if (!redoStack.length) { toast('Nothing to redo.'); return; }
    undoStack.push(snapshot());
    restore(redoStack.pop());
    lastTag = null;
    scheduleAutosave();
  }

  // =========================================================================================
  // Autosave — GENUINE crash recovery. NOT localStorage: in the artifact sandbox it failed
  // SILENTLY and nearly cost him a day's work. Debounced 2 s, plus UNCONDITIONALLY on A and E.
  // =========================================================================================
  function scheduleAutosave() {
    clearTimeout(autosaveTimer);
    autosaveTimer = setTimeout(autosave, AUTOSAVE_MS);
  }
  function autosaveNow() { clearTimeout(autosaveTimer); autosave(); }
  async function autosave() {
    if (!doc) return;
    try {
      const r = await POST('/api/project/autosave', { doc: exportDoc() });
      if (el.autosaveNote) el.autosaveNote.textContent = 'autosave: ' + (r.saved_at || 'ok');
    } catch (e) {
      /* 🔴 NEVER SWALLOW THIS. A silent autosave failure has burned him before and nearly cost a
       * day's work. It is a LIVE warning about the current state — it stays, loud, both places. */
      toast('AUTOSAVE FAILED: ' + e.message + ' — save by hand.', 'bad');
      if (el.autosaveNote) el.autosaveNote.textContent = 'autosave: FAILED';
    }
  }

  /** The document as it goes over the wire: derived fields filled in, NORMALISED, provenance honest. */
  function exportDoc() {
    const d = JSON.parse(JSON.stringify(doc));
    /* ⛔ THE APP CARRIES NO DATASET KNOWLEDGE, SO NEITHER DOES ANYTHING IT WRITES (his ruling,
     * 2026-07-14). This block used to be a hard-coded ruling about 26 named trials of one specific
     * acquisition. It is gone from `newDoc()` — and it is deleted HERE TOO, so that loading an OLD
     * project file and re-saving it does not silently resurrect it. The ONLY exclusion record that
     * survives is `unusable_tiles`, rebuilt below from what the HUMAN actually excluded. */
    delete d.EXCLUDED_TRIALS;
    const anc = anchored();
    const placedT = trials().filter((t) => tileOf(t).x !== null);
    d.origin_trial = anc.length ? Math.min.apply(null, anc)
                   : (placedT.length ? Math.min.apply(null, placedT) : (doc.origin_trial ?? null));
    d.unusable_tiles = trials().filter((t) => tileOf(t).state === 'excluded');
    d.cursor = cursor;
    d.gaps = recomputeGaps();
    d.modified = iso();

    // ⭐ NORMALISE. A layout is defined only up to a translation, so the origin trial is pinned at
    // exactly [0, 0] — matching analysis/ground_truth/ and what benchmark/score.py expects. The
    // MACHINE's positions are shifted by the SAME vector, so `machine`, `build.positions` and `x/y`
    // stay in one frame and `moved_px` keeps meaning what it says. (The backend normalises too;
    // subtracting zero a second time is a no-op, so doing it here is free insurance.)
    const o = d.origin_trial !== null && d.tiles[K(d.origin_trial)] ? d.tiles[K(d.origin_trial)] : null;
    if (o && o.x !== null) {
      const ox = o.x, oy = o.y;
      for (const k of Object.keys(d.tiles)) {
        const tl = d.tiles[k];
        if (tl.x !== null && tl.x !== undefined) { tl.x -= ox; tl.y -= oy; }
        if (tl.machine) { tl.machine = [tl.machine[0] - ox, tl.machine[1] - oy]; }
        if (tl.last_xy) { tl.last_xy = [tl.last_xy[0] - ox, tl.last_xy[1] - oy]; }
        // ⚠️ The REJECTED match's position is a world coordinate too. Miss it here and the QC report
        // ships the one number that says "the matcher wanted to put it HERE" in a frame that no
        // longer exists — off by the origin vector, and silently plausible.
        if (tl.rejected_match && tl.rejected_match.x !== null && tl.rejected_match.x !== undefined) {
          tl.rejected_match = Object.assign({}, tl.rejected_match,
            { x: tl.rejected_match.x - ox, y: tl.rejected_match.y - oy });
        }
      }
      if (d.build && d.build.positions) {
        for (const k of Object.keys(d.build.positions)) {
          const p = d.build.positions[k];
          d.build.positions[k] = [p[0] - ox, p[1] - oy];
        }
      }
    }

    // human_edits — the honest record of what the human did to the machine's answer.
    let acc = 0, moved = 0, exc = 0, unv = 0, resc = 0, div = 0;
    const moves = [], diverted = [];
    for (const t of trials()) {
      const tl = tileOf(t);
      if (tl.state === 'excluded') exc++;
      if (tl.state === 'unverified') unv++;
      if (tl.machine && tl.x !== null) {
        const m = Math.hypot(tl.x - tl.machine[0], tl.y - tl.machine[1]);
        if (m < 0.5) acc++; else { moved++; moves.push(m); }
      }
      if (!tl.machine && tl.x !== null && doc.build) resc++;
      // ⭐ A DIVERTED TILE IS NOT "THE HUMAN ACCEPTED THE MACHINE" — it is "the app never gave the
      //   matcher a vote here". It lands in `accepted_unchanged` above (it IS at the machine's
      //   position), which would read as agreement. Count it separately and say so, or the QC report
      //   overstates how much independent confirmation these positions actually got.
      if (tl.diverted && tl.state !== 'excluded') { div++; diverted.push(t); }
    }
    moves.sort((a, b) => a - b);
    d.provenance.human_edits = {
      accepted_unchanged: acc, moved, excluded: exc, unverified: unv, rescued: resc,
      median_move_px: moves.length ? moves[Math.floor(moves.length / 2)] : 0,
      max_move_px: moves.length ? moves[moves.length - 1] : 0,
      diverted_to_solver: div,
      diverted_trials: diverted,
      diverted_note: div
        ? 'These ' + div + ' tiles sit at the SOLVER\'s position because the anchor-composite match ' +
          'was not confident there (margin < ' + SOLVER_MARGIN_MIN.toFixed(2) + ' or NCC < ' +
          SOLVER_NCC_MIN.toFixed(2) + ') AND disagreed with it by more than ' +
          SOLVER_DISAGREE_PX.toFixed(0) + ' px. The correlator was overruled by the batch solve, not ' +
          'by the human. Each tile\'s `rejected_match` records what the matcher wanted. They count ' +
          'in `accepted_unchanged` as well — do not read that as independent agreement.'
        : null,
    };
    return d;
  }

  // =========================================================================================
  // THE KEYBOARD MAP (API.md §15.6)
  //   A anchor · E exclude · Space next · R replay the fade · D difference · V alternatives ·
  //   S snap · arrows nudge 1 px (Shift = 10) · F fit · 0 = 1:1 · Ctrl+Z / Ctrl+Y · Esc deselect
  //
  // ❌ NO BLUR SLIDER, NO SHARPNESS SCORE, NO VARIANCE-OF-LAPLACIAN NUMBER — ANYWHERE IN THE UI.
  //    Across 15 focus measures the best global blur threshold reaches F1 = 0.37, and
  //    variance-of-Laplacian — the textbook autofocus metric — scores WORSE THAN CHANCE (it is
  //    dominated by sensor noise, identical in sharp and blurry frames). Catching all 15 of his
  //    blurry frames also throws away 62 good ones, best case. His eye is the authority, and he
  //    meets every tile in this sweep. Blur is judged with `E`, by him.
  // =========================================================================================
  function onKeyDown(e) {
    const tag = (e.target && e.target.tagName) || '';
    if (/INPUT|TEXTAREA|SELECT/.test(tag) || (e.target && e.target.isContentEditable)) return;

    // ⭐ Ctrl+S SAVES FROM ANY SCREEN (his ruling, 2026-07-14: "at any time in the process I can
    // export the save file so I can resume later"). It MUST be handled up here, above the
    // `screen !== 'sweep'` gate below — the whole point is that it works everywhere, and an hour
    // into a sweep is exactly when he wants it. The project file is the app's only memory.
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's') { e.preventDefault(); saveProject(); return; }
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z') { e.preventDefault(); undo(); return; }
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'y') { e.preventDefault(); redo(); return; }
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    if (screen !== 'sweep') return;

    // The keys the SWEEP owns. Everything else (F, 0, D, G, Esc, arrows, +/-) belongs to the
    // viewer's camera and selection, and is delegated below — mounted with bindKeys:false, it does
    // NOT listen for itself, so this is the single dispatch point and nothing is handled twice.
    switch (e.key) {
      case ' ':           e.preventDefault(); advance(); return;
      case 'a': case 'A': e.preventDefault(); anchor(); return;
      case 'e': case 'E': e.preventDefault(); exclude(); return;
      case 'r': case 'R': e.preventDefault(); if (viewerOk) Viewer.replayFade(); return;
      case 'v': case 'V': e.preventDefault(); showAlternatives(); return;
      case 's': case 'S': e.preventDefault(); snap(); return;
      default: break;
    }
    if (!viewerOk) return;
    const handled = Viewer.handleKey(e);          // F · 0 · D · G · Esc · arrows (nudge) · +/-
    if (handled) syncViewerUI();
  }

  /** After the viewer has handled a key itself, pull its state back into our chrome. (An arrow-key
   *  nudge comes back to us through onDragEnd -> move(), so the document is already in step; this
   *  only syncs the toggles and the cursor.) */
  function syncViewerUI() {
    diffOn = Viewer.isDifference ? Viewer.isDifference() : diffOn;
    if (el.btnDiff) el.btnDiff.classList.toggle('on', diffOn);
    if (diffOn) banner(DIFF_MSG, 'ok');
    refresh();
  }

  function toggleDiff() {
    if (!viewerOk) return;
    diffOn = !diffOn;
    Viewer.setDifference(diffOn);
    if (el.btnDiff) el.btnDiff.classList.toggle('on', diffOn);
    banner(diffOn ? DIFF_MSG : null, 'ok');
  }

  // =========================================================================================
  // Rendering the panels
  // =========================================================================================
  function refresh() {
    if (!doc) return;
    const c = counts();
    el.nAnchored.textContent   = c.anchored;
    el.nUnverified.textContent = c.unverified;
    el.nUnplaced.textContent   = c.unplaced;
    el.nExcluded.textContent   = c.excluded;
    // ⭐ the diverted count. Hidden at zero (it is not a normal part of the vocabulary), shown the
    // moment one tile sits on the solver's answer — see counts().
    if (el.nDiverted) el.nDiverted.textContent = c.diverted;
    if (el.divertedBadge) el.divertedBadge.classList.toggle('hidden', !c.diverted);

    /* ⚠️ THE GAPS ARE LIVE. Excluding a tile opens an acquisition gap, and the Range screen's `?`
     * promises they are "recomputed every time you exclude a tile" — so they must actually be. This
     * used to be written once, at load, from the SESSION's list, and then never again. */
    if (el.gapsV) {
      const g = doc.gaps || [];
      el.gapsV.textContent = g.length ? g.map((p) => p[0] + '→' + p[1]).join(', ') : 'none';
    }
    lockSteps();

    const t = cursor;
    el.cbTrial.textContent = t === null ? '—' : t;
    if (t !== null && tileOf(t)) {
      const tile = tileOf(t);
      el.cbState.textContent = tile.state + (tile.stale ? ' · stale' : '');
      el.cbState.className = 'badge ' + tile.state;
      el.cbPass.innerHTML = 'pass ' + tile.pass +
        (tile.blank ? ' <span class="badge blank">blank (measured)</span>' : '');
      // ⚠️ TOP-LEFT, not the centre. Anything drawing a centre adds +256. Say which it is, here.
      el.cbPos.textContent = tile.x === null ? 'none'
        : fmt(tile.x, 2) + ', ' + fmt(tile.y, 2);
    } else {
      el.cbState.textContent = '—'; el.cbState.className = 'badge unplaced';
      el.cbPass.textContent = ''; el.cbPos.textContent = '—';
    }
    const ts = trials();
    el.queuePos.textContent = (t === null ? '—' : (ts.indexOf(t) + 1) + ' / ' + ts.length);

    renderQueue();
    renderRescue();
    renderStale();
    renderBuildStale();     // ⚠️ "the build was solved on a different input" — nothing read this
    renderProvenance();
  }

  /** `ncc === null` means NOT MEASURABLE (below exact_ncc's overlap floor). Show "—" in the
   *  "not applicable" style style.css provides (.v.na) — **never 0.0**, which is a measurement. */
  function setNcc(v) {
    const ok = (v !== null && v !== undefined && isFinite(v));
    el.evNcc.textContent = ok ? fmt(v, 4) : '—';
    el.evNcc.className = 'v big' + (ok ? '' : ' na');
    const bar = el.evNccMeter && el.evNccMeter.querySelector('i');
    if (bar) bar.style.width = (ok ? Math.max(0, Math.min(1, v)) * 100 : 0) + '%';
  }

  function clearEvidence() {
    setNcc(null);
    el.evMargin.textContent = '—'; el.evAnchors.textContent = '—';
    el.evArea.textContent = '—'; el.evNpix.textContent = '—'; el.evMs.textContent = '—';
    el.evThin.classList.add('hidden');
    if (el.evNccMeter) el.evNccMeter.classList.remove('thin');
    el.evAperture.classList.add('hidden');
    el.evMachine.innerHTML = '';
  }

  /** ⭐ ALWAYS SHOW THE EVIDENCE BEHIND A PLACEMENT: the NCC, the best-vs-second margin, the number
   *  of anchors and the composite's area. He watches the evidence strengthen; he does not take the
   *  placement on faith. A THIN MARGIN IS FLAGGED LOUDLY. */
  function showEvidence(t) {
    el.refused.classList.add('hidden');
    const res = evidence[K(t)];
    const tile = tileOf(t);
    if (!res) { clearEvidence(); showMachineNote(tile); return; }

    const b = res.best;
    /* 🔴 THE NCC ON THE RAIL IS THE NCC AT THE TILE'S FINAL POSITION. On a DIVERTED tile the final
     * position is the SOLVER's, not `res.best` — so painting `res.best.ncc` here would put the
     * REJECTED alias's confident-looking score (0.53, 0.64…) next to a position it was never
     * measured at. That is the same bug `pickAlternative` was fixed for. `recordPlacement` measured
     * the tile where it really sits (`POST /api/match/score`); that is `tile.ncc`, and it is what
     * goes on the rail — `null` (`—`) if the overlap is not measurable, never 0.0. */
    setNcc(tile.diverted ? tile.ncc : (b ? b.ncc : null));
    el.evMargin.textContent  = (res.margin === null || res.margin === undefined) ? '—' : fmt(res.margin, 4);
    el.evAnchors.textContent = res.n_anchors !== undefined ? res.n_anchors : '—';
    el.evArea.textContent    = res.composite
      ? (res.composite.valid_px / 1e6).toFixed(2) + ' Mpx' : '—';
    el.evNpix.textContent    = b ? (b.npix / 1e3).toFixed(0) + ' k' : '—';
    // ⚠️ SAY IT WHEN THE NUMBERS ARE ABOUT A FIELD THAT NO LONGER EXISTS. The rail used to print a
    // confident cached NCC (0.9298, measured against a mis-anchored field) as though it were current
    // evidence for the tile. It is evidence — about a different question.
    const oldField = !!(res._field !== undefined && res._field !== fieldSig(t));
    el.evMs.textContent      = (res.elapsed_ms !== undefined ? res.elapsed_ms + ' ms' : '—') +
                               (res.cached ? ' · cached' : '') + (res.gpu ? ' · GPU' : '') +
                               (oldField ? ' · AN EARLIER ANCHOR FIELD' : '');

    const thin = !!res.margin_thin ||
                 (res.margin !== null && res.margin !== undefined && res.margin < THIN_MARGIN);
    el.evThin.classList.toggle('hidden', !thin);
    if (el.evNccMeter) el.evNccMeter.classList.toggle('thin', thin);

    /* ⚠️ A LIVE WARNING ABOUT THE CURRENT TILE: at n_anchors <= 2 this IS a tile-pair match — the
     * weak case, and the one that lies confidently. It fires only when the aperture is genuinely
     * thin, so it stays on the page. Its BACKGROUND lives on the `?`. */
    const na = res.n_anchors;
    if (na !== undefined && na <= 2) {
      el.evAperture.classList.remove('hidden');
      el.evAperture.innerHTML =
        '<div><b>Small aperture (' + na + ' anchor' + (na === 1 ? '' : 's') + ').</b> Check it in ' +
        'Difference (<kbd class="kbd">D</kbd>) before you anchor.' +
        '<span class="help" data-help="Essentially a tile-pair match. At tile-pair aperture the ' +
        'exact-NCC winner is >20 px wrong 5 % of the time, at scores up to 0.760 — one measured ' +
        'pair scores 0.760 and is 757 px wrong, while the truth is the runner-up at 0.677.&#10;&#10;' +
        'What saves the opening is that consecutive snapshots overlap ~78 %. The aperture, and the ' +
        'evidence, strengthen with every anchor you add."></span></div>';
      Help.reindex(el.evAperture);
    } else {
      el.evAperture.classList.add('hidden');
    }
    showMachineNote(tile);

    /* ⛔ A BLANK TILE STAYS BLANK WHEN YOU COME BACK TO IT. `showEvidence` hides the refusal panel at
     * the top, and nothing re-showed it — so the loud "REFUSED — blank: any match it scores is
     * fixed-pattern SENSOR structure, not the scene" warning existed only for the one second after
     * the match, and clicking back onto trial 34 from the queue showed a tile with a position and no
     * warning at all. That matters more now than it did: the tile now HAS a position (the solver's),
     * so it looks placed and settled. The refusal is a standing fact about the pixels, not a
     * transient event — re-assert it from the stamped evidence. (`showRefusal` is divert-aware: it
     * keeps the rail intact when the tile was placed anyway.) */
    if (res.refused && res.refused.reason && res.refused.reason !== 'no_anchors') {
      showRefusal(t, res.refused);
    }
  }

  /** ⚠️ THE ANCHORING HAZARD, said out loud. Pass 1's ground truth got 4 tiles wrong precisely
   *  because a human deferred to a build he could see. If the tile is still exactly where the
   *  machine put it, say so — do not let "I looked at it" and "I agreed with it" blur together. */
  function showMachineNote(tile) {
    if (!tile) { el.evMachine.innerHTML = ''; return; }

    /* ⭐ THE DIVERT BLOCK (his ruling). Say WHICH position is on the screen, WHY, and what the
     * matcher wanted instead — the evidence, not just a verdict. Without this the tile would sit at
     * the machine's position reading "At the machine's position, untouched", which is TRUE and
     * completely misses the point: the app actively refused the matcher's answer here. */
    let head = '';
    if (tile.diverted) {
      const rm = tile.rejected_match;
      head =
        '<div class="warn loud" style="margin-bottom:8px">' +
        '<div><b>SOLVER\'S POSITION, NOT THE MATCHER\'S.</b>' +
        '<span class="help" data-help="The anchor-composite match was not confident here, so it was ' +
        'overruled by the batch solve.&#10;&#10;At a thin aperture the matcher lies CONFIDENTLY: ' +
        'measured, with only trial 11 anchored it put trial 13 284.8 px out at margin 0.0129. The ' +
        'batch solve places 312/312.&#10;&#10;The NCC above is measured where the tile ACTUALLY ' +
        'SITS, not at the answer that was rejected. Nothing is anchored until you press A."></span>' +
        '</div>' +
        '<div class="muted" style="margin-top:4px">' + (tile.divert_reason || '—') + '</div>' +
        (rm
          ? '<div class="mono" style="font-size:11px;margin-top:4px">matcher wanted (' +
            fmt(rm.x, 1) + ', ' + fmt(rm.y, 1) + ') — <b>' + fmt(rm.px_from_solver, 0) + ' px away</b>' +
            ', NCC ' + fmt(rm.ncc, 4) +
            (rm.margin === null || rm.margin === undefined ? '' : ', margin ' + fmt(rm.margin, 4)) +
            '. <kbd class="kbd">V</kbd> to see it.</div>'
          : '<div class="mono" style="font-size:11px;margin-top:4px">the matcher returned nothing — ' +
            'there is no alternative to compare.</div>') +
        '</div>';
    }

    if (!tile.machine) { el.evMachine.innerHTML = head; Help.reindex(el.evMachine); return; }
    const d = tile.x === null ? null : Math.hypot(tile.x - tile.machine[0], tile.y - tile.machine[1]);
    /* ⚠️ THE ANCHORING HAZARD, said out loud: "I looked at it" and "I agreed with it" must not blur
     * together. A tile still sitting exactly where the machine put it says so. */
    el.evMachine.innerHTML = head + ((d !== null && d < 0.5)
      ? '<span style="color:var(--c-unverified)">At the machine\'s position, <b>' +
        (tile.diverted ? 'because the app put it there — not because you agreed' : 'untouched') +
        '</b>.</span>'
      : '<span style="color:var(--c-anchored)">Moved <b>' + fmt(d, 2) + ' px</b> from the machine (' +
        fmt(tile.machine[0], 1) + ', ' + fmt(tile.machine[1], 1) + ').</span>');
    Help.reindex(el.evMachine);
  }

  /** ⭐ "Did you mean HERE instead?" — the human takes a runner-up peak.
   *
   *  🔴 THE EVIDENCE MUST FOLLOW THE TILE, AND IT MUST DO SO ON **BOTH** ROUTES. There are two ways
   *  to pick an alternative — the list in the rail, and a click on the ranked ghost rectangle ON THE
   *  CANVAS (PLAN.md:180-181; it is the primary affordance, and it is the one a user actually
   *  reaches for). The rail's handler recorded the peak's ncc/npix/rank; the canvas's called only
   *  `move()`, so the tile kept **rank 0's NCC at rank 1's position**. Driven on trial 28 (margin
   *  0.026 — a textbook alias): after clicking the canvas ghost, the tile sat 2,113 px away still
   *  carrying `ncc: 0.4477`, with `alt_rank` and `npix` undefined and a `source` that did not name
   *  the alias. The schema defines `tiles[*].ncc` as the NCC **at its final position**, and this is
   *  the exact flow where it matters most: the thin-margin case is *why* the human is overruling
   *  rank 0 (trial 119: rank 0 = 0.5303 and 797 px wrong; rank 1 = 0.5019 and correct). The exported
   *  GT and QC would attribute the alias's score to the human's correction.
   *
   *  ONE helper; both call sites use it. */
  function pickAlternative(t, c) {
    if (t === null || !tileOf(t) || !c) return;
    move(t, c.x, c.y);                 // move() pushes the undo entry and flags it `human`
    const tl = tileOf(t);
    tl.ncc      = (c.ncc === undefined ? null : c.ncc);
    tl.npix     = (c.npix === undefined ? null : c.npix);
    tl.alt_rank = c.rank;              // which peak the human chose, kept for the QC report
    // The rail reads the stashed response, so re-point its `best` at the peak the human took.
    // `margin` deliberately STAYS the search's best-minus-second: the near-tie is the whole reason
    // this tile was corrected by hand, and hiding it would hide the alias.
    const ev = evidence[K(t)];
    if (ev) { ev.best = c; ev.picked_rank = c.rank; }
    if (c.rank !== 0) {
      tl.source = (tl.machine ? 't33 build, ' : '') +
        'moved by hand to alternative #' + c.rank + ' of the anchor-composite search' +
        ' (rank 0 was a thin-margin alias)';
    }
    showEvidence(t);
    banner('Moved to alternative #' + c.rank + ' (NCC ' + fmt(c.ncc, 4) + '). ' +
           '<kbd class="kbd">S</kbd> to snap.', 'ok');
    if (viewerOk) Viewer.fadeIn(t, c.x, c.y);
  }

  function renderAlts(cands) {
    if (!cands || !cands.length) {
      el.altsList.innerHTML = '<div class="muted">Press <kbd class="kbd">V</kbd>.</div>';
      return;
    }
    el.altsList.innerHTML = '';
    cands.forEach((c) => {
      const d = document.createElement('div');
      d.className = 'item alt' + (c.rank === 0 ? ' on' : '');
      d.innerHTML = '<span class="t">#' + c.rank + '</span>' +
                    '<span class="n">' + fmt(c.ncc, 4) + '</span>' +
                    '<span class="spacer"></span>' +
                    '<span class="n">' + fmt(c.x, 1) + ', ' + fmt(c.y, 1) + '</span>' +
                    '<span class="n">' + (c.npix / 1e3).toFixed(0) + ' k</span>';
      d.title = c.rank === 0 ? 'the placement' : 'a runner-up peak — click to move the tile here';
      d.onclick = () => pickAlternative(cursor, c);
      el.altsList.appendChild(d);
    });
  }

  function renderQueue() {
    const onlyOut = el.onlyOutstanding && el.onlyOutstanding.checked;
    const frag = document.createDocumentFragment();
    for (const t of trials()) {
      const tl = tileOf(t);
      if (onlyOut && !(tl.state === 'unverified' || tl.state === 'unplaced')) continue;
      const d = document.createElement('button');
      d.className = 'q ' + tl.state + (t === cursor ? ' cursor' : '') + (tl.stale ? ' stale' : '');
      d.textContent = t;
      d.title = t + ' · ' + tl.state + (tl.blank ? ' · blank (measured)' : '') +
                (tl.ncc != null ? ' · ncc ' + fmt(tl.ncc, 3) : '');
      d.onclick = () => setCursor(t);
      frag.appendChild(d);
    }
    el.queue.innerHTML = '';
    el.queue.appendChild(frag);
    const c = el.queue.querySelector('.q.cursor');
    if (c && c.scrollIntoView) c.scrollIntoView({ block: 'nearest' });
  }

  function renderRescue() {
    const un = trials().filter((t) => tileOf(t).state === 'unplaced');
    if (!un.length) { el.rescueList.innerHTML = '<div class="muted">None.</div>'; return; }
    el.rescueList.innerHTML = '';
    for (const t of un) {
      const d = document.createElement('div');
      d.className = 'item';
      d.innerHTML = '<span class="t">' + t + '</span>' +
                    (tileOf(t).blank ? '<span class="badge blank">blank</span>' : '') +
                    '<span class="spacer"></span>';
      const b = document.createElement('button');
      b.className = 'btn sm';
      b.textContent = 'Rescue';
      b.onclick = (e) => { e.stopPropagation(); rescue(t); };
      d.onclick = () => setCursor(t);
      d.appendChild(b);
      el.rescueList.appendChild(d);
    }
  }

  /** ⚠️ THE RE-CHECK MUST BE **GLOBAL**, AND IT MUST BE ALLOWED TO SAY "NO".
   *
   *  It used to fire `mode:'local'` around the tile's CURRENT position (±64 px) and then clear
   *  `stale` unconditionally, without ever moving the tile. But a tile knocked off by a moved anchor
   *  is off by HUNDREDS of px — failure on this data is binary, sub-pixel-right or wildly wrong — so
   *  a ±64 px window is structurally blind to the one error the panel exists for. Measured: a tile
   *  380 px from the truth re-checked LOCALLY to `ncc -0.0678`, was not moved, and had its flag
   *  cleared; the same tile re-checked GLOBALLY found the truth at `ncc 0.9394`, 0.9 px out. The loud
   *  "N tiles may be stale" panel disappeared and the tile stayed 380 px wrong, with a NEGATIVE NCC
   *  recorded in the document as its evidence.
   *
   *  So: match GLOBALLY, and if the current anchor field disagrees with where the tile sits by more
   *  than `RECHECK_TOL_PX`, **KEEP IT STALE AND SAY SO.** We never move it — a re-check is a
   *  measurement, and only `A`/`E`/a drag/`S`/`V` may place a tile. The panel offers the jump. */
  function renderStale() {
    const st = trials().filter((t) => tileOf(t).stale);
    el.stalePanel.classList.toggle('hidden', !st.length);
    if (!st.length) return;

    const bad = st.filter((t) => tileOf(t).recheck_px != null && tileOf(t).recheck_px > RECHECK_TOL_PX);
    let h = '<div><b>' + st.length + ' stale</b> — matched against an anchor field that has since ' +
      'changed.' +
      '<span class="help" data-help="A tile knocked off by a moved anchor is off by HUNDREDS of px — ' +
      'failure on this data is binary, sub-pixel right or wildly wrong.&#10;&#10;The re-check matches ' +
      'GLOBALLY and is allowed to say NO: it never moves the tile, it only measures it. Anything that ' +
      'disagrees by more than ' + RECHECK_TOL_PX + ' px STAYS flagged."></span> ' +
      '<button class="btn sm" id="btn-recheck">Re-check</button></div>';
    if (bad.length) {
      h += '<div style="margin-top:8px"><b>' + bad.length + ' disagree</b> by &gt; ' + RECHECK_TOL_PX +
           ' px — go and look:<div class="row tight" style="margin-top:6px">' +
           bad.map((t) => '<button class="btn sm danger go-stale" data-trial="' + t + '">' + t +
                          ' · ' + fmt(tileOf(t).recheck_px, 0) + ' px</button>').join('') +
           '</div></div>';
    }
    el.stale.innerHTML = h;
    el.stale.querySelectorAll('button.go-stale').forEach((b) => {
      b.onclick = () => setCursor(+b.dataset.trial);
    });
    Help.reindex(el.stale);

    const b = $('btn-recheck');
    if (b) b.onclick = async () => {
      let agreed = 0, refused = 0, failed = 0;
      const off = [];
      for (const t of st) {
        const tl = tileOf(t);
        if (tl.x === null) { tl.stale = false; continue; }
        const res = await foregroundMatch(t, 'global', null);     // ⬅️ GLOBAL, not local
        if (!res)            { failed++; continue; }              // keep it stale — we do not know
        if (res.refused)     { refused++; tl.stale = false; delete tl.recheck_px; continue; }
        if (!res.best)       { failed++; continue; }
        stashEvidence(t, res);                                    // candidates for `V`; not a position
        const d = Math.hypot(res.best.x - tl.x, res.best.y - tl.y);
        tl.recheck_px = d;
        tl.margin = (res.margin === undefined) ? null : res.margin;
        tl.n_anchors = res.n_anchors;
        // `tiles[*].ncc` is the NCC AT ITS FINAL POSITION — which is where it SITS, not where the
        // search would like it. One extra exact_ncc; it is the only honest number here.
        const s = await scoreAt(t, tl.x, tl.y);
        if (s && !s.refused) { tl.ncc = s.ncc; tl.npix = s.npix; }
        if (d > RECHECK_TOL_PX) { off.push(t); }                  // STAYS stale, deliberately
        else { tl.stale = false; agreed++; }
      }
      refresh(); scheduleAutosave();
      if (off.length) {
        // ⚠️ LIVE: these tiles are still wrong and they have NOT been moved. Loud.
        banner('<b>' + agreed + ' agree, ' + off.length + ' do not</b> (' +
               off.map((t) => t + ' by ' + fmt(tileOf(t).recheck_px, 0) + ' px').join(', ') +
               '). Still flagged, not moved — go and look.', 'warn');
      } else {
        banner('Re-checked ' + st.length + ': <b>' + agreed + ' agree</b> to ' + RECHECK_TOL_PX + ' px' +
               (refused ? ', ' + refused + ' refused (blank)' : '') +
               (failed ? ', ' + failed + ' unchecked' : '') + '.', 'ok');
      }
    };
  }

  function renderProvenance() {
    if (!el.provenance || !doc) return;
    const p = doc.provenance;
    /* ⭐ DERIVED FROM THE DOCUMENT'S HISTORY, never from what the document says about itself. A
     * `build` block, or a single tile still carrying a `machine` position, means every position here
     * started as a solver's answer — whatever `seeded_from` claims. (The backend's
     * `project.machine_evidence` applies the same rule to the exported stamp; this keeps the panel
     * from ever showing "Independent" over a seeded document.) */
    const seeded = !!doc.build || trials().some((t) => tileOf(t) && tileOf(t).machine);
    if (seeded && p.independent_of_method) { p.independent_of_method = false; }
    const method = (p.seeded_from && p.seeded_from.method) || 't33';
    el.provenance.className = p.independent_of_method ? 'warn info' : 'warn loud';
    el.provenance.innerHTML = p.independent_of_method
      ? '<div><b>Independent.</b> No build seeded this — it may be used to score a solver.' +
        '<span class="help" data-help="Every position here was placed by hand against the anchor ' +
        'field you built. It is an honest truth."></span></div>'
      : '<div><b>NOT AN INDEPENDENT GROUND TRUTH.</b> Every position started as ' + method +
        "'s output. <b>Never score " + method + ' with this.</b>' +
        '<span class="help" data-help="Confirmed or corrected by a human who could SEE the solver\'s ' +
        'answer. Scoring that method against this file returns ~100 % by construction.&#10;&#10;This ' +
        'project has already destroyed one benchmark exactly this way, and pass 1\'s ground truth got ' +
        'tiles 128/129/130/148 wrong for precisely this reason.&#10;&#10;The stamp goes into every ' +
        'file you export."></span></div>';
    Help.reindex(el.provenance);
  }

  function setCursor(t) {
    cursor = t;
    if (doc) doc.cursor = t;
    altsOn = false;
    if (viewerOk) Viewer.clearAlternatives();
    renderAlts(null);
    setCursorUI(t);
    if (t !== null) { if (evidence[K(t)]) showEvidence(t); else { clearEvidence(); el.refused.classList.add('hidden'); showMachineNote(tileOf(t)); } }
    refresh();
  }
  function setCursorUI(t) { if (viewerOk) Viewer.setCursor(t); }

  // =========================================================================================
  // ⭐ THE SIX-STEP WIZARD — his ruling, 2026-07-14: "make it more step by step"
  //      1 Load · 2 Range · 3 Screen · 4 Place · 5 Sweep · 6 Mosaic
  // =========================================================================================
  /* THE HEADER IS A PROGRESS INDICATOR, NOT A MENU. A step is LOCKED until everything before it is
   * ready — style.css's `.step.locked` does the look (and kills pointer-events); this enforces it.
   *
   * ⚠️ The gates are the ones that are REAL. There is no gate on "did he tick a blank box" or "did
   * he run the solver", because *not* ticking and *not* solving are both legitimate answers — Skip
   * goes straight to a hand-placed sweep. What is genuinely impossible is: a Range with no session,
   * and a Mosaic with nothing placed. Do not invent gates the workflow does not have; a wizard that
   * locks a step he is entitled to reach is worse than one that locks nothing. */
  const STEPS = ['load', 'range', 'screen', 'place', 'sweep', 'mosaic'];
  const READY = {
    load:   () => !!session,                       // a session exists = the Load step is done
    range:  () => !!session,                       // the range always has a value (the detected one)
    screen: () => !!session,
    place:  () => !!session,
    sweep:  () => anyPlaced(),                     // nothing to export until something has a position
    mosaic: () => true,
  };

  /** The furthest step he may click: everything before it must be ready. */
  function unlockedThrough() {
    let i = 0;
    while (i < STEPS.length - 1 && READY[STEPS[i]]()) i++;
    return i;
  }
  const isLocked = (name) => STEPS.indexOf(name) > unlockedThrough();

  function lockSteps() {
    const max = unlockedThrough();
    const at  = STEPS.indexOf(screen);
    STEPS.forEach((s, i) => {
      const b = $('step-' + s);
      if (!b) return;
      b.classList.toggle('locked', i > max);
      b.classList.toggle('on', s === screen);
      // `.done` = behind him AND actually finished. The origin tile is step 5's evidence, not a tick
      // on step 5 itself, so a step is only `done` once he has moved PAST it.
      b.classList.toggle('done', i < at && READY[s]());
    });
  }

  /** The router. The SWEEP is not a pane — it IS the stage (canvas + both rails). The other five
   *  screens are panes that cover the stage, and they hide the rails (style.css gives us
   *  `.shell.no-left` / `.no-right` for exactly this). */
  function show(name) {
    if (STEPS.indexOf(name) < 0) return;
    if (isLocked(name)) { toast('Finish the step before it first.', 'bad'); return; }
    screen = name;
    Help.hide();                     // a bubble anchored to a `?` on the screen we are leaving
    // The sweep has NO pane — it is the stage itself. Every other step does.
    for (const s of STEPS) {
      const pane = $('screen-' + s);
      if (pane) pane.classList.toggle('on', s === name);
    }
    lockSteps();

    const sweeping = (name === 'sweep');
    el.app.classList.toggle('no-left', !sweeping);
    el.app.classList.toggle('no-right', !sweeping);
    // The stage OVERLAYS (banner, A/E/Space cluster, camera + undo) sit at z-index 4, above the
    // panes' z-index 3. Hiding the rails is not enough: without this they float on top of Load /
    // Range / Screen / Place / Mosaic, obscure the text and swallow clicks in the corners.
    if (el.stage) el.stage.classList.toggle('no-overlays', !sweeping);
    if (sweeping) {
      mountViewer();
      if (viewerOk) Viewer.resize();
      refresh();
    }
    if (name === 'mosaic') renderProvenance();
  }

  function mountViewer() {
    if (viewerOk || !session) return;
    try {
      Viewer.mount(el.canvas, {
        apiBase: API(),
        toneVersion: cacheKey,
        // 🔴 bindKeys:false. The viewer would otherwise bind its OWN window keydown for F/0/D/G/Esc/
        // arrows, and we would double-handle every one of them (D would toggle Difference twice and
        // land back where it started). We own the keyboard; we DELEGATE those keys to
        // Viewer.handleKey(e) from onKeyDown, which is the hook viewer.js documents for this.
        bindKeys: false,

        // ONE undo entry per drag, pushed on the gesture's start (the bench's rule).
        onDragStart: (t) => { dragTag = t; pushUndo('drag:' + t); },

        onDragMove: (t, x, y) => {
          if (dragTag !== t) { dragTag = t; pushUndo('drag:' + t); }   // belt and braces
          const tile = tileOf(t);
          if (tile && tile.state !== 'excluded') { tile.x = x; tile.y = y; }
          clearTimeout(scoreTimer);
          scoreTimer = setTimeout(async () => {
            try {
              const r = await scoreAt(t, x, y);
              if (!r) return;
              if (r.refused) { el.evNcc.textContent = 'refused'; el.evNcc.className = 'v big na'; return; }
              // `ncc: null` = NOT MEASURABLE (too little overlap). The honest answer is "—".
              // NEVER print 0.0 for it: 0.0 is a measurement, and this is the absence of one.
              setNcc(r.ncc);
              el.evNpix.textContent = r.npix ? (r.npix / 1e3).toFixed(0) + ' k' : '—';
              el.evMargin.textContent = '—';   // a drag has no ranked list, so there is no margin.
            } catch (_) { /* transient */ }
          }, SCORE_DEBOUNCE);
        },

        // move() first, THEN clear dragTag — otherwise the drop pushes a second undo entry on top of
        // the one the drag start already pushed.
        onDragEnd: (t, x, y) => { move(t, x, y); dragTag = null; },

        // A click on a ranked ghost box == "did you mean here?" -> the SAME path as the rail's list.
        // (It used to be its own three lines, and they lost the evidence — see `pickAlternative`.)
        onAlternativePick: (t, c) => pickAlternative(t, c),

        /* 🔴 `Esc` MUST NOT KILL THE SWEEP. viewer.js's Escape clears the marquee selection and the
         * alternative ghosts, and reports it as `onSelect(null)` — and this used to pass that
         * straight into `setCursor(null)`. The cursor IS the tile under judgement, so Esc left the
         * sweep with no cursor at all: `advance()`, `anchor()` and `exclude()` all begin with
         * `if (cursor === null) return`, so Space / A / E then did NOTHING, silently, and the only
         * way back was to click a trial in the queue. Driven on the real app: Esc, then three
         * Spaces, and the status bar read `trial —` with the sweep frozen. It also wrote
         * `cursor: null` into the project file, so a RESUME landed back at the top of the run.
         * Esc deselects. It does not abandon the tile you are judging. */
        onSelect: (t) => { if (t !== null) setCursor(t); },
        onFadeEnd: () => {},
        onError: (t, err) => toast('Tile ' + t + ': ' + err, 'bad'),
      });
      viewerOk = true;
      Viewer.setTiles(doc.tiles);
      Viewer.setCursor(cursor);
      Viewer.fit();
      setInterval(() => {
        if (screen !== 'sweep' || !viewerOk) return;
        try {
          const s = Viewer.stats();
          if (s && el.cbFps && s.ms !== undefined) {
            el.cbFps.textContent = s.ms.toFixed(1) + ' ms/frame · ' + (s.fps || 0) + ' fps';
          }
        } catch (_) {}
      }, 1000);
    } catch (e) {
      toast('Viewer failed to mount: ' + e.message, 'bad');
    }
  }

  // ---- 1 · LOAD — one question: which directory? ------------------------------------------
  async function openDir() {
    const dir = el.inDatadir.value.trim();
    if (!dir) { toast('Pick a directory first.', 'bad'); return; }
    el.openProgress.classList.remove('hidden');
    try {
      const j = await POST('/api/session/open', { data_dir: dir, project_path: null });
      await pollJob(j.job_id, (job) => {
        el.openFill.style.width = (job.pct || 0) + '%';
        el.openMsg.textContent = (job.phase || '') + ' — ' + (job.message || '');
      });
      await loadSession();          // -> Range. The question this screen asks has been answered.
      el.openProgress.classList.add('hidden');
    } catch (e) {
      el.openProgress.classList.add('hidden');
      toast('Open failed: ' + e.message, 'bad');
    }
  }

  /** `{silent: true}` = load the SESSION (pixels, tone, blank scan, trial list) but do not navigate
   *  and do not announce. The resume path uses it: it needs the session, and then it replaces the
   *  fresh document this builds with the one from the project file. */
  async function loadSession(opts) {
    session = await GET('/api/session');
    toneVersion = (session.tone && session.tone.version) || 1;
    cacheKey = bustKey();
    doc = newDoc();
    seqCounter = 0;
    undoStack.length = 0; redoStack.length = 0;
    evidence = {};
    cursor = session.run.trials.length ? session.run.trials[0] : null;
    doc.cursor = cursor;

    /* 🔴 A RELOAD IS A NEW SET OF PIXELS. The viewer's `bitmaps` Map is keyed on the trial number
     * alone and was cleared ONLY inside setToneVersion() — which early-returns when the version has
     * not changed, and after a reload the version is 1 and it was already 1. So the old ImageBitmaps
     * survived a re-open of a DIFFERENT directory. Push the new session's cache key in (it always
     * differs — the nonce is fresh) and re-seed the tiles, unconditionally. */
    if (viewerOk) {
      Viewer.setToneVersion(cacheKey);
      Viewer.setTiles(doc.tiles);
      Viewer.setCursor(cursor);
      Viewer.fit();
    }

    /* ⛔ THE NUMBERS ONLY. There is no "312 usable of 338 (26 thrown out)" line any more, because
     * THE APP EXCLUDES NOTHING AT LOAD (his ruling, 2026-07-14). `run.n` is simply the trial count.
     * The DETECTION's reasoning — a measured `why` string — goes behind the `?`, not on the page. */
    el.hdrDataset.textContent = session.dataset + ' · ' + session.run.n + ' tiles';
    el.runRange.textContent   = session.run.lo + '–' + session.run.hi;
    el.runN.textContent       = session.run.n;
    // The TOOLTIP is where the long version belongs — that is the whole point of moving it off the
    // page. Prefer `why_detail` (the full reasoning) and fall back to the terse `why`.
    Help.set(el.helpRun, session.run.why_detail || session.run.why || '');

    const ps = session.pass_split || {};
    el.splitValue.textContent = ps.value ?? '—';
    el.splitN1.textContent    = ps.n_pass1 ?? '—';
    el.splitN2.textContent    = ps.n_pass2 ?? '—';
    Help.set(el.helpSplit, ps.why_detail || ps.why || '');

    el.inLo.value = session.run.lo; el.inHi.value = session.run.hi;
    el.inSplit.value = ps.value ?? '';
    el.cfgPassSplit.value = ps.value ?? '';
    el.inBasename.value = session.dataset + '_mosaic';
    if (session.tone) { el.toneLo.value = fmt(session.tone.lo, 1); el.toneHi.value = fmt(session.tone.hi, 1); }

    renderSheet();
    renderBlankScan();
    // renderGpu() is ASYNC. `gpu` must be known before renderBuildCost() reads it, or the Place
    // screen prints "No GPU" on a machine that has one — a false statement in the one line whose
    // whole job is an honest cost report. (renderGpu calls renderBuildCost on settle.)
    renderGpu();
    refresh();
    if (opts && opts.silent) return;
    // ⭐ Opening a directory lands him on RANGE, not back on Load. Load asks ONE question and it
    //    has been answered. (Every path in — Open, Apply, a page reload, `--data-dir` — comes here.)
    show('range');
    toast('Loaded ' + session.run.n + ' tiles.', 'ok');
  }

  async function renderGpu() {
    try { gpu = await GET('/api/gpu'); } catch (_) { gpu = session && session.gpu; }
    if (!gpu) return;
    el.gpuBadge.textContent = gpu.available ? ('GPU · ' + (gpu.name || gpu.backend)) : 'CPU only';
    el.gpuBadge.className = 'badge ' + (gpu.available ? 'gpu' : 'unplaced');
    // ⭐ SAY *WHY* THERE IS NO GPU. Being honest about the bill (the note) and silent about the bug
    //    is how "your CUDA DLLs are in a directory CuPy cannot see" becomes a permanent 8-minute
    //    build that nobody ever diagnoses.
    el.gpuBadge.title = (gpu.note || '') + (gpu.reason ? '\n\nWHY: ' + gpu.reason : '');
    renderBuildCost();   // only now is `gpu` actually known — see the note at the call site.
  }

  /** No GPU? RUN ANYWAY, and state the real cost. Never degrade the result silently.
   *  ⚠️ A COST, not a warning — style.css makes this a `.muted` line and the HTML gives it no
   *     `.warn`. One clause. The `why` (a CUDA DLL path problem is FIXABLE, and is not the same
   *     thing as "no card") lives on the GPU badge's tooltip — see `renderGpu`. */
  function renderBuildCost() {
    if (!el.buildCost) return;
    const on = gpu && gpu.available;
    // ⚠️ The `?`'s body is set through `Help.set` (a property), NEVER interpolated into an HTML
    //    attribute: `gpu.reason` is a backend string and a single `"` in it would break out of
    //    data-help and mangle the page.
    el.buildCost.innerHTML = (on
      ? 'GPU · ' + (gpu.name || gpu.backend) + ' — ~3 min cold, ~25 s cached.'
      : '<b>No GPU</b> — ~8–10 min. The result is identical.') +
      '<span class="help" data-help=""></span>';
    Help.set(el.buildCost.querySelector('.help'), on
      ? 'For a 312-tile build. The sweep itself is unaffected.'
      : 'The build runs anyway and the answer is the SAME; it just takes ~8-10 min instead of ~3.\n\n' +
        'The sweep itself is only 1.46x slower without a GPU (1,562 vs 1,068 ms per Space), because ' +
        'the exact-NCC scoring runs on the CPU either way.\n\n' +
        (gpu && gpu.reason ? 'why: ' + gpu.reason + '\n\n' : '') +
        'If this machine DOES have an NVIDIA card, this is a CUDA DLL-path problem, not a missing ' +
        'GPU — and it is fixable.');
    Help.reindex(el.buildCost);
  }

  async function overrideRun() {
    try {
      const body = { lo: +el.inLo.value, hi: +el.inHi.value, pass_split: +el.inSplit.value };
      // ⚠️ DESTRUCTIVE, and he has work on the canvas. Say what dies, in one line, and let him stop.
      if (anyPlaced()) {
        if (!confirm('Reloading discards the build and every position in it. Continue?')) return;
      }
      const j = await PATCH('/api/session/run', body);
      await pollJob(j.job_id, (job) => { el.openMsg.textContent = job.phase + ' — ' + (job.message || ''); });
      await loadSession();     // -> Range
    } catch (e) { toast('Reload failed: ' + e.message, 'bad'); }
  }

  // ---- 2 · SCREEN -----------------------------------------------------------------------
  /** What the MEASURE proposed — never what the matcher currently refuses. The two diverge the
   *  moment the user overrules one, and this screen must go on showing every frame it recommended. */
  const scannedBlanks = () => {
    const b = session && session.blank;
    if (!b) return [];
    return (b.scanned || b.blank || []).slice();
  };

  /** ⚠️ `#blank-list` is `class="facts"` in the HTML, so each frame must be a `.fact` — that is the
   *  CSS contract (`.fact .k` / `.fact .v`). It used to emit `.card`, which style.css does not
   *  define at all, and the whole list would have rendered unstyled. */
  function renderBlankScan() {
    const b = session.blank;
    if (!b) {
      el.blankList.innerHTML = '<div class="muted">No scan.</div>';
      el.blankN.textContent = '0';
      el.blankThr.textContent = '—';
      Help.set(el.helpBlank, '');
      return;
    }
    const scan = scannedBlanks();
    el.blankN.textContent   = scan.length;
    el.blankThr.textContent = fmt(b.threshold, 2);
    // The measure, where the threshold came from, and how little margin it has — all of it is
    // background, so all of it is a hover. (his ruling: a tool, not an explainer.)
    Help.set(el.helpBlank, [b.measure, b.threshold_source,
                            b.margin_warning_detail || b.margin_warning]
      .filter(Boolean).join('\n\n'));

    el.blankList.innerHTML = '';
    if (!scan.length) {
      el.blankList.innerHTML = '<div class="muted">Nothing recommended.</div>';
      return;
    }
    for (const t of scan) {
      const tex = b.texture ? b.texture[K(t)] : null;
      const d = document.createElement('div');
      d.className = 'fact';
      /* 🔴 NOT `checked`. See the note in index.html: a pre-ticked box under a primary button
       * reading "Exclude the ticked" IS an auto-exclude, and on this dataset it threw away four
       * tiles the user himself hand-anchored into the ground truth. THE SCAN RECOMMENDS. HE TICKS. */
      d.innerHTML =
        '<div class="k">trial ' + t + '<span class="spacer"></span></div>' +
        '<img src="' + API() + '/api/tile/' + t + '.png?v=' + cacheKey + '" alt="trial ' + t + '" ' +
        'style="width:100%;aspect-ratio:1;object-fit:cover;image-rendering:pixelated;' +
        'border-radius:4px;margin:4px 0">' +
        '<div class="muted mono" style="font-size:11px">texture ' + fmt(tex, 1) + '</div>' +
        '<label style="display:flex;gap:5px;align-items:center;cursor:pointer;font-size:12px;' +
        'margin-top:4px"><input type="checkbox" class="blank-chk" data-trial="' + t + '">exclude</label>' +
        '<label style="display:flex;gap:5px;align-items:center;cursor:pointer;font-size:12px" ' +
        'title="Lift the matcher&#39;s refusal on this frame. Only if you can see real tissue.">' +
        '<input type="checkbox" class="blank-score" data-trial="' + t + '">score it</label>';
      el.blankList.appendChild(d);
    }
    // The refusal override is a decision, so it reaches the server the moment it is made — not only
    // if the user happens to press Apply. See `putRefusals`.
    el.blankList.querySelectorAll('.blank-score').forEach((c) => { c.onchange = putRefusals; });
  }

  /** ⭐ THE MATCHER'S REFUSAL LIST — the human's, not the measure's.
   *
   *  API.md §9.1: "the `blank` list is what the matcher refuses, regardless of whether the user
   *  excluded it", and PLAN.md is explicit that a blank frame must be REFUSED, not scored. That is
   *  the SAFE default and it stays the default. But the measure has **no margin** here — over
   *  11-348 it names 34/55/56/127, and three of those are ordinary, correctly-placed pass-1 tiles —
   *  so the human must be able to overrule it, per frame, having LOOKED at the frame.
   *
   *  🔴 AND THE OVERRULE HAS TO REACH THE SERVER ON EVERY PATH OUT OF THIS SCREEN. It used to reach
   *  it only through `applyBlank()`; "Next — build →" walked straight past, so the raw scan list
   *  governed `engine._refusal` (Space and snap dead on those trials) and `engine._blank_anchors`
   *  (their pixels dropped from EVERY composite) for the whole session, with no UI trace and no way
   *  to overrule. So: this fires on any tick, on Apply, and on the way to Build. */
  async function putRefusals() {
    if (!session || !session.blank) return;
    const scan = scannedBlanks();
    const overruled = [];
    (el.blankList ? el.blankList.querySelectorAll('.blank-score') : []).forEach((c) => {
      if (c.checked) overruled.push(+c.dataset.trial);
    });
    const refuse = scan.filter((t) => !overruled.includes(t));
    try {
      const b = await PUT('/api/scan/blank', { blank: refuse });
      session.blank = b;
      if (doc && doc.blank_scan) {
        doc.blank_scan.blank = b.blank;                  // what the MATCHER refuses
        doc.blank_scan.scanned = scan;                   // what the MEASURE said (never rewritten)
        doc.blank_scan.overruled_by_user = overruled;    // and what the human overruled, on the record
      }
      if (overruled.length) toast('The matcher will now score ' + overruled.join(', ') + '.', 'ok');
    } catch (e) {
      toast('Refusal list failed: ' + e.message, 'bad');
    }
  }

  /** The contact sheet: ONE sprite sheet, cells positioned by background-position (style.css's
   *  `.sheet .cell`). Never scale a cell — the sheet is 1:1. */
  async function renderSheet() {
    try {
      const idx = await GET('/api/thumbs.json');
      const url = API() + '/api/thumbs.png?v=' + cacheKey;
      const blanks = new Set((session.blank && session.blank.blank) || []);
      const cell = idx.cell, grid = idx.grid;
      const frag = document.createDocumentFragment();
      idx.trials.forEach((t, i) => {
        const c = document.createElement('div');
        c.className = 'cell' + (blanks.has(t) ? ' blank' : '');
        c.style.width = cell + 'px';
        c.style.backgroundImage = 'url(' + url + ')';
        c.style.backgroundPosition = '-' + (i % grid) * cell + 'px -' + Math.floor(i / grid) * cell + 'px';
        c.title = 'trial ' + t + (blanks.has(t) ? ' — scanned BLANK (a recommendation)' : '');
        c.innerHTML = '<span class="t">' + t + '</span>';
        c.onclick = () => { setCursor(t); show('sweep'); };
        frag.appendChild(c);
      });
      el.sheet.innerHTML = '';
      el.sheet.appendChild(frag);
    } catch (e) { el.sheet.innerHTML = '<div class="muted">no contact sheet: ' + e.message + '</div>'; }
  }
  /** "Exclude the ticked frames." ⚠️ THE TICK IS THE ONLY THING THAT EXCLUDES. Nothing here reads a
   *  measure and decides for the user — and the boxes start EMPTY, so pressing this with nothing
   *  ticked excludes nothing, which is exactly what it should do.
   *
   *  It no longer touches the refusal list: that is `putRefusals`' job, driven by its own
   *  per-frame tick. Conflating the two meant "I don't want to exclude these" was silently read as
   *  "…and score all of them", which would have lifted the refusal on trial 127 — the one frame in
   *  the list that genuinely misleads the matcher, by 679 px at NCC 0.66. */
  async function applyBlank() {
    const chks = el.blankList.querySelectorAll('.blank-chk');
    pushUndo('blank-apply');
    let n = 0;
    let minSeq = Infinity, wasAnchor = null;
    chks.forEach((c) => {
      if (!c.checked) return;
      const t = +c.dataset.trial;
      const tl = tileOf(t);
      if (!tl || tl.state === 'excluded') return;
      // Excluding an ANCHOR removes its pixels from the composite — every tile judged after it was
      // matched against a field that contained them. Same rule as `exclude()`.
      if (tl.state === 'anchored' && tl.seq !== undefined && tl.seq < minSeq) {
        minSeq = tl.seq; wasAnchor = t;
      }
      if (tl.x !== null) tl.last_xy = [tl.x, tl.y];
      setState(t, 'excluded');
      tl.excluded = true;
      tl.unusable_reason = 'blank';
      tl.excluded_reason = 'measured blank — recommended by the scan and ticked by the user';
      n++;
    });
    const nStale = isFinite(minSeq) ? markStaleAfter(minSeq, wasAnchor, false) : 0;

    await putRefusals();     // the refusal list follows its OWN ticks, on every path out of here

    const g = recomputeGaps();
    doc.unusable_tiles = trials().filter((t) => tileOf(t).state === 'excluded');
    if (doc.blank_scan) doc.blank_scan.accepted = true;
    if (cursor !== null && tileOf(cursor).state === 'excluded') setCursor(nextTrial(cursor));
    refresh(); autosaveNow();
    toast('Excluded ' + n + '. Gaps: ' +
          (g.length ? g.map((p) => p[0] + '→' + p[1]).join(', ') : 'none') + '.' +
          (nStale ? ' ' + nStale + ' stale.' : ''), 'ok');
  }

  // ---- 3 · BUILD ------------------------------------------------------------------------
  function advancedConfig() {
    const num = (v) => (v === '' || v === null || v === undefined) ? null : +v;
    const c = {};
    const ps = num(el.cfgPassSplit.value); if (ps !== null) c.pass_split = ps;
    const an = num(el.cfgAnchorNcc.value); if (an !== null) c.anchor_ncc = an;
    const sp = num(el.cfgSplitPx.value);   if (sp !== null) c.split_px = sp;
    const lk = num(el.cfgLook.value);      if (lk !== null) c.look = lk;
    const ms = num(el.cfgMinSide.value);   if (ms !== null) c.min_side = ms;
    const t27 = {};
    const cf = num(el.cfgT27Conf.value);    if (cf !== null) t27.conf = cf;
    const rc = num(el.cfgT27Runconf.value); if (rc !== null) t27.run_conf = rc;
    if (Object.keys(t27).length) c.t27 = t27;
    // pass_split alone (= the DETECTED value) is not an override worth sending as a config.
    const keys = Object.keys(c);
    if (keys.length === 1 && keys[0] === 'pass_split' &&
        session.pass_split && c.pass_split === session.pass_split.value) return null;
    return keys.length ? c : null;
  }

  /** The trials the solver should actually be given: everything the user has NOT excluded.
   *  ⚠️ `/api/build/start` used to be handed the session's full 312 regardless — so pressing `E` and
   *  then "re-solve" re-solved the IDENTICAL problem and put the excluded frame straight back into
   *  the chain. The exclusion the app invites you to make has to reach the solver. */
  function activeTrials() {
    return trials().filter((t) => tileOf(t).state !== 'excluded');
  }

  /** ⚠️ IS THE BUILD STILL A BUILD OF *THIS* PROBLEM? Excluding a tile removes a frame from the
   *  solver's input and opens a gap in acquisition order — and the serpentine one-step prior does
   *  NOT hold across a gap. The positions either side of an excluded tile were solved THROUGH it.
   *  Nothing surfaced this before: the backend has the machinery (project.mark_stale_if_input_changed)
   *  but was never given `build.trials` to compare against, and nothing in this file ever read the
   *  answer. -> {stale, reason} */
  function buildStale() {
    const b = doc && doc.build;
    if (!b) return { stale: false, reason: null };
    if (!b.trials) {
      return { stale: true, reason: 'This build does not record which trials it was solved on, so ' +
                                    'it cannot be checked against the current input. Treat it as stale.' };
    }
    const now = activeTrials();
    const was = b.trials.map(Number);
    const dropped = was.filter((t) => !now.includes(t));
    const added = now.filter((t) => !was.includes(t));
    if (!dropped.length && !added.length) return { stale: false, reason: null };
    const bits = [];
    if (dropped.length) bits.push('<b>' + dropped.length + '</b> excluded since the build (' +
      dropped.slice(0, 12).join(', ') + (dropped.length > 12 ? ' …' : '') + ')');
    if (added.length) bits.push('<b>' + added.length + '</b> un-excluded (' +
      added.slice(0, 12).join(', ') + ')');
    return { stale: true, reason: bits.join(', ') + '.' };
  }

  /** ⚠️⚠️ A LIVE WARNING ABOUT THE CURRENT STATE, AND IT STAYS ON THE PAGE. He excluded a tile; the
   *  positions were solved on a DIFFERENT input, and the tiles either side of an excluded one were
   *  placed *through* it. He must re-solve, or knowingly not. Its BACKGROUND is on the `?`; the
   *  fact that it is firing is not negotiable. */
  function renderBuildStale() {
    if (!el.buildStale) return;
    const { stale, reason } = buildStale();
    el.buildStale.classList.toggle('hidden', !stale);
    if (!stale) return;
    el.buildStale.className = 'warn loud';
    el.buildStale.innerHTML = '<div><b>THE BUILD IS STALE.</b> ' + reason +
      '<span class="help" data-help="The build was solved on a different input. The tiles either ' +
      'side of an excluded one were placed THROUGH it, and the serpentine one-step prior does not ' +
      'hold across the gap that just opened.&#10;&#10;Re-solve, or place the affected tiles against ' +
      'the anchor field yourself. Do not keep these positions as if nothing had changed."></span> ' +
      '<button class="btn sm" id="btn-restale">Re-solve</button></div>';
    const b = $('btn-restale');
    if (b) b.onclick = () => show('place');
    Help.reindex(el.buildStale);
  }

  async function startBuild() {
    try {
      const j = await POST('/api/build/start', {
        config: advancedConfig(),
        use_cache: !!el.inUsecache.checked,
        trials: activeTrials(),      // ⭐ the problem the DOCUMENT poses, not the session's default
      });
      buildJobId = j.job_id;
      el.buildProgress.classList.remove('hidden');
      el.btnBuild.disabled = true;
      el.btnBuildCancel.classList.remove('hidden');
      const job = await pollJob(j.job_id, (job) => {
        el.buildFill.style.width = (job.pct || 0) + '%';
        el.buildPhase.textContent = job.phase || '';
        el.buildMsg.textContent = job.message || '';
        el.buildEta.textContent = job.eta_s ? ('~' + Math.round(job.eta_s) + ' s left') : '';
        el.buildLog.textContent = (job.log_tail || []).slice(-8).join('\n');
      });
      buildJobId = null;
      el.btnBuild.disabled = false;
      el.btnBuildCancel.classList.add('hidden');
      if (job.state !== 'done') { toast('Build ' + job.state + '.', 'bad'); return; }
      await loadBuildResult();
    } catch (e) {
      buildJobId = null;
      el.btnBuild.disabled = false;
      el.btnBuildCancel.classList.add('hidden');
      toast('Build failed: ' + e.message, 'bad');
    }
  }

  async function cancelBuild() {
    if (!buildJobId) return;
    try { await POST('/api/jobs/' + buildJobId + '/cancel', {}); toast('Cancelling…'); }
    catch (e) { toast('Cancel failed: ' + e.message, 'bad'); }
  }

  const median = (a) => {
    if (!a.length) return 0;
    const s = a.slice().sort((x, y) => x - y);
    const h = s.length >> 1;
    return s.length % 2 ? s[h] : 0.5 * (s[h - 1] + s[h]);
  };

  /** Seed the document from the build. Every placed tile becomes `unverified` — PLACED BUT NOT
   *  CERTIFIED. Nothing is anchored by a machine. The human's `A` is the only thing that anchors.
   *
   *  🔴🔴 A RE-SOLVE MUST NOT DESTROY THE HUMAN'S WORK, AND IT USED TO — SILENTLY, THEN AUTOSAVE
   *  OVER THE RECOVERY FILE. `setState` was called unconditionally on every non-excluded tile, so
   *  every `anchored` tile reverted to `unverified` at t33's position. And the app ROUTES THE USER
   *  INTO THIS: excluding a tile mid-sweep raises "⚠️ THE BATCH BUILD IS STALE … Re-solve", whose
   *  button opens the Build screen. Sweep 150 tiles, hand-correct the aliases (the 797 px fix on
   *  119, the 2,969 px fix on 128), press `E` on one bad frame, take the app's own advice — and all
   *  150 judgements, including the three catastrophic corrections, are gone, with `autosaveNow()`
   *  writing the wiped document straight over the crash-recovery file.
   *
   *  ⇒ A TILE THE HUMAN HAS JUDGED (`anchored`) OR PLACED (`human`) IS NOT THE MACHINE'S TO MOVE.
   *    We keep it, and we seed everything else AROUND it.
   *
   *  ⚠️ AND THE TWO FRAMES MUST BE MADE ONE. A layout is defined only up to a translation: t33's
   *    origin is its own, the document's is `origin_trial` at (0,0). Seeding raw build positions
   *    into a document that already holds human positions would mix two frames — every seeded tile
   *    offset by a constant vector from every human one, which looks exactly like a solver that has
   *    gone mad. So the build is TRANSLATED onto the human field, by the **median** offset over the
   *    protected tiles (a median, not a mean: a tile the human corrected *because t33 was wrong* is
   *    precisely an outlier, and one 2,969 px correction would drag a mean into nonsense). */
  async function loadBuildResult() {
    const r = await GET('/api/build/result');
    pushUndo('seed');

    const isHumans = (tl) => tl.state !== 'excluded' && tl.x !== null &&
                             (tl.state === 'anchored' || tl.human === true);
    const keepT = trials().filter((t) => isHumans(tileOf(t)));

    let ox = 0, oy = 0;
    if (keepT.length) {
      const dxs = [], dys = [];
      for (const t of keepT) {
        const p = r.positions[K(t)];
        if (!p) continue;
        dxs.push(tileOf(t).x - p[0]);
        dys.push(tileOf(t).y - p[1]);
      }
      if (!dxs.length) {
        // Not one of the human's tiles is in the build. There is no measurable translation between
        // the two frames, so ANY seed would be a guess dressed as an answer. Refuse.
        toast('This build places none of your ' + keepT.length + ' hand-placed tiles — the frames ' +
              'cannot be tied together. Nothing seeded.', 'bad');
        return;
      }
      ox = median(dxs); oy = median(dys);
    }
    const P = {};
    for (const k of Object.keys(r.positions || {})) {
      P[k] = [r.positions[k][0] + ox, r.positions[k][1] + oy];
    }

    let n = 0, kept = 0;
    for (const t of trials()) {
      const tl = tileOf(t);
      if (tl.state === 'excluded') continue;
      const p = P[K(t)];
      if (!p) { tl.machine = null; continue; }
      tl.machine = [p[0], p[1]];        // what the solver said. A FACT, and it is recorded either way.
      if (isHumans(tl)) {
        // The human put it here. Keep the position, keep the state, keep the judgement. All the
        // machine gets to do is tell us how far apart the two of you are.
        tl.moved_px = Math.hypot(tl.x - p[0], tl.y - p[1]);
        kept++;
        continue;
      }
      tl.moved_px = 0;
      setState(t, 'unverified', p[0], p[1]);
      tl.source = 't33 build, not yet judged';
      tl.human = false;
      const pt = r.per_tile && r.per_tile[K(t)];
      if (pt) { tl.ncc = pt.anchor_ncc ?? null; tl.margin = pt.run_margin ?? null; }
      n++;
    }
    doc.build = {
      build_id: r.build_id, method: 't33', created: r.created, seconds: r.seconds,
      gpu: r.gpu, n_placed: r.n_placed,
      config: (r.info && r.info.config) || {},
      // ⚠️ THE TRANSLATED positions — the same frame as `tiles[*].x/y` and `tiles[*].machine`, so
      // `moved_px` keeps meaning what it says and `exportDoc`'s normalisation shifts all three by
      // one vector. Storing t33's raw frame here while the tiles live in the human's would make
      // every QC number in the export wrong by a constant.
      positions: P,
      seed_translation: [ox, oy],
      // ⭐ WHAT THE SOLVER WAS ACTUALLY GIVEN. Without these two, `project.mark_stale_if_input_changed`
      // compares the current trial list WITH ITSELF and can never fire — so excluding a tile mid-sweep
      // left the app happily using positions that were solved through it, and exporting them as
      // ground truth with `stale: false`. The backend now refuses to guess: no `trials` = stale.
      trials: (r.trials || activeTrials()).map(Number),
      gaps: (r.gaps || recomputeGaps()).map((g) => g.slice()),
      stale: false, stale_reason: null,
    };
    doc.provenance.workflow = 'machine-seeded verification sweep';
    doc.provenance.seeded_from = { method: 't33', build_id: r.build_id,
                                   config: (r.info && r.info.config) || {} };
    doc.provenance.independent_of_method = false;
    doc.provenance.warning =
      'NOT AN INDEPENDENT GROUND TRUTH. Every position here started as t33\'s output and was ' +
      'confirmed or corrected by a human who could see it. It MUST NEVER be used to score t33 or any ' +
      'method derived from it — the score would be 100 % by construction. This project has already ' +
      'destroyed one benchmark exactly this way.';

    el.bresN.textContent = r.n_placed + ' / ' + trials().length;
    el.bresUnplaced.textContent = (r.unplaced && r.unplaced.length)
      ? ('unplaced: ' + r.unplaced.join(', ') + ' — in the rescue queue')
      : 'every tile placed';
    el.bresS.textContent = Math.round(r.seconds) + ' s';
    el.bresGpu.textContent = r.gpu ? 'on the GPU' : 'CPU only';
    el.bresId.textContent = r.build_id;
    renderWorklist(r);
    el.buildResult.classList.remove('hidden');
    refresh(); autosaveNow();
    if (kept) {
      // ⚠️ HIS WORK SURVIVED, and he needs to know it did — a re-solve used to silently wipe it.
      toast('Seeded ' + n + '. ' + kept + ' of your placements kept (build shifted ' +
            fmt(ox, 1) + ', ' + fmt(oy, 1) + ' px onto your field).', 'ok');
    } else {
      toast('Seeded ' + n + ' tiles. Nothing is anchored — that is your job.', 'ok');
    }
  }

  /** "Go look here first" — sorted by anchor_residual_px. NOT a verdict, and it is BLIND to pass 1.
   *  ⛔ It is deliberately NOT built on quality.score_positions: on the ground-truth-perfect 312/312
   *     build that flags 11 tiles and ALL 11 ARE FALSE POSITIVES (precision 0/11). */
  /** ⚠️ `#bres-worklist` has no class of its own, so we pick from style.css's vocabulary: `.list` /
   *  `.item` (a clickable trial row — `.t`, `.n`, `.spacer`). The old code emitted `<table class=
   *  "tbl">`, and `.tbl` DOES NOT EXIST in style.css — the whole worklist rendered unstyled. */
  function renderWorklist(r) {
    const rows = [];
    for (const t of trials()) {
      const pt = r.per_tile && r.per_tile[K(t)];
      if (!pt) continue;
      rows.push({ t, res: pt.anchor_residual_px, ncc: pt.anchor_ncc, m: pt.run_margin, pass: pt.pass });
    }
    const withRes = rows.filter((x) => x.res != null).sort((a, b) => b.res - a.res).slice(0, 12);
    const thin = rows.filter((x) => x.m != null && x.m < THIN_MARGIN);
    const noConf = rows.filter((x) => x.pass === 1).length;

    const bad = (on) => on ? ' style="color:var(--bad)"' : '';
    let h = '<div class="list">';
    for (const x of withRes) {
      h += '<div class="item go" data-trial="' + x.t + '">' +
           '<span class="t">' + x.t + '</span>' +
           '<span class="n"' + bad(x.res > 20) + '>' + fmt(x.res, 1) + ' px</span>' +
           '<span class="spacer"></span>' +
           '<span class="n">ncc ' + fmt(x.ncc, 3) + '</span>' +
           '<span class="n"' + bad(x.m != null && x.m < THIN_MARGIN) + '>m ' + fmt(x.m, 3) + '</span>' +
           '</div>';
    }
    if (thin.length) {
      h += '<div class="item"><span class="t"' + bad(true) + '>thin</span>' +
           '<span class="n">' + thin.map((x) => x.t + ' (' + fmt(x.m, 3) + ')').join(', ') + '</span>' +
           '</div>';
    }
    h += '</div>';
    if (!withRes.length && !thin.length) h = '<div class="muted">Nothing flagged.</div>';

    /* ⚠️ A LIVE WARNING ABOUT THE BUILD IN FRONT OF HIM: N tiles CANNOT appear on this list at all,
     * so the absence of a warning here is not a clean bill of health. That is a fact about the
     * current result, not a lecture — it stays. */
    h += '<div class="warn loud"><div><b>' + noConf + ' pass-1 tiles have no per-tile confidence.</b> ' +
         'They cannot appear here at all.' +
         '<span class="help" data-help="t27\'s info is aggregate-only, so no pass-1 tile can be ' +
         'scored individually — and the WORST tile in the shipped 312/312 build (trial 127, 9.94 px ' +
         'out) is one of them.&#10;&#10;The absence of a warning is not a clean bill of health. ' +
         'Sweep them exactly like the rest."></span></div></div>';

    el.bresWorklist.innerHTML = h;
    el.bresWorklist.querySelectorAll('.item.go').forEach((b) => {
      b.onclick = () => { setCursor(+b.dataset.trial); show('sweep'); };
    });
    Help.reindex(el.bresWorklist);
  }

  /** "Skip — place from scratch."
   *
   *  🔴 THIS USED TO BE A WAY TO LAUNDER A MACHINE BUILD INTO AN "INDEPENDENT GROUND TRUTH."
   *  It nulled `build`, nulled `seeded_from`, set `independent_of_method: true` and deleted the
   *  warning — and **did not touch a single tile.** Every tile kept t33's position and its `machine`
   *  answer. The step-3 breadcrumb is clickable at any time, and this button reads like "don't run
   *  another build", so the path was: build 312/312 → seed → sweep → click "3 Build" → click "Skip"
   *  → Export a file that says, in writing, that it is a hand-authored independent truth. Score t33
   *  against it and it gets ~100 % BY CONSTRUCTION. That is the exact mechanism that already
   *  destroyed one benchmark in this project.
   *
   *  So: if anything in the document came from a machine, this is DESTRUCTIVE or it is nothing.
   *  (The backend now derives the stamp from the tiles' history anyway — `project.machine_evidence`
   *  — so a laundered document would be re-stamped on save. This is the second belt, not the first.) */
  function skipBuild() {
    const seeded = trials().filter((t) => tileOf(t).machine);
    if (doc.build || seeded.length) {
      // ⚠️ DESTRUCTIVE, and the alternative is laundering a machine build into an "independent"
      //    ground truth. He must see exactly what he is about to lose.
      const ok = confirm(
        seeded.length + ' tiles still sit where the solver put them.\n\n' +
        'Placing from scratch means discarding EVERY position and the build. Otherwise this file ' +
        'would claim to be an independent ground truth while every position came from the solver — ' +
        'and it would score that solver ~100 % by construction.\n\nDiscard all ' + seeded.length +
        ' and start from scratch?');
      if (!ok) { show('place'); return; }
      pushUndo('skip-build');
      for (const t of trials()) {
        const tl = tileOf(t);
        if (tl.state === 'excluded') continue;
        setState(t, 'unplaced');
        tl.machine = null; tl.moved_px = null; tl.ncc = null; tl.margin = null;
        tl.n_anchors = null; tl.seq = undefined; tl.stale = false; tl.human = false;
        delete tl.source;
      }
      evidence = {};
      cursor = trials().length ? trials()[0] : null;
      doc.cursor = cursor;
      if (viewerOk) { Viewer.setTiles(doc.tiles); Viewer.setCursor(cursor); }
    }
    doc.build = null;
    doc.provenance.workflow = 'hand placement from scratch';
    doc.provenance.seeded_from = null;
    doc.provenance.independent_of_method = true;
    delete doc.provenance.warning;
    refresh();
    autosaveNow();
    toast('All positions discarded. This document is now independent.', 'ok');
    show('sweep');
  }

  // ---- 5 · EXPORT -----------------------------------------------------------------------
  async function doExport() {
    const outputs = [];
    if (el.outTiff.checked) outputs.push('tiff');
    if (el.outPng.checked) outputs.push('png');
    if (el.outPositions.checked) outputs.push('positions');
    if (el.outGt.checked) outputs.push('gt');
    if (el.outQc.checked) outputs.push('qc');
    if (!outputs.length) { toast('Nothing ticked.', 'bad'); return; }
    const dir = el.inExportdir.value.trim();
    if (!dir) { toast('Pick an output directory.', 'bad'); return; }
    try {
      el.exportProgress.classList.remove('hidden');
      const j = await POST('/api/export', {
        dir, basename: el.inBasename.value.trim() || (session.dataset + '_mosaic'),
        doc: exportDoc(), outputs,
        render_mode: el.inRendermode.value,
        include_unverified: !!el.inIncludeUnverified.checked,
        um_per_px: el.inUmpx.value === '' ? null : +el.inUmpx.value,
      });
      const job = await pollJob(j.job_id, (job) => {
        el.exportFill.style.width = (job.pct || 0) + '%';
        el.exportMsg.textContent = (job.phase || '') + ' — ' + (job.message || '');
      });
      el.exportProgress.classList.add('hidden');
      if (job.state !== 'done') { toast('Export ' + job.state, 'bad'); return; }
      el.exportFiles.innerHTML = ((job.result && job.result.files) || [])
        .map((f) => '<div><b>' + f.kind + '</b> ' + f.path + '  <span class="muted">' +
                    (f.bytes / 1e6).toFixed(2) + ' MB</span></div>').join('');
      toast('Exported.', 'ok');
    } catch (e) {
      el.exportProgress.classList.add('hidden');
      toast('Export failed: ' + e.message, 'bad');
    }
  }

  async function saveProject() {
    if (!doc) { toast('Nothing to save.', 'bad'); return; }
    const dflt = ((session && session.dataset) || 'project') + '.camea.json';
    let path = null;
    try {
      const r = await POST('/api/dialog/save-file', {
        title: 'Save project as', default_name: dflt,
        filters: ['Camea project (*.camea.json)'],
      });
      path = r.path;
    } catch (e) { path = prompt('Save project to:', dflt); }
    if (!path) return;
    try {
      const r = await POST('/api/project/save', { path, doc: exportDoc() });
      toast('Saved ' + r.path + ' (' + (r.bytes / 1024).toFixed(0) + ' kB)', 'ok');
    } catch (e) { toast('Save failed: ' + e.message, 'bad'); }
  }

  /** ⭐⭐ RESUME. THE PROJECT FILE IS THE APP'S ENTIRE MEMORY (his ruling, 2026-07-14): the app
   *  ships with no knowledge of any dataset and remembers nothing between runs, so this file — its
   *  exclusions, every placement, what he anchored, the cursor and the build — is the whole of it.
   *
   *  🔴 IT IS ALSO REACHABLE FROM A COLD START. `btn-load` now lives on the LOAD screen, so there
   *  may be **no session at all** when it is pressed — no pixels, no trial list, no tone window.
   *  `POST /api/project/load` tolerates that (its range guard just goes quiet), and it would hand
   *  back a document the app cannot draw a single tile of: `trials()` reads `session.run.trials`,
   *  which does not exist. So when there is no session we bootstrap one FROM THE FILE — it names its
   *  own `data_dir` — and then re-read the file, now genuinely range-guarded against the session it
   *  actually belongs to. (Pass 2's autosave once silently overwrote pass 1's GT records. That guard
   *  is why the second read is not redundant.) */
  async function loadProject() {
    let path = null;
    try {
      const r = await POST('/api/dialog/open-file', {
        title: 'Open a project', filters: ['Camea project (*.camea.json)'],
      });
      path = r.path;
    } catch (e) { path = prompt('Load project from:'); }
    if (!path) return;
    try {
      let r = await POST('/api/project/load', { path });

      if (!session) {
        const dir = r.doc && r.doc.data_dir;
        if (!dir) {
          toast('This project names no data directory — open the directory first.', 'bad');
          return;
        }
        el.openProgress.classList.remove('hidden');
        el.openMsg.textContent = 'opening ' + dir + '…';
        try {
          const j = await POST('/api/session/open', { data_dir: dir, project_path: path });
          await pollJob(j.job_id, (job) => {
            el.openFill.style.width = (job.pct || 0) + '%';
            el.openMsg.textContent = (job.phase || '') + ' — ' + (job.message || '');
          });
          await loadSession({ silent: true });      // pixels + tone + blank scan. Its fresh doc is
          r = await POST('/api/project/load', { path });   // thrown away by the adopt below.
        } finally {
          el.openProgress.classList.add('hidden');
        }
      }
      adoptDoc(r.doc, r.warnings);
    } catch (e) {
      // The range guard (409), a bad document (400) — either way, say so and change nothing.
      toast('Load refused: ' + e.message, 'bad');
    }
  }

  /** Take a loaded document as THE document, and put the user back where he left off. */
  function adoptDoc(loaded, warnings) {
    pushUndo('load');
    doc = loaded;
    evidence = {};   // a different document = a different anchor field. Nothing here describes it.
    // `state` wins if present, else derive from `status` (API.md §2 / project_schema.json).
    const S = { anchor: 'anchored', unverified: 'unverified', unplaced: 'unplaced', excluded: 'excluded' };
    for (const k of Object.keys(doc.tiles || {})) {
      const tl = doc.tiles[k];
      if (!tl.state) tl.state = S[tl.status] || 'unplaced';
    }
    cursor = doc.cursor ?? (trials().length ? trials()[0] : null);
    seqCounter = 0;
    for (const t of trials()) if (tileOf(t) && tileOf(t).seq > seqCounter) seqCounter = tileOf(t).seq;
    if (viewerOk) { Viewer.setTiles(doc.tiles); Viewer.setCursor(cursor); Viewer.fit(); }
    (warnings || []).forEach((w) => toast(w, 'warn'));
    refresh();
    const c = counts();
    toast('Resumed — ' + c.anchored + ' anchored, ' + c.excluded + ' excluded.', 'ok');
    // He was in the middle of a sweep. Put him back in it, not at the top of the wizard.
    show(anyPlaced() ? 'sweep' : 'range');
  }

  // ---- tone -----------------------------------------------------------------------------
  async function applyTone(auto) {
    try {
      const body = auto ? { auto: true } : { lo: +el.toneLo.value, hi: +el.toneHi.value };
      const t = await PUT('/api/tone', body);
      toneVersion = t.version;
      cacheKey = bustKey();
      doc.tone = t;
      el.toneLo.value = fmt(t.lo, 1); el.toneHi.value = fmt(t.hi, 1);
      // ⚠️ On a version change EVERY tile PNG must be re-requested and the baked background rebuilt.
      if (viewerOk) Viewer.setToneVersion(cacheKey);
      renderSheet();
      renderBlankScan();      // its thumbnails carry the cache-buster too
      toast('Tone ' + fmt(t.lo, 0) + '–' + fmt(t.hi, 0) + '. Display only.', 'ok');
    } catch (e) { toast('Tone failed: ' + e.message, 'bad'); }
  }

  // ---- jobs -----------------------------------------------------------------------------
  function pollJob(jobId, onTick) {
    return new Promise((resolve, reject) => {
      const tick = async () => {
        let job;
        try { job = await GET('/api/jobs/' + jobId); }
        catch (e) { return reject(e); }
        if (onTick) { try { onTick(job); } catch (_) {} }
        if (job.state === 'done' || job.state === 'failed' || job.state === 'cancelled') {
          if (job.state === 'failed') return reject(new Error((job.error && job.error.message) || 'job failed'));
          return resolve(job);
        }
        setTimeout(tick, POLL_MS);
      };
      tick();
    });
  }

  // =========================================================================================
  // Boot
  // =========================================================================================
  /* ⚠️ EVERY ID HERE EXISTS IN index.html. index.html is the CONTRACT and it is FINAL — a typo, or
   * an id that was renamed out from under us, produces a `null` that only explodes at the moment the
   * user reaches that screen. If you add one, grep the HTML for it first.
   *
   * GONE with the 2026-07-14 rulings, and they must not come back:
   *   `load-result`  — opening a directory NAVIGATES to Range now; there is no reveal-in-place block.
   *   `run-why` / `split-why`   — the prose moved behind `#help-run` / `#help-split`.
   *   `run-n-excluded` / `run-n-in-range` — THE APP EXCLUDES NOTHING AT LOAD. There is no
   *                    "312 usable of 338 (26 thrown out)" line, because there is no ruling.
   *   `blank-measure` / `blank-thrsrc` / `blank-margin` — folded into `#help-blank`.
   *   `screen-build` / `screen-export` — renamed `screen-place` / `screen-mosaic`. */
  function cacheDom() {
    const ids = {
      app: 'app', toast: 'toast', banner: 'banner', canvas: 'view', stage: 'stage',
      sheet: 'sheet', stalePanel: 'stale-panel', evNccMeter: 'ev-ncc-meter', cbHint: 'cb-hint',
      hdrDataset: 'hdr-dataset', gpuBadge: 'gpu-badge',
      nAnchored: 'n-anchored', nUnverified: 'n-unverified', nUnplaced: 'n-unplaced',
      nExcluded: 'n-excluded', nDiverted: 'n-diverted', divertedBadge: 'diverted-badge',

      // the one help bubble, body-level and position:fixed (style.css owns the look)
      helpTip: 'help-tip',
      helpRun: 'help-run', helpSplit: 'help-split', helpGaps: 'help-gaps', helpBlank: 'help-blank',

      // 1 · LOAD — one question: which directory? (+ the resume path)
      inDatadir: 'in-datadir', btnBrowse: 'btn-browse', btnOpen: 'btn-open',
      openProgress: 'open-progress', openFill: 'open-fill', openMsg: 'open-msg',
      btnLoad: 'btn-load',

      // 2 · RANGE — the numbers, then: which trials are the mosaic?
      runRange: 'run-range', runN: 'run-n',
      splitValue: 'split-value', splitN1: 'split-n1', splitN2: 'split-n2', gapsV: 'gaps-v',
      inLo: 'in-lo', inHi: 'in-hi', inSplit: 'in-split', btnOverride: 'btn-override',
      btnBackLoad: 'btn-back-load', btnToScreen: 'btn-to-screen',

      // 3 · SCREEN — the scan recommends; HE ticks.
      blankN: 'blank-n', blankThr: 'blank-thr', blankList: 'blank-list',
      btnBlankAll: 'btn-blank-all', btnBlankNone: 'btn-blank-none', btnBlankApply: 'btn-blank-apply',
      btnBackRange: 'btn-back-range', btnToBuild: 'btn-to-build',

      // 4 · PLACE — one button.
      buildCost: 'build-cost', btnBuild: 'btn-build', btnBuildCancel: 'btn-build-cancel',
      inUsecache: 'in-usecache', btnSkipBuild: 'btn-skip-build',
      buildProgress: 'build-progress', buildFill: 'build-fill', buildPhase: 'build-phase',
      buildMsg: 'build-msg', buildEta: 'build-eta', buildLog: 'build-log',
      buildResult: 'build-result', bresN: 'bres-n', bresUnplaced: 'bres-unplaced', bresS: 'bres-s',
      bresGpu: 'bres-gpu', bresId: 'bres-id', bresWorklist: 'bres-worklist',
      btnBackScreen: 'btn-back-screen', btnToSweep: 'btn-to-sweep',
      cfgPassSplit: 'cfg-pass-split', cfgAnchorNcc: 'cfg-anchor-ncc', cfgSplitPx: 'cfg-split-px',
      cfgLook: 'cfg-look', cfgMinSide: 'cfg-min-side', cfgT27Conf: 'cfg-t27-conf',
      cfgT27Runconf: 'cfg-t27-runconf',

      // 5 · SWEEP — the stage itself: the canvas and both rails.
      cbTrial: 'cb-trial', cbState: 'cb-state', cbPass: 'cb-pass', cbPos: 'cb-pos', cbFps: 'cb-fps',
      btnAnchor: 'btn-anchor', btnExclude: 'btn-exclude', btnNext: 'btn-next', btnReplay: 'btn-replay',
      btnDiff: 'btn-diff', btnAlts: 'btn-alts', btnSnap: 'btn-snap', btnFit: 'btn-fit',
      btnOne: 'btn-one', btnUndo: 'btn-undo', btnRedo: 'btn-redo', btnPrev: 'btn-prev',
      refused: 'refused', evNcc: 'ev-ncc', evMargin: 'ev-margin',
      evAnchors: 'ev-anchors', evArea: 'ev-area', evNpix: 'ev-npix', evMs: 'ev-ms',
      evThin: 'ev-thin', evAperture: 'ev-aperture', evMachine: 'ev-machine',
      altsList: 'alts-list', toneLo: 'tone-lo', toneHi: 'tone-hi', btnTone: 'btn-tone',
      btnToneAuto: 'btn-tone-auto', queue: 'queue', queuePos: 'queue-pos',
      onlyOutstanding: 'in-only-outstanding', rescueList: 'rescue-list', stale: 'stale',
      buildStale: 'build-stale',

      // 6 · MOSAIC
      btnSave: 'btn-save', autosaveNote: 'autosave-note',
      inExportdir: 'in-exportdir', btnExportDir: 'btn-export-dir', inBasename: 'in-basename',
      outTiff: 'out-tiff', outPng: 'out-png', outPositions: 'out-positions', outGt: 'out-gt',
      outQc: 'out-qc', inRendermode: 'in-rendermode', inIncludeUnverified: 'in-include-unverified',
      inUmpx: 'in-umpx', btnExport: 'btn-export', exportProgress: 'export-progress',
      exportFill: 'export-fill', exportMsg: 'export-msg', exportFiles: 'export-files',
      provenance: 'provenance', btnBackSweep: 'btn-back-sweep',
    };
    const missing = [];
    for (const k of Object.keys(ids)) {
      el[k] = $(ids[k]);
      if (!el[k]) missing.push(ids[k]);
    }
    // A stale getElementById returning null is the single most likely way this file breaks, and it
    // breaks LATER, on a screen the user has walked to. Say it at boot, in the console, once.
    if (missing.length) console.error('sweep.js: these ids are not in index.html:', missing.join(', '));
  }

  function bind() {
    el.btnOpen.onclick = openDir;
    el.btnBrowse.onclick = async () => {
      try {
        const r = await POST('/api/dialog/open-directory', { title: 'Pick an acquisition directory' });
        if (r.path) el.inDatadir.value = r.path;
      } catch (e) { toast('No native dialog here — type the path.', 'warn'); }
    };
    el.btnOverride.onclick = overrideRun;
    el.btnToScreen.onclick = () => show('screen');
    // 🔴 "Place the tiles →" USED TO WALK STRAIGHT PAST THE REFUSAL LIST. Whatever the user ticked
    // on this screen never reached the server unless he pressed Apply, so the raw scan governed the
    // matcher for the whole session. Every path out of the screen now carries the human's decision.
    el.btnToBuild.onclick  = async () => { await putRefusals(); show('place'); };
    el.btnToSweep.onclick  = () => show('sweep');

    // the wizard's back buttons
    el.btnBackLoad.onclick   = () => show('load');
    el.btnBackRange.onclick  = () => show('range');
    el.btnBackScreen.onclick = () => show('screen');
    el.btnBackSweep.onclick  = () => show('sweep');

    el.btnBlankAll.onclick  = () => el.blankList.querySelectorAll('.blank-chk').forEach((c) => c.checked = true);
    el.btnBlankNone.onclick = () => el.blankList.querySelectorAll('.blank-chk').forEach((c) => c.checked = false);
    el.btnBlankApply.onclick = applyBlank;
    el.btnBuild.onclick = startBuild;
    el.btnBuildCancel.onclick = cancelBuild;
    el.btnSkipBuild.onclick = skipBuild;
    el.btnAnchor.onclick  = anchor;
    el.btnExclude.onclick = exclude;
    el.btnNext.onclick    = advance;
    el.btnReplay.onclick  = () => { if (viewerOk) Viewer.replayFade(); };
    el.btnDiff.onclick    = toggleDiff;
    el.btnAlts.onclick    = showAlternatives;
    el.btnSnap.onclick    = snap;
    el.btnFit.onclick     = () => { if (viewerOk) Viewer.fit(); };
    el.btnOne.onclick     = () => { if (viewerOk) Viewer.oneToOne(); };
    el.btnUndo.onclick    = undo;
    el.btnRedo.onclick    = redo;
    el.btnPrev.onclick    = () => { const p = prevTrial(cursor); if (p !== null) setCursor(p); };
    el.onlyOutstanding.onchange = renderQueue;
    el.btnTone.onclick     = () => applyTone(false);
    el.btnToneAuto.onclick = () => applyTone(true);
    el.btnSave.onclick = saveProject;
    el.btnLoad.onclick = loadProject;
    el.btnExport.onclick = doExport;
    el.btnExportDir.onclick = async () => {
      try {
        const r = await POST('/api/dialog/open-directory', { title: 'Pick an output directory' });
        if (r.path) el.inExportdir.value = r.path;
      } catch (e) { toast('No native dialog here — type the path.', 'warn'); }
    };
    /* THE HEADER IS A PROGRESS INDICATOR, NOT A MENU. `show()` refuses a locked step on its own (it
     * is also the one route a *button* can take you down), and `.step.locked` kills pointer-events
     * — this is the third belt, and it is the cheap one. */
    document.querySelectorAll('.step').forEach((b) => {
      b.onclick = () => show(b.dataset.screen);
    });
    window.addEventListener('keydown', onKeyDown);
  }

  /** 🔴 `--data-dir`: ATTACH TO THE OPEN THAT IS ALREADY IN FLIGHT.
   *
   *  `main.py --data-dir` fires `POST /api/session/open` at the server on a background thread and
   *  then paints the window IMMEDIATELY (it must — the open is 8-9 s and the window may not wait for
   *  it). So at the moment this page loads there is **no session yet**, and `init()` used to make a
   *  single `GET /api/session`, take the 404, and park on the Load screen **forever** — while the
   *  session opened perfectly well three seconds later, behind its back. Driven in the real native
   *  window: launched with `--data-dir`, the app sat on "Open an acquisition directory" with the
   *  path already typed in, and nothing but a second click would move it.
   *
   *  So: no session -> look for an `open` job. If one is running (or has just finished), ride it —
   *  same progress bar, same `loadSession()` tail as the Open button. -> true if we attached. */
  async function attachToPendingOpen() {
    let jobs;
    try { jobs = await GET('/api/jobs'); } catch (e) { return false; }
    const open = (jobs.jobs || []).find((j) => j.kind === 'open' &&
                                               (j.state === 'running' || j.state === 'queued'));
    if (!open) return false;
    el.openProgress.classList.remove('hidden');
    el.openMsg.textContent = 'opening…';
    try {
      await pollJob(open.job_id, (job) => {
        el.openFill.style.width = (job.pct || 0) + '%';
        el.openMsg.textContent = (job.phase || '') + ' — ' + (job.message || '');
      });
      await loadSession();          // -> Range
      el.openProgress.classList.add('hidden');
      return true;
    } catch (e) {
      el.openProgress.classList.add('hidden');
      toast('The launch directory failed to open: ' + e.message, 'bad');
      return false;
    }
  }

  /** Boot: health -> GPU -> (a directory may be preset by main.py) -> step 1, Load. */
  async function init() {
    cacheDom();
    Help.init();          // ⭐ before anything renders a `?` — one delegated listener, set up once
    bind();
    show('load');
    try {
      const h = await GET('/api/health');
      if (!h.ok) toast('Backend is up but not ok.', 'bad');
    } catch (e) {
      toast('Cannot reach the backend at ' + API() + ' — ' + e.message, 'bad');
    }
    renderGpu();
    if (window.CAMEA_DATA_DIR) el.inDatadir.value = window.CAMEA_DATA_DIR;
    try {
      // A session is already open (a page reload). Pick it straight back up — `loadSession` lands
      // on Range, which is where a freshly-loaded run belongs: nothing is placed yet.
      await loadSession();
      return;
    } catch (e) { /* 404 no_session — the normal cold start, OR --data-dir is still opening. */ }
    await attachToPendingOpen();   // --data-dir: ride the open job already in flight -> Range
  }

  return {
    init, anchor, exclude, advance, move, matchAnchor, prefetchNext, snap,
    showAlternatives, rescue, scoreAt, pushUndo, undo, redo, autosave, onKeyDown,
    // for the integration tests / the dev console:
    setCursor, show, exportDoc, recomputeGaps, nextTrial, prevTrial,
    loadBuildResult, applyBlank, putRefusals, pickAlternative,
    evidenceOf: (t) => evidence[K(t)], fieldSig, evidenceIsCurrent,
    get advancing() { return advancing; },
    get doc() { return doc; },
    get cursor() { return cursor; },
    get session() { return session; },
    get counts() { return counts(); },
  };
})();

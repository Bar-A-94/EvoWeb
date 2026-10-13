// ╔════════════════════════════════════════════════════════════════════════════╗
// ║  nine-hard-v5-chained.js — v5 ladder generator                              ║
// ║                                                                              ║
// ║  v5 = v4.1 + fixes from the v4.1 DATA AUDIT (David found 'Showing X of Y'   ║
// ║  233x across 20 samples — the generator anchored on the prompt's own        ║
// ║  examples; archetype mix was a fixed 3/3/2/1 in every sample) + two new     ║
// ║  requirements:                                                              ║
// ║  V5-1  ANTI-ANCHORING: global rules must be INVENTED for the app's domain;  ║
// ║        the prompt's examples may never be reused; example instances         ║
// ║        replaced by a menu of rule CLASSES. Verifier checks originality.     ║
// ║  V5-2  COUNTER CAP: at most 2 tasks in the whole ladder may verify a        ║
// ║        list-count/'Showing X of Y'-style convention.                        ║
// ║  V5-3  ARCHETYPE MIX RELAXED: >=3 archetypes present, <=4 turns of any one, ║
// ║        never twice in a row — the allocation should VARY between samples.   ║
// ║  V5-4  IMPLEMENTATION-AGNOSTIC TASKS (David): there are endless valid ways  ║
// ║        to build a feature — tasks/expected_results must hold for ANY        ║
// ║        reasonable implementation of the instructions, never the specific    ║
// ║        UI the generator imagined. Verifier rule 11.                         ║
// ║  V5-5  PER-TURN COMPLEXITY FLOOR (David): verifier explicitly judges every  ║
// ║        turn as substantially complex engineering (advanced capabilities),   ║
// ║        not a widget-sized ask. Verifier rule 12.                            ║
// ║                                                                              ║
// ║  v4.1 = v4 with the DEPENDENCY model reworked after David's review of the   ║
// ║  v4 output (sample 1: screener/watchlist adjacency read as repetition;      ║
// ║  shared-seed "dependencies" too weak; but mandating a fixed connection      ║
// ║  shape — e.g. sub-components — is too rigid for apps we can't predict):     ║
// ║  DEP-1  QUOTA RELAXED: not every turn must connect. Was "≥5 of turns 4-10   ║
// ║         consume an earlier follow-up"; now 3-4+ SIGNIFICANT dependencies    ║
// ║         across the 9 turns — the generator chooses which turns and HOW.     ║
// ║         Standalone turns are fine.                                          ║
// ║  DEP-2  SIGNIFICANCE BAR on every declared edge: the later feature must     ║
// ║         materially rely on the earlier one — if the earlier feature were   ║
// ║         missing or broken, the later one couldn't do what it's specified   ║
// ║         to do. Reading the same seeded records is NOT a dependency.        ║
// ║         Connection SHAPE is free (aggregate / drive / cross-validate /      ║
// ║         reconcile / embed / extend / gate / ...) — creativity encouraged.   ║
// ║  DEP-3  DISTINCTNESS (v2's dropped rule, adapted): every follow-up is a    ║
// ║         NEW capability — different core operation + UI surface from the    ║
// ║         base app and every other turn. Relying on an earlier feature is    ║
// ║         required-good; resembling its function is the violation (two       ║
// ║         filterable lists, two calculators, two savable tables).            ║
// ║  DEP-4  One chain still ≥3 deep (the breakage cascade is the point);       ║
// ║         standalone turns use the global-rule variant of the integration    ║
// ║         slot. Verifier rules 4 (rewritten) + 10 (new) enforce all this.    ║
// ║  DEP-5  MINIMAL TESTER WORK (David review): tasks use the fewest entities/ ║
// ║         repetitions that prove the check — no "add three subtasks" when    ║
// ║         one suffices; preload data via seed instead of live creation.      ║
// ║         Generator STEP 4 + verifier rule 7.                                ║
// ║  Same 20-sample subset. Output: evoweb_benchmark.jsonl / evoweb_main_dataset/.          ║
// ║  Pilot mode: pass args {samples: [..]} to generate a few and skip assembly. ║
// ║                                                                              ║
// ║  ── WHY v4 (difficulty regression found in v3) ──                          ║
// ║  v3 optimized STRUCTURAL difficulty (dependency depth, integration,        ║
// ║  regression, exact values) but silently DROPPED the three clauses that      ║
// ║  made each individual feature intrinsically hard in v2. v4 re-adds them —   ║
// ║  keeping ALL of v3's DAG/exact-value/regression machinery — so a ladder is  ║
// ║  hard BOTH structurally (chains) AND per-feature (each turn a real          ║
// ║  sub-problem). The re-added levers (marked ═══ v4 RESTORE below):          ║
// ║  RESTORE-A  Every follow-up's CORRECTNESS MUST HINGE ON A NON-TRIVIAL       ║
// ║             SUB-PROBLEM (boolean composition, count-consistent-with-visible ║
// ║             set, stable sort incl. ties, exact rounding/units, empty/       ║
// ║             boundary, input validation). [v2 line 72; absent in v3]         ║
// ║  RESTORE-B  Per-archetype hardness specs: derived-state seed ARRANGED so a  ║
// ║             naive build VISIBLY differs; interactive-tool updates per       ║
// ║             keystroke; multi-surface keeps every action visible/reachable;  ║
// ║             design-restyle = 4-6 specific rules on 3+ pages, partial        ║
// ║             application is the failure tested. [v2 lines 74-77; thinned v3] ║
// ║  RESTORE-C  Each feature must BUNDLE SEVERAL INTERACTING REQUIREMENTS (a    ║
// ║             screener with presets AND a counter AND an export — not a lone  ║
// ║             filter). [v2 line 78; absent in v3]                             ║
// ║                                                                              ║
// ║  ── WHAT v3 CHANGED vs nine-hard-followups.js (all inherited by v4) ──      ║
// ║  CHANGE #1  SELF-CONTAINED → CHAINED, as a DAG (review round 1: was a       ║
// ║             single-root tree + stable-base S3 inspection; David dropped     ║
// ║             the inspection — generator stays blind like v2 — and the        ║
// ║             structure is now a DAG: multiple independent entry features     ║
// ║             are fine, converging/fanning later). The agent designs the      ║
// ║             finished "T10 target app" as a feature DAG (longest path       ║
// ║             depth ≥ 3), slices it into 9 turns in a valid topological       ║
// ║             order, and RECORDS THE GRAPH in the output JSON               ║
// ║             (dependency_graph {nodes, edges}) for auditing + HTML viewer.  ║
// ║  CHANGE #2  Real features may be ADAPTED: grounding still starts from      ║
// ║             similar_websites.json real features, but the agent may fuse,   ║
// ║             extend, or complicate them so they genuinely depend on each    ║
// ║             other — fidelity to the real site yields to the dependency.    ║
// ║  CHANGE #3  Regression slot REINSTATED (was in super-hard v1, banned in     ║
// ║             earlier drafts): task 5 of every turn is a VERBATIM copy of an     ║
// ║             earlier turn's task. Task 4 is a cross-feature integration.     ║
// ║  CHANGE #4  "NOT a data-dependent constant" rule INVERTED for pinned data:  ║
// ║             one early turn pins an exact seed dataset in its instruction;   ║
// ║             later turns get ≥1 exact-value task (exact count/sum/order).    ║
// ║  CHANGE #5  GLOBAL RULES: 2-3 app-wide conventions introduced naturally in  ║
// ║             early turns; later turns must silently comply and are tested.   ║
// ║  CHANGE #6  Per-sample VERIFY + one REPAIR pass (an earlier draft leaked 5 samples     ║
// ║             with banned controls; this time compliance is machine-checked  ║
// ║             before assembly).                                               ║
// ║  CHANGE #7  Surface language is MORE casual-user, not less — dependencies  ║
// ║             and precision are embedded underneath natural phrasing.        ║
// ║  CHANGE #8  HARNESS-POSSIBLE rule (pilot review): explicit ban on external ║
// ║             APIs / LLM features / email / auth / uploads / real clock /    ║
// ║             file downloads — everything must run fully client-side over    ║
// ║             seeded local data and be observable on screen. Verifier rule 8.║
// ║                                                                              ║
// ║  ── CARRIED OVER UNCHANGED (the learnings) ──                               ║
// ║  · generator is BLIND: sees only the build prompt, never the finished app  ║
// ║  · click/type/scroll-only tester; NO hover/drag/keyboard; sliders BANNED    ║
// ║  · every check reachable in ≤6 operations; behavioral invariants elsewhere  ║
// ║  · archetype mix (derived-state / interactive-tool / multi-surface /        ║
// ║    design-restyle), never the same archetype twice in a row                 ║
// ║  · grounding starts from similar_websites.json; avoid cosmetic features     ║
// ║  · runtime robustness (crash/blank page = ladder death via the turn gate)   ║
// ║  · natural, varied wording; 2–5 sentence instructions                       ║
// ║  · part-file per sample + missing-tolerant assembly + verification summary  ║
// ╚════════════════════════════════════════════════════════════════════════════╝

export const meta = {
  name: 'nine-hard-v5-chained',
  description: 'v5 ladder generator: v4.1 + anti-homogeneity (invent app-specific global rules, never reuse prompt examples; counter-check cap; varied archetype mix) + implementation-agnostic tasks + per-turn complexity floor. Otherwise: v4 (intrinsic hardness + DAG + exact values + regression/integration slots + global rules) with the dependency model reworked — fewer but SIGNIFICANT dependencies (later feature materially relies on the earlier one; shared seed data does not count; connection shape is free), every follow-up a DISTINCT new capability vs the base app and all other turns, one chain >= 3 deep. Verify + repair each sample, then assemble evoweb_benchmark.jsonl (skipped in pilot mode).',
  phases: [
    { title: 'Generate', detail: 'Per-sample: design target-app DAG, write 9 chained follow-ups', model: 'opus' },
    { title: 'Verify', detail: 'Per-sample compliance check (banned controls, DAG depth/consistency, verbatim regressions, exact-value coverage, intrinsic hardness) + one repair pass' },
    { title: 'Assemble', detail: 'Write evoweb_benchmark.jsonl (full runs only; pilot skips this)' },
  ],
}

// [unchanged] Worktree data dir + the challenging 20-sample subset.
const FULL = [1, 7, 11, 14, 17, 30, 35, 38, 40, 41, 47, 48, 51, 57, 59, 61, 64, 70, 91, 93]
// Pilot mode: Workflow args {samples: [1, 14, 30]} generates only those and skips assembly.
// args may arrive JSON-string-encoded (bit us on the first pilot run: fell back to FULL) — parse defensively.
const parsedArgs = typeof args === 'string' ? JSON.parse(args) : args
// Where this repository keeps its datasets: <clone>/data (evoweb/paths.py's DATA).
// The Workflow sandbox has no __dirname, so pass it as an arg {data: '/abs/.../data'}
// or edit the fallback below to your clone's absolute path before dispatching.
const DATA = (parsedArgs && parsedArgs.data) || '/ABSOLUTE/PATH/TO/EvoWeb/data'
const SCRIPTS = `${DATA}/data_gen`   // assemble_dataset.py, audit_parts.py
const indices = (parsedArgs && parsedArgs.samples) || FULL
const pilot = Boolean(parsedArgs && parsedArgs.samples)

const TASK_ITEM = {
  type: 'object',
  properties: {
    // ═══ v3 CHANGE #3/#4: every task declares what KIND of check it is ═══
    kind: { type: 'string', enum: ['feature', 'exact-value', 'integration', 'regression'], description: 'feature = tests this turn\'s own work (invariant-style); exact-value = expected_result is an exact constant derived ONLY from the pinned seed dataset; integration = exercises this turn\'s feature TOGETHER with an earlier turn\'s feature; regression = VERBATIM copy of an earlier turn\'s task.' },
    copied_from_turn: { type: 'number', description: 'regression tasks only: the turn (1 = base app, 2-10 = follow-ups) whose ui_instruct this task was copied from, character-for-character.' },
    task: { type: 'string', description: 'A tester interaction using only clicks, typing into input fields, and scrolling. NEVER requires hover, drag, or keyboard navigation.' },
    expected_result: { type: 'string', description: 'feature/integration: a checkable behavioral invariant a naive/buggy implementation gets wrong. exact-value: an exact constant (count, sum, ordering, label) derivable only from the pinned seed. regression: copied verbatim.' },
    task_category: {
      type: 'object',
      properties: {
        primary_category: { type: 'string', enum: ['Functional Testing', 'Design Validation Testing', 'Data Display Testing'] },
        subcategories: { type: 'array', items: { type: 'string' } },
      },
      required: ['primary_category', 'subcategories'],
    },
  },
  required: ['kind', 'task', 'expected_result', 'task_category'],
}

const FOLLOWUP_ITEM = {
  type: 'object',
  properties: {
    // [unchanged] archetype mix from nine-hard
    archetype: { type: 'string', enum: ['derived-state', 'interactive-tool', 'multi-surface-workflow', 'design-restyle'] },
    instruction: { type: 'string', description: '2-5 sentences in casual user voice. Precision and dependencies embedded naturally, never as spec clauses or turn numbers.' },
    source_website: { type: 'string' },
    source_feature: { type: 'string', description: 'The real feature this one started from — the implemented version may be adapted/fused/extended beyond it.' },
    ui_instruct: { type: 'array', minItems: 5, maxItems: 5, items: TASK_ITEM },
  },
  required: ['archetype', 'instruction', 'source_website', 'source_feature', 'ui_instruct'],
}

const SCHEMA = {
  type: 'object',
  properties: {
    app_idx: { type: 'number' },
    // ═══ v3 CHANGE #1: the back-translated design + its DAG, recorded for audit and the HTML viewer ═══
    target_app_summary: { type: 'string', description: '3-6 sentences: the much bigger product the app has grown into after all 9 turns (the several directions it grew in), and the shape of its feature graph.' },
    dependency_graph: {
      type: 'object',
      properties: {
        nodes: {
          type: 'array', minItems: 10, maxItems: 10,
          items: {
            type: 'object',
            properties: {
              id: { type: 'string', description: '"T1" (base app) through "T10", matching turn order.' },
              label: { type: 'string', description: 'Short feature name, 2-5 words (T1 = "base app").' },
              archetype: { type: 'string', description: 'The node\'s archetype ("base" for T1).' },
            },
            required: ['id', 'label', 'archetype'],
          },
        },
        edges: {
          type: 'array',
          items: {
            type: 'object',
            properties: {
              from: { type: 'string', description: 'The earlier turn whose artifact is consumed (e.g. "T3").' },
              to: { type: 'string', description: 'The later turn that consumes it. Must be a strictly later turn (DAG, edges point forward).' },
              what: { type: 'string', description: 'The consumed artifact, in a few words (e.g. "expense records", "watchlist grouping", "pinned seed dataset").' },
            },
            required: ['from', 'to', 'what'],
          },
        },
      },
      required: ['nodes', 'edges'],
    },
    // ═══ v3 CHANGE #5 ═══
    global_rules: {
      type: 'array', minItems: 2, maxItems: 3,
      items: {
        type: 'object',
        properties: {
          rule: { type: 'string', description: 'An app-wide convention, e.g. money always "$1,234.56", every list view shows a "Showing X of Y" counter, destructive actions always confirm.' },
          introduced_in_turn: { type: 'number', description: 'The turn whose instruction states this rule (naturally, as a user preference).' },
        },
        required: ['rule', 'introduced_in_turn'],
      },
    },
    // ═══ v3 CHANGE #4 ═══
    pinned_seed: {
      type: 'object',
      properties: {
        entity: { type: 'string', description: 'What the pinned records are (e.g. "6 rental properties").' },
        introduced_in_turn: { type: 'number', description: 'The turn whose instruction spells out the exact records.' },
        records_gist: { type: 'string', description: 'One line summarizing the exact values (for our audit; the full records live in the instruction text).' },
      },
      required: ['entity', 'introduced_in_turn', 'records_gist'],
    },
    follow_ups: { type: 'array', minItems: 9, maxItems: 9, items: FOLLOWUP_ITEM },
  },
  required: ['app_idx', 'target_app_summary', 'dependency_graph', 'global_rules', 'pinned_seed', 'follow_ups'],
}

const VERDICT = {
  type: 'object',
  properties: {
    ok: { type: 'boolean' },
    violations: { type: 'array', items: { type: 'string' }, description: 'Each violation: which turn/task and which rule it breaks. Empty when ok.' },
  },
  required: ['ok', 'violations'],
}

const partPath = (idx) => `${DATA}/evoweb_main_dataset/${String(idx).padStart(6, '0')}.json`

const genPrompt = (idx) => `You are generating a NINE-turn chained follow-up ladder (turns 2-10) for a long-horizon web-dev benchmark. Weak models must score near zero on the late turns; strong models should reach the middle. The lever is DEPENDENCY: later turns must genuinely stand on earlier turns' work, so breakage and shallow implementations compound.

## STEP 1 — read your inputs (you are BLIND to the finished app)
1. Read line ${idx} (1-indexed) of ${DATA}/legacy_webgen_bench_apps.jsonl. Its "instruction" field is the base-app BUILD PROMPT. You see ONLY this prompt, NOT the finished app, so never assume a specific implementation detail, page, or field exists beyond what the prompt asked for. Your ladder REPLACES the old hard3/9hard follow-ups entirely; do not read or reuse them.
2. Read ${DATA}/similar_websites.json, entry app_idx == ${idx}: its similar_websites[].interesting_features are your grounding. Favor features needing real engineering (multi-criteria filtering/screeners, cross-filtering, ranking with ties, aggregations/rollups, calculators, debounced search, pagination interacting with filters/sort, computed exports). Cosmetic features only inside the design-restyle archetype.

## STEP 2 — design the GROWN app first, as a feature graph, then slice it (back-translation)
Imagine this base app a year later, grown into a much BIGGER product for its domain. Design 9 MAJOR features — each one an epic-sized module a real team would ship as its own milestone, often with its own page or section. NOT small tweaks, single widgets, or slices of one narrow product vision: the 9 features may pull the app in several different directions (analytics, workflows, discovery, tooling, planning, community...) as long as each fits the app's domain and users. Do NOT shrink features to make them fit together — size each one as if it were the only thing being asked for that week. SOME of the 9 genuinely build on each other; standalone features are fine, but the connections you do create must be real and significant (rules below). Then cut the graph into turns 2-10 in a valid topological order (every dependency built before its consumer). Requirements:
- ADAPT THE REAL FEATURES: start each feature from a real similar_websites feature, but you may fuse two of them, extend one, or make it more complex — including reshaping it so it genuinely builds on another feature where that makes the app more coherent. Fidelity to the original site yields to the design. Keep source_website/source_feature pointing at what it started from.
- CORRECTNESS MUST HINGE ON A NON-TRIVIAL SUB-PROBLEM in EVERY follow-up (this is the load-bearing per-feature hardness rule; a feature whose only hard part is "consumes an earlier turn" is NOT enough). Each feature's correctness must turn on at least one of: correct boolean composition (AND across dimensions, OR within one); a count/total that stays exactly consistent with the filtered/visible set as it changes; stable & correct sorting including ties and mixed types; exact computed values with correct rounding/units; correct empty/boundary/first-load handling; precise input validation; for design-restyle — full cross-page consistency. A naive/shallow build must get this sub-problem WRONG. State the expectation in the instruction, embedded naturally per STEP 3's wording rule, never as a formal spec clause.
- BUNDLE SEVERAL INTERACTING REQUIREMENTS per feature: each follow-up is a rich feature with multiple controls/states/rules that interact, NOT a lone control. E.g. a screener with saved presets AND a live result counter AND a computed export — not a single filter; a workflow with validation AND a review step AND persistence — not one button. The interacting requirements are part of what a weak model fails to keep mutually consistent.
- SIGNIFICANT DEPENDENCIES, YOUR CHOICE OF SHAPE: you decide which turns build on earlier ones and HOW — a connection can take any form that fits this app (aggregate an earlier feature's output, drive it from a new control, cross-validate against it, reconcile two earlier features, gate a flow on it, embed or extend it...). Invent what's natural for the domain; there is no mandated shape. Not every turn needs a dependency. But every connection you DO declare must be SIGNIFICANT: the later feature must genuinely rely on the earlier one, such that if the earlier feature were missing or broken, the later one could not do what its instruction asks for. Merely reading the same seeded records as an earlier turn is NOT a dependency and must not be declared as an edge. Create AT LEAST 3-4 such significant dependencies across the 9 turns, arranged so at least one chain runs >= 3 deep from T1 (a feature relying on a feature relying on a feature) — deep chains are what make early breakage compound.
- EVERY FEATURE IS A DISTINCT NEW CAPABILITY: each follow-up must introduce a capability that neither the base app nor any other turn already provides — a different core operation on a different UI surface. Relying on an earlier feature is good; RESEMBLING its function is the failure: never build two features of the same kind (two filterable lists, two calculators, two savable tables, two dashboards) even if one references the other, and never re-implement or lightly re-skin something the base app was already asked to have.
- RECORD THE GRAPH: output dependency_graph with all 10 nodes (T1 "base app" + T2-T10) and an edge for every SIGNIFICANT reliance, each labeled with WHAT the later feature relies on and how (e.g. "aggregates the tracker's logged expenses", "gates checkout on the validator's result"). Edges only point forward; standalone turns simply have no incoming T2+ edge. This is our audit trail and gets rendered in a viewer — make labels short and honest. The implementer NEVER sees it. COMPLETENESS still applies where reliance exists: design-restyle turns need an edge for EACH feature they restyle, and a turn that materially leans on a base-app page/surface needs a T1 edge; under-declared restyle/base edges were the #1 audit failure.
- ARCHETYPE MIX: use at least 3 of the four archetypes across the 9 turns, at most 4 turns of any one, never the same archetype twice in a row — and let the allocation follow THIS app's natural shape rather than a fixed quota. Interactive-tool turns are the natural low-dependency ones — place them early, then wire later turns to consume their outputs where it fits. Each archetype carries its OWN hardness spec, which the feature must satisfy:
  (a) DERIVED-STATE: computes/aggregates/ranks over seeded or earlier-turn records (rollups, windowed stats, cross-filters). ARRANGE THE SEED so a naive implementation produces a VISIBLY DIFFERENT result from the correct one (e.g. a windowed/most-recent order differs from all-time order; a tie forces a specific tiebreak; a rounding edge changes a displayed total) — so the exact-value task actually discriminates.
  (b) INTERACTIVE TOOL: driven purely by the user's typed inputs — calculators, configurators, live meters/previews. State MUST update correctly DURING interaction (per keystroke/field/click), not only on a final submit.
  (c) MULTI-SURFACE WORKFLOW: a flow spanning 2+ pages/views (create -> review -> resolve) where EVERY required action stays visible and reachable — nothing gated behind an implicit role, hover, or hidden state the click-only tester can't reach.
  (d) DESIGN RESTYLE: a bundle of 4-6 SPECIFIC visual requirements (primary action color, heading alignment, card spacing/radius, a badge style, a typography rule) applied CONSISTENTLY across at least 3 named pages — PARTIAL APPLICATION (some pages updated, others missed) is exactly the failure being tested.
- FAIRNESS RULE (critical, because you are blind): every dependency must be expressed through USER-VISIBLE behavior an earlier instruction EXPLICITLY asked to build — never through assumed implementation details. If turn 7 needs turn 3's records, turn 3's instruction must have clearly created them. Different valid implementations of earlier turns must all be able to support later turns.
- PINNED SEED: exactly one early turn (2 or 3) pins an exact small dataset in its instruction — spell out ~5-8 records with exact names/numbers, phrased casually ("start me off with these six: Maple Duplex at $1,850/mo, 2 units, ... — exactly these, I'll add more later"). Later derived-state turns compute over THESE records so exact expected values exist.
- GLOBAL RULES: 2-3 app-wide conventions, each introduced naturally inside some early turn's instruction as a user preference, with the app-wide scope stated ("everywhere in this app, now and for anything we add later"). INVENT conventions specific to THIS app's domain — NEVER reuse an example from this prompt, and avoid the generic list-counter and money-format cliches unless nothing domain-specific fits. Pick from different CLASSES: value formatting (units, precision, notation), naming/labeling schemes, color/badge coding, ordering/grouping conventions, interaction conventions (confirmations, undo, defaults), state display (how statuses/progress are shown). Later turns' instructions do NOT restate them — compliance is tested silently.
- RUNTIME ROBUSTNESS: favor features where a naive build crashes or blanks (dedup/unique-count/sort over collections, non-blank empty/first-load states). A crash is a total failure — the ladder dies there.
- HARNESS-POSSIBLE ONLY (STRICT): the app is a self-contained client-side React app with local seeded data — no backend, no network, no clock. NEVER require: external/third-party APIs or live data (prices, weather, maps, feeds), AI/LLM-powered anything, email/SMS/push sending, login/signup/auth/roles, file uploads, real-time sync/collaboration, or behavior depending on the actual current date/time (fixed labels like "Trending This Week" over seeded counts are fine; computing from today's real date is not). Exports/share features must render their output ON SCREEN (a preview panel or copyable text block) — never as a file download, which the tester cannot verify.

## STEP 3 — write each instruction (2-5 sentences, casual user voice)
Write like a real product owner returning with the next ask: varied tone, plain words, concrete domain examples, occasional mid-sentence asides. NEVER say "turn", "feature from before", or spec-speak ("must equal exactly"). Refer to earlier work the way a user would: "that screener you set up", "the expenses I've been logging in the tracker". All precision — exact seed values, thresholds, formats — is embedded conversationally, not as clauses. Across 9 turns, vary structure so they don't read like one template.

## STEP 4 — EXACTLY 5 verification tasks per turn, in this fixed template
Tester limits (STRICT): clicks, typing into inputs (auto-Enter), scrolling ONLY. NO hover, NO drag, NO keyboard navigation. BANNED controls anywhere: sliders, range handles, drag-to-reorder, drag-and-drop, dials — numeric thresholds are typed into text inputs. Never write the words "slider", "drag", or "hover". Every task reaches its check in <= 6 operations.
MINIMAL WORK PER TASK: every task must be the SIMPLEST interaction that still proves the check — the fewest actions, entities, and repetitions possible (e.g. "add a subtask and check it off", not "add three subtasks and check one off"). If a check needs data to exist, preload it via seed data rather than having the tester create it.
COUNTER CAP: across the WHOLE ladder, at most 2 tasks may verify a list-count / "Showing X of Y"-style convention — spend checks on the app's real behavior, not repeated counter reads.
NO SETUP OR FREE CHOICES IN TASKS: a task must never leave the tester to set up state or invent values (names, amounts, configurations). If a check depends on specific data existing, put that data in the TURN'S INSTRUCTION so the builder seeds it, and let the task simply interact with what's already there (e.g. the instruction seeds an overdue item; the task is "open the list and look at the overdue item", not "create an overdue item, then...").
- Tasks 1-3, kind "feature" (or "exact-value"): test THIS turn's work — and at least one of them must directly exercise the turn's NON-TRIVIAL SUB-PROBLEM: the boolean composition, the count-stays-consistent, the tie/sort, the rounding, the boundary/empty case, or the validation — phrased so a shallow build fails it. From the pinned-seed turn onward, AT LEAST ONE of these three per turn is kind "exact-value": its expected_result is an exact constant computed from the pinned records, and the seed must be arranged so a naive build would show a DIFFERENT constant (e.g. "the windowed top-3 reads A, C, B — not the all-time A, B, C"). Exact-value tasks are still bound by the <= 6 operations ceiling (don't chain create -> save -> reopen -> export in one task; get to the constant the shortest way). The other feature tasks stay behavioral invariants: relationships, counts-consistent-with-visible-set, orderings — never exact message strings, so different valid UX still passes.
- Task 4, kind "integration": if this turn has a declared dependency, one flow that exercises THIS turn's feature TOGETHER with the earlier feature it relies on (act over there, watch the effect land correctly over here) — it should walk one of the DAG edges into this turn and fail if the reliance is broken. For STANDALONE turns (no incoming T2+ edge) — and for at least 2 turns of the ladder overall — make this slot instead verify a GLOBAL RULE on the new feature's surface (the new surface silently obeys an app-wide convention introduced in an earlier turn).
- Task 5, kind "regression": copy ONE task VERBATIM (task + expected_result, character-for-character) from an earlier turn's ui_instruct, and set copied_from_turn. For turn 2, instead write one task against the BASE app using ONLY behavior the build prompt explicitly asked for (copied_from_turn = 1). Choose targets FREELY — do not default to always re-testing the immediately previous turn: prefer the turns later turns depend on, and vary the gap (a late turn re-testing an early feature is especially valuable). At least 5 of turns 2-9 should be re-tested by some later regression; full coverage is NOT required.
- IMPLEMENTATION-AGNOSTIC TASKS (critical — you are blind): there are ENDLESS valid ways to build each feature; the app that gets built will NOT be the one you imagined. A task may only reference elements, labels, and values the instructions EXPLICITLY requested; everything else must be phrased generically ("the row for Maple Duplex", "the control that filters by price") and every expected_result must hold for ANY reasonable implementation of the instructions — never for one specific layout, wording, or mechanism you pictured.
- ONE SMALL ASPECT IS FINE; every task names specific elements the instructions asked for; every expected_result is a specific observable outcome, never "works correctly".

## OUTPUT
Build { "app_idx": ${idx}, "target_app_summary": ..., "dependency_graph": { "nodes": [...], "edges": [...] }, "global_rules": [...], "pinned_seed": {...}, "follow_ups": [ EXACTLY 9, turns 2-10 in order ] }.
FIRST write it as a single compact JSON line to ${partPath(idx)} with the Write tool. THEN return the same object as your structured output.`

// The verifier re-derives compliance from the part file alone — it does not trust the generator.
const verifyPrompt = (idx) => `Audit ${partPath(idx)} — a 9-turn chained follow-up ladder for a web benchmark. FIRST read line ${idx} (1-indexed) of ${DATA}/legacy_webgen_bench_apps.jsonl — the BASE app's build prompt; rules 3, 4 (fairness) and 10 (distinctness vs base) are checked against it. Then read the part file and check EVERY rule below; report ok/violations. Be strict; cite turn+task per violation.
1. BANNED CONTROLS: no instruction or task anywhere contains sliders/range handles/drag/hover/keyboard-navigation (or the words "slider", "drag", "hover", "press Tab/Enter/Escape").
2. STRUCTURE: exactly 9 follow_ups, exactly 5 ui_instruct tasks with kinds = 3x feature/exact-value + 1 integration + 1 regression, in that slot order.
3. REGRESSIONS VERBATIM: every regression task's task+expected_result strings appear character-for-character in the ui_instruct of the turn named by copied_from_turn (turn 2's may target the base app, copied_from_turn=1, using only behavior the base build prompt asked for). Across the ladder, at least 5 of turns 2-9 are re-tested by a later regression (full coverage NOT required — varied gaps and dependency-focused targets beat a mechanical k-1 chain).
4. DAG + DEPENDENCY SIGNIFICANCE: dependency_graph has all 10 nodes T1-T10; every edge points strictly forward; the longest path from T1 reaches depth >= 3; at least 3 edges land on a T2+ target (i.e. at least 3 significant follow-up-on-follow-up dependencies exist — standalone turns are allowed, no per-turn quota). SIGNIFICANCE: for EACH edge, the consuming turn's instruction must genuinely rely on the earlier feature — if that earlier feature were missing or broken, the later feature could not do what its instruction asks. Flag any edge whose only basis is that both turns read the same seeded records. CONSISTENCY: every edge corresponds to something the consuming instruction actually leans on, and every earlier-work reference in an instruction has a matching edge. FAIRNESS: every relied-on artifact was explicitly requested by the earlier instruction (the generator is blind — flag any dependency on assumed implementation details).
5. EXACT VALUES: a pinned_seed turn exists (turn 2 or 3) whose instruction spells out exact records; from that turn on every turn has >= 1 exact-value task whose expected constant is actually derivable from those records (recompute it yourself; flag any wrong constant — a wrong constant poisons the eval).
6. GLOBAL RULES: 2-3 rules, each introduced naturally in an early instruction with app-wide scope; at least 2 later turns have a task verifying a global rule on a NEW surface; no later instruction restates the rule. ORIGINALITY: rules must be specific to this app's domain — flag generic list-counter ("Showing X of Y") or money-format rules unless clearly domain-motivated, and flag any ladder where more than 2 tasks total verify a list-count convention (counter cap).
7. LANGUAGE + TASK ECONOMY: instructions read like a casual user (no "turn N", no spec clauses); archetypes never repeat back-to-back, at least 3 archetypes are present, and no archetype exceeds 4 turns; no task needs more than ~6 operations. MINIMAL WORK: flag any task that isn't the simplest interaction proving its check — more actions, entities, or repetitions than needed (e.g. "add three subtasks and check off one" when one subtask proves the same thing). NO SETUP/FREE CHOICES: flag any task that makes the tester set up state or invent values (create records, configure things, pick arbitrary names/amounts) when that data could have been seeded by the turn's instruction — the task should just interact with what the instruction already asked to exist.
8. HARNESS-POSSIBLE: nothing anywhere requires external/third-party APIs or live data, AI/LLM functionality, email/SMS/push sending, auth/login/roles, file uploads, real-time sync, the actual current date/time (static labels like "This Week" over seeded data are fine), or file downloads (exports must show their output on screen). Flag any feature a fully offline client-side React app with seeded local data could not implement, or any expected_result the click/type-only tester could not observe on screen.
9. INTRINSIC HARDNESS: every follow-up's correctness must hinge on a non-trivial sub-problem (boolean composition, count-consistent-with-visible-set, stable sort incl. ties, exact rounding/units, empty/boundary handling, or input validation) — flag any feature whose only difficulty is "it depends on an earlier turn" or that a shallow build would trivially get right. Every follow-up must BUNDLE several interacting requirements, not be a lone control. And each archetype must meet its own spec: derived-state seeds must be arranged so a naive build VISIBLY differs (flag exact-value tasks whose constant a naive implementation would also produce); interactive-tool must update per keystroke/field/click; multi-surface must keep every required action reachable by clicks alone; design-restyle must list 4-6 specific rules across >=3 named pages with partial application as the tested failure.
10. DISTINCTNESS: every follow-up must be a NEW capability — a different core operation on a different UI surface from the base app's requested features and from every other turn. Flag any pair of turns that are the same kind of feature (two filterable lists, two calculators, two savable tables, two dashboards, two search boxes), and any turn that re-implements or lightly re-skins something the base build prompt already asked for. Relying on an earlier feature (a declared edge) is NOT a violation — resembling its function is.
11. IMPLEMENTATION-AGNOSTIC TASKS: the builder never sees the generator's imagined design, and there are endless valid ways to implement each instruction — flag any task or expected_result that assumes an implementation detail the instructions never requested (a specific button label, page layout, widget type, message wording, or mechanism). Every check must pass on ANY reasonable implementation of the instructions.
12. PER-TURN COMPLEXITY: judge EVERY turn's feature on engineering weight — it must be substantially complex, demanding advanced capability (multi-component state, real logic per rule 9, several interacting requirements, its own surface). Flag any turn that is widget-sized, a trivial variation of standard CRUD, or that a competent model could complete with a few lines — every turn must be a real milestone.
Return { ok, violations }.`

phase('Generate')
const results = await pipeline(
  indices,
  (idx) => agent(genPrompt(idx), { label: `gen-${String(idx).padStart(3, '0')}`, phase: 'Generate', schema: SCHEMA, model: 'opus' }),
  // ═══ v3 CHANGE #6: verify each sample as soon as it lands; one repair pass on failure ═══
  async (gen, idx) => {
    if (!gen) return { idx, status: 'generation-failed' }
    let verdict = await agent(verifyPrompt(idx), { label: `verify-${String(idx).padStart(3, '0')}`, phase: 'Verify', schema: VERDICT })
    if (verdict && !verdict.ok) {
      await agent(
        `${partPath(idx)} failed audit with these violations:\n${verdict.violations.map((v) => `- ${v}`).join('\n')}\n\nFix ONLY what the violations require — keep everything compliant untouched. Rules recap: verbatim regressions with correct copied_from_turn; >=1 exact-value task per turn from the pinned-seed turn on, with constants recomputed from the pinned records AND the seed arranged so a naive build would show a different constant; every feature's correctness hinges on a non-trivial sub-problem and bundles several interacting requirements (not a lone control); each archetype meets its hardness spec (derived-state visibly differs from naive, interactive-tool updates per keystroke, multi-surface actions reachable by clicks, design-restyle 4-6 rules on 3+ pages); dependency_graph consistent with the instructions, longest path depth >= 3, at least 3 SIGNIFICANT follow-up-on-follow-up edges (the later feature genuinely relies on the earlier one; shared seed data does not count as an edge; standalone turns are allowed); every follow-up a DISTINCT new capability (no two turns of the same kind, nothing re-implementing a base feature); no banned controls or the words slider/drag/hover; casual user voice, no "turn N"; each task the simplest interaction that proves its check, never asking the tester to set up data the turn's instruction could seed; tasks implementation-agnostic (no assumed labels/layouts/mechanisms beyond what instructions requested); global rules domain-specific (no generic counter/money cliches; <=2 counter-check tasks per ladder); every turn substantially complex. Overwrite ${partPath(idx)} with the corrected single-line JSON (same schema).`,
        { label: `repair-${String(idx).padStart(3, '0')}`, phase: 'Verify', model: 'opus' }
      )
      verdict = await agent(verifyPrompt(idx), { label: `reverify-${String(idx).padStart(3, '0')}`, phase: 'Verify', schema: VERDICT })
    }
    return { idx, status: verdict ? (verdict.ok ? 'ok' : 'still-failing') : 'verify-failed', violations: verdict ? verdict.violations : ['verifier died'] }
  }
)

const summary = results.filter(Boolean)
const clean = summary.filter((r) => r.status === 'ok').map((r) => r.idx)
const dirty = summary.filter((r) => r.status !== 'ok')
log(`Verified clean: ${clean.length}/${indices.length}; problems: ${dirty.map((r) => `${r.idx}:${r.status}`).join(', ') || 'none'}`)

if (pilot) {
  log('Pilot mode: skipping assembly — inspect the part files in evoweb_main_dataset/.')
  return { pilot: true, clean, dirty, parts: indices.map(partPath) }
}

phase('Assemble')
// Assembly is DETERMINISTIC: one bash call to data_gen/assemble_dataset.py, not an agent
// authoring a merge script. The merge has nothing to reason about, and a free-form assembly
// agent can lose a completed multi-hour run on a session limit. Only clean parts are merged.
const assembled = await agent(
  `Run EXACTLY this one command with Bash and report its stdout verbatim. Do not read or write any other file, and do not write a script of your own:\n\npython3 ${SCRIPTS}/assemble_dataset.py --parts ${DATA}/evoweb_main_dataset --out ${DATA}/evoweb_benchmark.jsonl --clean ${clean.join(',')}`,
  { label: 'assemble-jsonl', phase: 'Assemble' }
)

log(`Assembly: ${assembled}`)
return { clean, dirty, out: `${DATA}/evoweb_benchmark.jsonl`, assembly: assembled }

// ╔════════════════════════════════════════════════════════════════════════════╗
// ║  nine-hard-v5_no_grounding.js — v5 ABLATION #2: real-website GROUNDING       ║
// ║                                  REMOVED                                     ║
// ║                                                                              ║
// ║  Ablation of `nine-hard-v5-chained.js`. Everything the v5 spec does is kept  ║
// ║  BIT-FOR-BIT except the one lever under test: **grounding in real websites'  ║
// ║  features**. Purpose: measure how much of v5's difficulty and realism comes  ║
// ║  from mining `similar_websites.json` versus from the generator inventing     ║
// ║  features for the domain unaided. See the paper's ablation appendix.                    ║
// ║                                                                              ║
// ║  The ablation is defined ENTIRELY by what the generator is NOT GIVEN: the     ║
// ║  scraped real-feature corpus is withheld and the generator is asked to        ║
// ║  INVENT instead. No prohibition rules are added anywhere — no "don't name a   ║
// ║  real product" clause in the prompt, none in the verifier, none in the        ║
// ║  repair pass. Withholding the input IS the treatment.                        ║
// ║                                                                              ║
// ║  ── WHAT IS REMOVED (the ablated lever) ──                                   ║
// ║  NG-1  NO similar_websites.json: the generator never reads it. Its STEP 1    ║
// ║        input is the base build prompt ALONE. (This also makes the generator   ║
// ║        strictly blinder than v5 — the only external corpus is gone.)          ║
// ║  NG-2  NO source_website / source_feature: those schema fields are gone from  ║
// ║        every follow-up; there is no real feature to point back at. Replaced   ║
// ║        by `feature_rationale` — one line on why this invented feature is a    ║
// ║        natural next milestone for THIS app's users.                          ║
// ║  NG-3  NO "ADAPT THE REAL FEATURES" rule: replaced by INVENT FROM THE DOMAIN  ║
// ║        — features are derived from first principles about the app's users and ║
// ║        their workflow. Purely positive framing; nothing is banned.            ║
// ║  NG-4  Verifier rule 2 no longer checks source fields. The engineering bar    ║
// ║        that grounding used to guarantee (features that need real work, not    ║
// ║        cosmetics) is stated DIRECTLY as a requirement, so the ablation        ║
// ║        removes the source of ideas, not the difficulty target.                ║
// ║  NG-5  ANTI-ANCHORING (V5-1) DROPPED: the global-rule originality clause      ║
// ║        ("invent conventions, never reuse an example from this prompt, avoid   ║
// ║        the counter/money cliches") and the verifier's ORIGINALITY check are    ║
// ║        gone. Global rules are still required and still invented per domain,   ║
// ║        just not policed for anchoring. The V5-2 counter cap stays.            ║
// ║                                                                              ║
// ║  ── WHAT IS DELIBERATELY KEPT (so the comparison isolates one variable) ──   ║
// ║  · THE FULL DAG: back-translated grown-app feature graph, 3-4+ significant    ║
// ║    dependencies, one chain >= 3 deep, dependency_graph recorded, integration  ║
// ║    task slot (that is ablation #1)                                            ║
// ║  · intrinsic hardness: non-trivial sub-problem per turn (v4 RESTORE-A),      ║
// ║    per-archetype hardness specs (RESTORE-B), bundled requirements (RESTORE-C)║
// ║  · pinned seed + exact-value tasks · global rules (invented per domain)       ║
// ║  · verbatim regression slot · distinctness · harness-possible                 ║
// ║  · implementation-agnostic tasks · per-turn complexity floor · counter cap    ║
// ║  · archetype mix · minimal tester work · click/type-only tester limits        ║
// ║  · verify + one repair pass · missing-tolerant assembly                       ║
// ║                                                                              ║
// ║  Same 32 study ladder indices as evoweb_benchmark.jsonl (the ablation must be         ║
// ║  measured on the SAME apps as the control).                                    ║
// ║  Output: ablation_no_grounding.jsonl /                                   ║
// ║  ablation_dataset_no_grounding/. Pilot mode: args {samples: [..]} generates a few  ║
// ║  and skips assembly.                                                         ║
// ║                                                                              ║
// ║  ── v5 SPEC INHERITED (see nine-hard-v5-chained.js for the full history) ──  ║
// ║  V5-2 counter cap (<= 2 list-count checks per ladder) · V5-3 varied archetype ║
// ║       mix · V5-4 implementation-agnostic tasks · V5-5 per-turn complexity     ║
// ║       floor. Plus v4.1's DEP-1..DEP-5 dependency model, v4's RESTORE-A/B/C,   ║
// ║       and v3's DAG / exact-value / global-rule / regression / verify-repair   ║
// ║       machinery. (V5-1 anti-anchoring is dropped — see NG-5.)                 ║
// ╚════════════════════════════════════════════════════════════════════════════╝

export const meta = {
  name: 'nine-hard-v5-no-grounding-fable',
  description: 'v5 ABLATION #2 (no grounding): the v5 ladder generator with the real-website feature corpus withheld — similar_websites.json is never read and source_website/source_feature are gone, so the generator must INVENT every feature from the app domain from first principles. Withholding the input is the whole treatment: no prohibition rules are added in the prompt or the verifier, and V5-1 anti-anchoring is dropped. Everything else is v5 verbatim: the full DAG dependency model (significant edges, one chain >= 3 deep, integration slot), intrinsic hardness, pinned seed + exact-value tasks, global rules, verbatim regressions, distinctness, implementation-agnostic tasks, per-turn complexity floor. Verify + repair each sample, then assemble ablation_no_grounding.jsonl (skipped in pilot mode).',
  phases: [
    { title: 'Generate', detail: 'Per-sample: invent a target-app DAG from the domain alone, write 9 chained follow-ups', model: 'fable' },
    { title: 'Verify', detail: 'Per-sample compliance check (banned controls, DAG depth/significance, verbatim regressions, exact-value coverage, intrinsic hardness) + one repair pass' },
    { title: 'Repair', detail: 'repairOnly mode: re-verify + repair existing parts for the named samples, up to `rounds` rounds', model: 'fable' },
    { title: 'Assemble', detail: 'Write ablation_no_grounding.jsonl (full runs only; pilot skips this)' },
  ],
}

// Data dir of the worktree this runs in (check before dispatch — v5 ran from a Mac checkout).
// The 32 study ladder indices — identical to evoweb_benchmark.jsonl, so the ablation is measured
// on the SAME apps as the v5 control (that is what makes the score delta attributable).
const FULL = [1, 4, 6, 11, 14, 15, 17, 18, 21, 23, 30, 31, 33, 35, 38, 40, 41, 42,
              44, 47, 48, 50, 51, 58, 61, 67, 69, 70, 73, 78, 91, 93]
// Pilot mode: Workflow args {samples: [1, 14, 30]} generates only those and skips assembly.
// args may arrive JSON-string-encoded (bit us on the first v3 pilot run: fell back to FULL) — parse defensively.
const parsedArgs = typeof args === 'string' ? JSON.parse(args) : args
// Where this repository keeps its datasets: <clone>/data (evoweb/paths.py's DATA).
// The Workflow sandbox has no __dirname, so pass it as an arg {data: '/abs/.../data'}
// or edit the fallback below to your clone's absolute path before dispatching.
const DATA = (parsedArgs && parsedArgs.data) || '/ABSOLUTE/PATH/TO/EvoWeb/data'
const SCRIPTS = `${DATA}/data_gen`   // assemble_dataset.py, audit_parts.py
const indices = (parsedArgs && parsedArgs.samples) || FULL
// Repair-only mode: {repairOnly: true, samples: [dirty...], clean: [already-clean...], rounds: 2}
// Re-verifies and repairs EXISTING part files without regenerating them, then re-assembles from the
// union of already-clean and newly-clean samples. The study's exclusion discipline is ~3-4 repair
// rounds before dropping a sample (repair loops start MANUFACTURING violations past that), and one
// inline pass is all the generation pipeline does — this is how rounds 2+ get run.
const repairOnly = Boolean(parsedArgs && parsedArgs.repairOnly)
const alreadyClean = (parsedArgs && parsedArgs.clean) || []
const rounds = (parsedArgs && parsedArgs.rounds) || 2
const pilot = Boolean(parsedArgs && parsedArgs.samples) && !repairOnly

// [unchanged from v5]
const TASK_ITEM = {
  type: 'object',
  properties: {
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
    // ═══ NG-2: source_website / source_feature REMOVED — nothing to attribute ═══
    feature_rationale: { type: 'string', description: 'One line: why this INVENTED feature is a natural next milestone for this app\'s own users and workflow.' },
    ui_instruct: { type: 'array', minItems: 5, maxItems: 5, items: TASK_ITEM },
  },
  required: ['archetype', 'instruction', 'feature_rationale', 'ui_instruct'],
}

// [unchanged from v5 — the whole DAG apparatus is KEPT in this ablation]
const SCHEMA = {
  type: 'object',
  properties: {
    app_idx: { type: 'number' },
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
    global_rules: {
      type: 'array', minItems: 2, maxItems: 3,
      items: {
        type: 'object',
        properties: {
          rule: { type: 'string', description: 'An app-wide convention INVENTED for this app\'s domain (formatting, naming, badge coding, ordering, interaction or state-display convention).' },
          introduced_in_turn: { type: 'number', description: 'The turn whose instruction states this rule (naturally, as a user preference).' },
        },
        required: ['rule', 'introduced_in_turn'],
      },
    },
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

const partPath = (idx) => `${DATA}/ablation_dataset_no_grounding/${String(idx).padStart(6, '0')}.json`

const genPrompt = (idx) => `You are generating a NINE-turn chained follow-up ladder (turns 2-10) for a long-horizon web-dev benchmark. Weak models must score near zero on the late turns; strong models should reach the middle. The lever is DEPENDENCY: later turns must genuinely stand on earlier turns' work, so breakage and shallow implementations compound. Every feature in this ladder is INVENTED BY YOU from the app's own domain — you have no catalogue of real-world features to draw on.

## STEP 1 — read your input (you are BLIND to the finished app, and you have NO feature corpus)
Read line ${idx} (1-indexed) of ${DATA}/legacy_webgen_bench_apps.jsonl. Its "instruction" field is the base-app BUILD PROMPT. This is your ONLY input. You see the prompt, NOT the finished app, so never assume a specific implementation detail, page, or field exists beyond what the prompt asked for. Your ladder REPLACES any older follow-ups entirely; do not read or reuse them. There is no feature catalogue to consult — every feature in this ladder is yours to invent.

## STEP 2 — design the GROWN app first, as a feature graph, then slice it (back-translation)
Imagine this base app a year later, grown into a much BIGGER product for its domain. Design 9 MAJOR features — each one an epic-sized module a real team would ship as its own milestone, often with its own page or section. NOT small tweaks, single widgets, or slices of one narrow product vision: the 9 features may pull the app in several different directions (analytics, workflows, discovery, tooling, planning, community...) as long as each fits the app's domain and users. Do NOT shrink features to make them fit together — size each one as if it were the only thing being asked for that week. SOME of the 9 genuinely build on each other; standalone features are fine, but the connections you do create must be real and significant (rules below). Then cut the graph into turns 2-10 in a valid topological order (every dependency built before its consumer). Requirements:
- INVENT FROM THE DOMAIN (this ladder's defining rule): design every feature yourself, from first principles about THIS app's users — who they are, what they are trying to get done, what a serious version of this tool would owe them, where their workflow would strain as their data grows. Reason from the users' jobs to the feature. Record a one-line feature_rationale per turn saying why that feature is the natural next milestone for these users.
- ENGINEERING WEIGHT IS ON YOU: with no feature catalogue to draw on, you must aim deliberately at features that need REAL engineering — multi-criteria filtering/screeners, cross-filtering, ranking with ties, aggregations/rollups, calculators, debounced search, pagination interacting with filters/sort, computed exports, validation-heavy workflows. Cosmetic features only inside the design-restyle archetype.
- CORRECTNESS MUST HINGE ON A NON-TRIVIAL SUB-PROBLEM in EVERY follow-up (this is the load-bearing per-feature hardness rule; a feature whose only hard part is "consumes an earlier turn" is NOT enough). Each feature's correctness must turn on at least one of: correct boolean composition (AND across dimensions, OR within one); a count/total that stays exactly consistent with the filtered/visible set as it changes; stable & correct sorting including ties and mixed types; exact computed values with correct rounding/units; correct empty/boundary/first-load handling; precise input validation; for design-restyle — full cross-page consistency. A naive/shallow build must get this sub-problem WRONG. State the expectation in the instruction, embedded naturally per STEP 3's wording rule, never as a formal spec clause.
- BUNDLE SEVERAL INTERACTING REQUIREMENTS per feature: each follow-up is a rich feature with multiple controls/states/rules that interact, NOT a lone control. E.g. a screener with saved presets AND a live result counter AND a computed export — not a single filter; a workflow with validation AND a review step AND persistence — not one button. The interacting requirements are part of what a weak model fails to keep mutually consistent.
- SIGNIFICANT DEPENDENCIES, YOUR CHOICE OF SHAPE: you decide which turns build on earlier ones and HOW — a connection can take any form that fits this app (aggregate an earlier feature's output, drive it from a new control, cross-validate against it, reconcile two earlier features, gate a flow on it, embed or extend it...). Invent what's natural for the domain; there is no mandated shape. Not every turn needs a dependency. But every connection you DO declare must be SIGNIFICANT: the later feature must genuinely rely on the earlier one, such that if the earlier feature were missing or broken, the later one could not do what its instruction asks for. Merely reading the same seeded records as an earlier turn is NOT a dependency and must not be declared as an edge. Create AT LEAST 3-4 such significant dependencies across the 9 turns, arranged so at least one chain runs >= 3 deep from T1 (a feature relying on a feature relying on a feature) — deep chains are what make early breakage compound.
- EVERY FEATURE IS A DISTINCT NEW CAPABILITY: each follow-up must introduce a capability that neither the base app nor any other turn already provides — a different core operation on a different UI surface. Relying on an earlier feature is good; RESEMBLING its function is the failure: never build two features of the same kind (two filterable lists, two calculators, two savable tables, two dashboards) even if one references the other, and never re-implement or lightly re-skin something the base app was already asked to have.
- RECORD THE GRAPH: output dependency_graph with all 10 nodes (T1 "base app" + T2-T10) and an edge for every SIGNIFICANT reliance, each labeled with WHAT the later feature relies on and how (e.g. "aggregates the tracker's logged expenses", "gates checkout on the validator's result"). Edges only point forward; standalone turns simply have no incoming T2+ edge. This is our audit trail and gets rendered in a viewer — make labels short and honest. The implementer NEVER sees it. COMPLETENESS still applies where reliance exists: design-restyle turns need an edge for EACH feature they restyle, and a turn that materially leans on a base-app page/surface needs a T1 edge; under-declared restyle/base edges were the #1 audit failure.
- ARCHETYPE MIX: use at least 3 of the four archetypes across the 9 turns, at most 4 turns of any one, never the same archetype twice in a row — and let the allocation follow THIS app's natural shape rather than a fixed quota. Interactive-tool turns are the natural low-dependency ones — place them early, then wire later turns to consume their outputs where it fits. Each archetype carries its OWN hardness spec, which the feature must satisfy:
  (a) DERIVED-STATE: computes/aggregates/ranks over seeded or earlier-turn records (rollups, windowed stats, cross-filters). ARRANGE THE SEED so a naive implementation produces a VISIBLY DIFFERENT result from the correct one (e.g. a windowed/most-recent order differs from all-time order; a tie forces a specific tiebreak; a rounding edge changes a displayed total) — so the exact-value task actually discriminates.
  (b) INTERACTIVE TOOL: driven purely by the user's typed inputs — calculators, configurators, live meters/previews. State MUST update correctly DURING interaction (per keystroke/field/click), not only on a final submit.
  (c) MULTI-SURFACE WORKFLOW: a flow spanning 2+ pages/views (create -> review -> resolve) where EVERY required action stays visible and reachable — nothing gated behind an implicit role, hover, or hidden state the click-only tester can't reach.
  (d) DESIGN RESTYLE: a bundle of 4-6 SPECIFIC visual requirements (primary action color, heading alignment, card spacing/radius, a badge style, a typography rule) applied CONSISTENTLY across at least 3 named pages — PARTIAL APPLICATION (some pages updated, others missed) is exactly the failure being tested. Invent the visual language for this app.
- FAIRNESS RULE (critical, because you are blind): every dependency must be expressed through USER-VISIBLE behavior an earlier instruction EXPLICITLY asked to build — never through assumed implementation details. If turn 7 needs turn 3's records, turn 3's instruction must have clearly created them. Different valid implementations of earlier turns must all be able to support later turns.
- PINNED SEED: exactly one early turn (2 or 3) pins an exact small dataset in its instruction — spell out ~5-8 records with exact names/numbers, phrased casually ("start me off with these six: Maple Duplex at $1,850/mo, 2 units, ... — exactly these, I'll add more later"). Later derived-state turns compute over THESE records so exact expected values exist.
- GLOBAL RULES: 2-3 app-wide conventions, each introduced naturally inside some early turn's instruction as a user preference, with the app-wide scope stated ("everywhere in this app, now and for anything we add later"). Pick from different CLASSES: value formatting (units, precision, notation), naming/labeling schemes, color/badge coding, ordering/grouping conventions, interaction conventions (confirmations, undo, defaults), state display (how statuses/progress are shown). Later turns' instructions do NOT restate them — compliance is tested silently.
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
2. STRUCTURE: exactly 9 follow_ups, each with a one-line feature_rationale, exactly 5 ui_instruct tasks with kinds = 3x feature/exact-value + 1 integration + 1 regression, in that slot order.
3. REGRESSIONS VERBATIM: every regression task's task+expected_result strings appear character-for-character in the ui_instruct of the turn named by copied_from_turn (turn 2's may target the base app, copied_from_turn=1, using only behavior the base build prompt asked for). Across the ladder, at least 5 of turns 2-9 are re-tested by a later regression (full coverage NOT required — varied gaps and dependency-focused targets beat a mechanical k-1 chain).
4. DAG + DEPENDENCY SIGNIFICANCE: dependency_graph has all 10 nodes T1-T10; every edge points strictly forward; the longest path from T1 reaches depth >= 3; at least 3 edges land on a T2+ target (i.e. at least 3 significant follow-up-on-follow-up dependencies exist — standalone turns are allowed, no per-turn quota). SIGNIFICANCE: for EACH edge, the consuming turn's instruction must genuinely rely on the earlier feature — if that earlier feature were missing or broken, the later feature could not do what its instruction asks. Flag any edge whose only basis is that both turns read the same seeded records. CONSISTENCY: every edge corresponds to something the consuming instruction actually leans on, and every earlier-work reference in an instruction has a matching edge. FAIRNESS: every relied-on artifact was explicitly requested by the earlier instruction (the generator is blind — flag any dependency on assumed implementation details).
5. EXACT VALUES: a pinned_seed turn exists (turn 2 or 3) whose instruction spells out exact records; from that turn on every turn has >= 1 exact-value task whose expected constant is actually derivable from those records (recompute it yourself; flag any wrong constant — a wrong constant poisons the eval).
6. GLOBAL RULES: 2-3 rules, each introduced naturally in an early instruction with app-wide scope; at least 2 later turns have a task verifying a global rule on a NEW surface; no later instruction restates the rule. COUNTER CAP: flag any ladder where more than 2 tasks total verify a list-count convention.
7. LANGUAGE + TASK ECONOMY: instructions read like a casual user (no "turn N", no spec clauses); archetypes never repeat back-to-back, at least 3 archetypes are present, and no archetype exceeds 4 turns; no task needs more than ~6 operations. MINIMAL WORK: flag any task that isn't the simplest interaction proving its check — more actions, entities, or repetitions than needed. NO SETUP/FREE CHOICES: flag any task that makes the tester set up state or invent values (create records, configure things, pick arbitrary names/amounts) when that data could have been seeded by the turn's instruction.
8. HARNESS-POSSIBLE: nothing anywhere requires external/third-party APIs or live data, AI/LLM functionality, email/SMS/push sending, auth/login/roles, file uploads, real-time sync, the actual current date/time (static labels like "This Week" over seeded data are fine), or file downloads (exports must show their output on screen). Flag any feature a fully offline client-side React app with seeded local data could not implement, or any expected_result the click/type-only tester could not observe on screen.
9. INTRINSIC HARDNESS: every follow-up's correctness must hinge on a non-trivial sub-problem (boolean composition, count-consistent-with-visible-set, stable sort incl. ties, exact rounding/units, empty/boundary handling, or input validation) — flag any feature whose only difficulty is "it depends on an earlier turn" or that a shallow build would trivially get right. Every follow-up must BUNDLE several interacting requirements, not be a lone control. And each archetype must meet its own spec: derived-state seeds must be arranged so a naive build VISIBLY differs (flag exact-value tasks whose constant a naive implementation would also produce); interactive-tool must update per keystroke/field/click; multi-surface must keep every required action reachable by clicks alone; design-restyle must list 4-6 specific rules across >=3 named pages with partial application as the tested failure.
10. DISTINCTNESS: every follow-up must be a NEW capability — a different core operation on a different UI surface from the base app's requested features and from every other turn. Flag any pair of turns that are the same kind of feature (two filterable lists, two calculators, two savable tables, two dashboards, two search boxes), and any turn that re-implements or lightly re-skins something the base build prompt already asked for. Relying on an earlier feature (a declared edge) is NOT a violation — resembling its function is.
11. IMPLEMENTATION-AGNOSTIC TASKS: the builder never sees the generator's imagined design, and there are endless valid ways to implement each instruction — flag any task or expected_result that assumes an implementation detail the instructions never requested (a specific button label, page layout, widget type, message wording, or mechanism). Every check must pass on ANY reasonable implementation of the instructions.
12. PER-TURN COMPLEXITY: judge EVERY turn's feature on engineering weight — it must be substantially complex, demanding advanced capability (multi-component state, real logic per rule 9, several interacting requirements, its own surface). Flag any turn that is widget-sized, a trivial variation of standard CRUD, or that a competent model could complete with a few lines — every turn must be a real milestone.
Return { ok, violations }.`

// The repair instruction, shared by the inline pass and repair-only mode so there is ONE wording.
const repairPrompt = (idx, violations) =>
  `${partPath(idx)} failed audit with these violations:\n${violations.map((v) => `- ${v}`).join('\n')}\n\nFix ONLY what the violations require — keep everything compliant untouched. Rules recap: verbatim regressions with correct copied_from_turn; >=1 exact-value task per turn from the pinned-seed turn on, with constants recomputed from the pinned records AND the seed arranged so a naive build would show a different constant; every feature's correctness hinges on a non-trivial sub-problem and bundles several interacting requirements (not a lone control); each archetype meets its hardness spec (derived-state visibly differs from naive, interactive-tool updates per keystroke, multi-surface actions reachable by clicks, design-restyle 4-6 rules on 3+ pages); dependency_graph consistent with the instructions, longest path depth >= 3, at least 3 SIGNIFICANT follow-up-on-follow-up edges (the later feature genuinely relies on the earlier one; shared seed data does not count as an edge; standalone turns are allowed); every follow-up a DISTINCT new capability (no two turns of the same kind, nothing re-implementing a base feature); no banned controls or the words slider/drag/hover; casual user voice, no "turn N"; each task the simplest interaction that proves its check, never asking the tester to set up data the turn's instruction could seed; tasks implementation-agnostic (no assumed labels/layouts/mechanisms beyond what instructions requested); 2-3 app-wide global rules introduced early and tested silently on later surfaces (<=2 counter-check tasks per ladder); every turn substantially complex. Overwrite ${partPath(idx)} with the corrected single-line JSON (same schema).`

let clean, dirty

if (repairOnly) {
  // ── Repair-only: no generation. Verify each named sample, repair, re-verify, up to `rounds`. ──
  phase('Repair')
  const repaired = await pipeline(
    indices,
    async (_unused, idx) => {
      let verdict = await agent(verifyPrompt(idx), { label: `verify-${String(idx).padStart(3, '0')}`, phase: 'Repair', schema: VERDICT })
      let round = 0
      while (verdict && !verdict.ok && round < rounds) {
        round += 1
        await agent(repairPrompt(idx, verdict.violations),
          { label: `repair${round}-${String(idx).padStart(3, '0')}`, phase: 'Repair', model: 'fable' })
        verdict = await agent(verifyPrompt(idx), { label: `reverify${round}-${String(idx).padStart(3, '0')}`, phase: 'Repair', schema: VERDICT })
      }
      return { idx, rounds: round, status: verdict ? (verdict.ok ? 'ok' : 'still-failing') : 'verify-failed', violations: verdict ? verdict.violations : ['verifier died'] }
    }
  )
  const summary = repaired.filter(Boolean)
  const fixed = summary.filter((r) => r.status === 'ok').map((r) => r.idx)
  dirty = summary.filter((r) => r.status !== 'ok')
  clean = [...new Set([...alreadyClean, ...fixed])].sort((a, b) => a - b)
  log(`Repair: fixed ${fixed.length}/${indices.length} (${fixed.join(', ') || 'none'}); still failing: ${dirty.map((r) => `${r.idx}`).join(', ') || 'none'}; total clean now ${clean.length}`)
} else {

phase('Generate')
const results = await pipeline(
  indices,
  (idx) => agent(genPrompt(idx), { label: `gen-${String(idx).padStart(3, '0')}`, phase: 'Generate', schema: SCHEMA, model: 'fable' }),
  // ═══ [unchanged v3 CHANGE #6] verify each sample as soon as it lands; one repair pass on failure ═══
  async (gen, idx) => {
    if (!gen) return { idx, status: 'generation-failed' }
    let verdict = await agent(verifyPrompt(idx), { label: `verify-${String(idx).padStart(3, '0')}`, phase: 'Verify', schema: VERDICT })
    if (verdict && !verdict.ok) {
      await agent(
        repairPrompt(idx, verdict.violations),
        { label: `repair-${String(idx).padStart(3, '0')}`, phase: 'Verify', model: 'fable' }
      )
      verdict = await agent(verifyPrompt(idx), { label: `reverify-${String(idx).padStart(3, '0')}`, phase: 'Verify', schema: VERDICT })
    }
    return { idx, status: verdict ? (verdict.ok ? 'ok' : 'still-failing') : 'verify-failed', violations: verdict ? verdict.violations : ['verifier died'] }
  }
)

const summary = results.filter(Boolean)
clean = summary.filter((r) => r.status === 'ok').map((r) => r.idx)
dirty = summary.filter((r) => r.status !== 'ok')
log(`Verified clean: ${clean.length}/${indices.length}; problems: ${dirty.map((r) => `${r.idx}:${r.status}`).join(', ') || 'none'}`)

if (pilot) {
  log('Pilot mode: skipping assembly — inspect the part files in ablation_dataset_no_grounding/.')
  return { pilot: true, clean, dirty, parts: indices.map(partPath) }
}

}

// [unchanged pattern] missing-tolerant assembly via a Python script; only clean parts are merged.
phase('Assemble')
// Assembly is DETERMINISTIC: one bash call to scripts/assemble_dataset.py, not an agent
// authoring a merge script. Twice on 2026-08-04 a free-form assembly agent cost a completed
// multi-hour run its output — once by dying on a session limit, once by silently rewriting the
// dataset with a smaller sample set. The merge has nothing to reason about.
const assembled = await agent(
  `Run EXACTLY this one command with Bash and report its stdout verbatim. Do not read or write any other file, and do not write a script of your own:\n\npython3 ${SCRIPTS}/assemble_dataset.py --parts ${DATA}/ablation_dataset_no_grounding --out ${DATA}/ablation_no_grounding.jsonl --clean ${clean.join(',')}`,
  { label: 'assemble-jsonl', phase: 'Assemble' }
)

log(`Assembly: ${assembled}`)
return { clean, dirty, out: `${DATA}/ablation_no_grounding.jsonl`, assembly: assembled }

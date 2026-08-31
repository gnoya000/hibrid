# Architectural decisions and their reasoning

Every decision here was argued through and chosen. [HANDOFF.md](../HANDOFF.md)
lists them in one line each; this file carries the full argument, so that
someone who wants to challenge one can see what it rests on.

**If you think one of these is wrong, say so explicitly rather than silently
"fixing" it.** Several look like inconsistencies or oversights until you know
the reason.

---

## Data and storage

### Health data stays on the device

Personal data splits by class, and the split is the entire safeguard.

**Stored server-side:** identity, profile, preferences, goals, plans and
routines, the training log, derived progress.
**Never stored server-side:** `HealthProfile`, `Injury`, `MedicalConsideration`,
`BodyComposition`, `RecoveryReading`, `WellnessCheckIn`, `CardiovascularFitness`,
`FitnessAssessment`. These reach the engine as request-scoped inputs and are
forgotten.

The reasoning was never about personal data in general. It is about
**special-category health data** (GDPR Art. 9), which pulls in explicit consent,
a DPIA, records of processing, erasure handling and 72-hour breach notification
— and which Apple's HealthKit terms, App Store Guideline 5.1.3 and Google's
Health Connect policy restrict contractually, enforced at app review long before
a regulator is involved. Keeping that class off the server keeps all of it off
the company. The rest is ordinary personal data: still GDPR, an order of
magnitude cheaper to hold.

Note that a random account key does **not** change this. Pseudonymised data is
still personal data under Art. 4(5) and Recital 26; a secret that resolves to a
record containing injuries is still processing special-category data. The split
by class is what does the work, not the anonymity of the key.

**Working rule:** do not add a table, column or log line holding a value from
the health bucket, and do not `repr()` one into an error message. If a feature
seems to need health data at rest, that is a decision to escalate, not to
implement.

**Accepted residual risk.** Activity data may qualify as consumer health data
under Washington's My Health My Data Act, which carries a private right of
action; the FTC Health Breach Notification Rule also reaches health apps
regardless of HIPAA. Get legal advice before public launch. Two leak paths
remain wherever the health bucket lives: device backup (a copy of HealthKit data
is not automatically excluded from iCloud/Drive backup) and analytics or crash
SDKs carrying health values in breadcrumbs.

### The account key, and why the client never sends a user id

The device holds one secret; the server resolves it to an `account_id` and fills
in `user_id` itself. A client that asserts an identity is rejected.

This keeps every ownership validator in `hibrid.user` meaningful — they catch
genuine cross-account bugs rather than becoming formalities — and it means
`Account.account_id` **is** `UserProfile.user_id`, with no second identity to
reconcile.

Credentials are modelled as a collection rather than a column so that adding
email recovery or OAuth later is an insert, not a schema change. The full model
is in [api-v1-draft.md](api-v1-draft.md#2-the-account-model).

**Accepted for now:** a lost key means a lost account. Any real recovery path
needs a second factor, which needs an identity — the credential model is what
keeps that door open without forcing the decision today.

### The schema stays graph-projectable

Stable IDs, relationships as ID references, `PerformedSet` shaped as a
relationship-with-properties. This is what makes moving to a server store cheap
rather than a migration: a relationship-with-properties is exactly a join row,
and every independent fact already carries its own `user_id` with an ownership
validator. Do not undo it.

### Anything measurable and changeable is a dated immutable snapshot

Including height. Corrections append a superseding record; they never mutate.

The question that actually drives a deload decision — "is this user's HRV
suppressed relative to their own 28-day baseline?" — is unanswerable from a
current-value field. Age is likewise never stored, only `birth_date`, because a
stored age is wrong the day after it is written.

### Prescribed and performed are both recorded

A user told `4x8@80` who did `4x6@80` at RPE 10 has said something a bare log
cannot express. Adherence is a first-class signal: a routine repeatedly skipped
is a failed prescription regardless of its physiological merit.

---

## Modelling

### Two model styles is a boundary, not an inconsistency

`hibrid.models` stays on **stdlib dataclasses**: internal, built from trusted
repo-local YAML, and on the variation engine's hot path where per-instance
validation costs real time during candidate search.

`hibrid.user` and `hibrid.api` use **pydantic v2**: both ingest untrusted
external data — device exports, API payloads, forms. `extra="forbid"` is
load-bearing; a renamed device field must raise at ingestion, not vanish and
resurface months later as a mysteriously absent feature.

### Enums are shared, never forked

`Equipment` and `MovementPattern` are defined in `hibrid.models` and re-exported
by `hibrid.user.enums`. Two divergent copies of a movement vocabulary would
break every join between a routine and a user's history. `Weekday` will get the
same treatment when the weekly plan lands.

### `Muscle` is a closed enum, and free text must never re-enter it

The upstream dataset spells the same muscle several ways (`traps`/`trapezius`,
`lats`/`latissimus dorsi`, `quads`/`quadriceps`). Substitution matches on shared
muscles, so an unnormalised value does not error — it silently stops matching
its own equivalents, and nothing in the output reveals that a candidate was
dropped. Synonyms are resolved once, at import.

### Objectives are a normalised weight vector, not a mode

Real users want blends ("mostly strength, some mobility"), and an engine trading
qualities off needs the trade-off stated numerically rather than inferred from a
single enum. `FitnessAssessment.component_scores` is keyed by the same enum, so
the engine can compare where the user *is* against where they want to *be*,
dimension by dimension.

### Hard constraints are separate from soft preferences

Health constraints are inviolable bounds; equipment and time are hard
constraints; dislikes and novelty appetite are soft cost terms. Contraindications
are explicit ID and enum sets, never free text, so a planner can mechanically
exclude work instead of interpreting a note.

---

## The engine

### The engine core stays pure

`hibrid.models`, `variation.py`, `objective_strategy.py`, `variation_context.py`,
`readiness.py`, `training_memory.py`, `progression.py`, `load_management.py` and
`exercise_db.py` are pure functions over value objects — no I/O, no database
session, no network, no clock they did not receive as a parameter.

The Rust port that originally justified this is shelved (below), but the rule
survives on its own merits: purity is what makes the engine trivially testable
(454 tests in ~2s with no fixtures beyond the library) and what keeps a future
native client possible. Persistence and HTTP live at the edges and call *into*
the engine, never the reverse.

### The engine stays deterministic and explainable, not learned

The original argument was that no cloud means no data flywheel. That half is
gone — a backend can collect longitudinal adherence and outcome data. What still
holds:

- The product must be good on day one for a user with an empty history, which is
  exactly where a learned system is weakest.
- A deterministic engine can explain itself to a user who disputes it.

*Adaptive per-user statistics remain the pattern to extend.* `readiness.py` is
the template: personal baseline, deviation from it, explicit `UNKNOWN` when the
data is thin, and a sentence saying why. Revisit the ML question when there is
real outcome data, not before.

### Each objective chooses the invariant its variation preserves

`vary_entry` originally held one thing for every objective: `sets × reps ×
weight`, solving the load per candidate scheme. That is right for hypertrophy
and muscular endurance, where total work is what drives the adaptation. It is
**inverted** for strength, where proximity to maximum is the adaptation and
total work is a by-product — so holding volume and solving load makes the one
variable that matters the free one.

The failure is not theoretical and not small. A `4×4 @ 100 kg` strength entry
had 23 candidate schemes that preserved both volume and time within the default
tolerances, spanning `6×6 @ 45 kg` to `3×1 @ 532.5 kg`. Every one of them was
reported as `VARIED`. Training memory did not bound it either: the reference
load anchors the *volume* target, and the solved candidate weight still floats
by the ratio of scheme sizes, so even a user with perfect history could be
handed five times their working weight.

So `ObjectiveStrategy.variation_policy` names the invariant, and `vary_entry`
branches on it. Under `Invariant.INTENSITY` the load is pinned at the reference
and the scheme waves around it, with total work becoming what the tolerance
judges.

*Two consequences worth knowing, because both look like accidents and are not:*

- **The adaptive multiplier stays on the volume target** rather than moving onto
  the load. Under `INTENSITY` a deload or a taper therefore takes sets away and
  leaves the bar where it is — which is what both are for, and which closes the
  "a taper lowers load" gap as a side effect rather than as a separate fix.
- **A held prescription is a correct answer, not a failed search.**
  `UNVARIED_HOLDING_INTENSITY` exists because strength is trained by repeating a
  movement: the load moves through progression once the session is logged, not
  through the scheme search. Reporting that as
  `UNVARIED_NO_CANDIDATE_WITHIN_TOLERANCE` would tell a user the engine failed
  when it did the right thing.

Do not "fix" this by making the invariant a caller parameter. It is a property
of the training objective, and a caller free to ask for volume-preservation
under a strength objective is a caller free to reintroduce the bug.

### Training correctness outranks stated preference

`novelty_preference` is documented in the schema as the dial `substitution_prob`
should derive from, and it does. But the objective's
`VariationPolicy.max_substitution_prob` **caps** the result, whatever the source
— including an explicit caller argument.

That looks like ignoring the user, and is the opposite. Strength is a
movement-specific motor skill, and `TrainingMemory` is keyed on the exercise, so
a substitution discards the history the progression layer reads. Above some
rotation rate the engine is not offering variety, it is quietly disabling its own
progression — at the schema's `novelty_preference` default of 0.5, a movement had
a 6% chance of surviving four sessions.

This is the existing hard-vs-soft tiering extended by one rank: health is
inviolable, equipment and time are hard constraints, **how often a movement may
rotate and still be trainable is a property of the objective**, and dislikes and
novelty are soft cost terms below all of it. A preference that silently defeats
the progression layer is not a preference, it is a bug with a dial on it.

The cap is never silent — `RoutineVariation.substitution_prob` reports the value
actually used, for the same reason `load_multiplier` is carried there.

### The scheme search stays near the current scheme

`candidate_rep_schemes` searches ±2 sets / ±4 reps around what the entry already
prescribes, then clips to the objective's range. An entry far outside that range
therefore yields no candidates and is returned unchanged, rather than being
jumped into range.

This is deliberate: a user's objective is broadly fixed, and the product is
*micro*-variation of their routine, not repeated re-basing of it. The case is not
silent — it reports `DoseOutcome.UNVARIED_NO_SCHEME_IN_OBJECTIVE_RANGE`. Do not
"fix" this by widening the radius or searching the objective range directly.

### Strain is judged against the user's own baseline, and only ever moves load down

An HRV of 45 ms is a crash for one person and an ordinary Tuesday for another;
any absolute cutoff gets one of them wrong.

Absent, thin (<7 readings in the window) or stale (>48h) data yields
`ReadinessState.UNKNOWN`, which changes nothing but is deliberately *not*
`NORMAL` — "we did not look" and "we checked and they were fine" must not read
the same.

Downward-only is the other half: backing off needs no history, whereas
prescribing *more* work is progressive overload and needs accumulated load.
Vendor `readiness_score` / `strain_score` are deliberately not read — they are
opaque functions of the same HRV and heart-rate inputs, so counting both
double-weights one piece of physiology.

### A measurement of the user and a directive from the user are different inputs

`SessionIntent` (light / moderate / challenging) is the control a real UI puts in
front of a person; readiness is the optional enrichment behind it. Keeping them
separate is load-bearing three ways: intent needs no baseline so it works on
install day, it is not health data, and it *cannot protect the user from
themselves* — whoever picks `CHALLENGING` every day is exactly who deloading
exists for. That last point is why readiness is kept alongside it rather than
replaced by it.

**They compose by multiplication, and readiness caps the result at 1.0 whenever
it binds.** Multiplication alone is not enough, which is worth knowing because it
looks like it should be: `CHALLENGING` (1.15) against a merely `SUPPRESSED`
readiness (0.90) is 1.035 — an under-recovered user handed *more* work than
normal, the exact outcome the tier exists to prevent. What survives the cap is
the ordering, so the user's answer still visibly changed something.

Note the trap this creates: at exactly 1.0 the dose is genuinely
volume-preserving and every entry honestly reports `VARIED`, so the cancelled
request is invisible in the per-entry outcomes.
`RoutineVariation.intent_capped_by_readiness` exists precisely to say it out loud.

This relaxes "downward only", deliberately and only for an explicit user
directive. The original argument was that *the algorithm* must not push without
knowing accumulated load; a user asking for more is a different act, and refusing
it makes the app feel broken. The band stays narrow (±15%) so a
session-to-session choice cannot quietly become a progression mechanism.

### Accumulated load is a third adaptive term, downward-only for the same reason

A ratio *below* the sweet spot means the user is detrained relative to a month
ago, and the answer to that is progressive overload — which `progression.py`
already owns, one increment at a time against measured effort. A second,
independent upward push here would double-count it.

Two composition rules follow, and they differ on purpose:

- Readiness × load management **multiply**, because "how this body woke up" and
  "what the last four weeks cost it" are different time scales and both answers
  are real.
- *Within* load management, the taper and the ratio take the **deeper cut**,
  because they reduce the same quantity for different reasons and
  0.55 × 0.75 = 0.41 is a session neither of them asked for.

### The acute:chronic ratio refuses to judge more often than it agrees to

A log that does not reach back four weeks has an artificially small chronic
average, so every ordinary week reads as a spike — the standard criticism of
this metric, and the reason it is guarded rather than trusted. Thin windows, new
users and returns from a layoff all yield `UNKNOWN`, which is not `OPTIMAL`.

Do not "improve" coverage by dropping that guard; a deload prescribed to a
beginner in their second week is exactly the failure it prevents.

Relatedly, `TrainingLoadSummary.chronic_load_28d` stores the window's **weekly
average**, not its total, so the ratio means what the published figures mean. A
raw total would put steady training near 0.25 and make every published threshold
unusable.

---

### A generated session is composed of blocks, and a block owns its invariant

*Decision:* a generated session is a `Routine` plus one `SessionBlock` per entry.
A block is one exercise slot carrying a stable `index`, its share of the session's
time budget, and the volume-and-time pair that re-rolling it must preserve. There
is deliberately no grouping above it — no warm-up/main/accessory phases, no
per-muscle container.

*Based on:* `vary_entry` has held volume and time **per entry** since M1,
specifically so a variation cannot rob one exercise to pay another. That means the
guarantee a re-roll needs already existed; what was missing was a way to *address*
it from outside. Giving each entry an index and publishing its invariant is
therefore a naming exercise rather than new machinery, and it makes the user-facing
promise exact: press re-roll on any block, as often as you like, and the time you
asked for and the work you asked for both survive.

The alternatives were considered and cost more than they returned. Named session
phases need prescription rules per phase — a warm-up load policy, accessory
selection — that the engine has no basis for, and warm-up work is not volume the
invariant should be holding anyway. A per-muscle container is a grouping the
`target` field already expresses, and it would make "re-roll this" ambiguous
between one exercise and four.

### Re-rolling a block drops the adaptive tier, and keeps every other one

*Decision:* `vary_block` re-solves a block through
`VariationContext.without_adaptive_load()` — session intent, readiness and
accumulated load are neutralised; health, equipment and preferences are untouched.
It also takes no `TrainingMemory` at all.

*Based on:* a generated block's prescribed weight **already embodies**
`load_multiplier`. Difficulty, readiness and any taper were applied when the
session was built, so passing the same context back into variation applies them a
second time — a `challenging` session climbs 15% on every re-roll, compounding
silently until the numbers are absurd. Nothing in the per-entry outcomes would say
so, because each individual step honestly reports an ordinary variation. The same
argument bars memory: a progression decision moves the load off the block's
volume, and re-rolling is the user asking for *different work of the same size*,
not for reprogramming.

The tiers are not symmetrical here, and that asymmetry is the point. The adaptive
tier answers "how much work today", which the block already records. The
inviolable and hard tiers answer "what may this person do at all", and nothing
about re-solving a dose makes a contraindication less true.

### The generator refuses to invent a starting load

*Decision:* a block's load comes from the user's own logged lifts, else from a
named table of deliberately light body-mass fractions, else from nothing — and
"nothing" is reported as `load_source: no_basis` with
`is_prescribable: false`, never emitted as a 0 kg prescription.

*Based on:* M5 named starting load as the one risk that can injure someone on day
one, and the mitigation the roadmap settled on is asymmetric error. A first
prescription 20% too light self-corrects within two or three sessions through
M8b's RPE-driven increment; one 10% too heavy hurts a beginner immediately. So
every fraction in the table is biased low, and the four sources are kept as
distinct reported outcomes because two of them prescribe 0 kg and mean opposite
things: a bodyweight movement's zero is correct, and a barbell movement's zero is
a gap the caller has to close.

This is explicitly *not* the population-norms table keyed on
age/sex/bodyweight/experience. Sourcing that defensibly is research rather than a
lookup, and the fractions are named constants precisely so nobody mistakes them
for it — the same treatment the readiness multipliers get.

## The exercise library

### The library is generated, not authored

Corrections go in `tools/import_*.py`, where they survive re-import; edits to
`data/exercises.yaml` do not.

Each source owns its vocabulary mapping in its own importer;
`build_exercise_library.py` owns only cross-source concerns (ids, collisions,
precedence). Adding a third source means a new importer module, not edits to an
existing one. Sources return **lists, not name-keyed dicts** — records sharing an
exact name are distinct exercises, and keying by name silently drops them.

Licensing and provenance per source live in
[exercise-library.md](exercise-library.md), not here.

### A wrong movement pattern is worse than an absent one

Derived-field rules are name-matched, and names are ambiguous in ways that create
**wrong** data rather than missing data. A tricep kickback is not a glute
kickback; a leg curl performed on a pull-up machine is not a vertical pull; a
front lever whose name mentions a leg extension is not knee isolation. All three
were real over-matches.

`VariationContext.permits` fails closed on an *unknown* pattern but lets a
confidently-wrong one straight through the health guard. Simulate a rule change
over the existing library before trusting it, and pin the trap in
`tests/test_importer_patterns.py`.

The product target: mobile client over a Python cloud backend, aimed at a game-like social fitness network.
Code comments written before the reversal may still assume the old world.

**Personal data** Now split by class — see
[Health data stays on the device](#health-data-stays-on-the-device). The original
reasoning was never about data in general, so the part that mattered survives
intact.

**The port is shelved.** It existed to run the
engine on a phone without a server; with the engine server-side in Python it buys
nothing. Both habits it imposed stay, now on their own merits: no
Python-specific cleverness in the engine (a `Protocol` over duck typing), and
`mypy --strict`, which was justified as making a port mechanical and is equally
what makes a growing backend safe to change.

**Social is the vision.** The old
objection was that it required centralising other people's health data — which
the class split still forbids. Challenges and leaderboards get counts and
achievements, never the health bucket. Design that line into the first social
feature rather than retrofitting it.

**Coach relationships remain out of scope, not merely deferred.** If coach
sharing is ever wanted it has to be designed as an explicit, separately-consented
export, never as a sync that arrives behind a convenience.

---

## Still open

**The one-time-purchase model is an open question**, not a settled decision.
Recurring server and compliance costs do not come out of a single payment, and
social multiplies both. It needs an answer before V3 can be planned. The
account-key design lowers server cost somewhat, which changes the calculation but
does not settle it.

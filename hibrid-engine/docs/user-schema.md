# User schema (V2)

Data modelling only. These models describe everything a future routine-generation
engine may read about a person. **No engine reads them yet** — they were written
ahead of the logic on purpose, because schema churn is much more expensive than
logic churn: an algorithm can be rewritten at any time, but reshaping data that
has already been collected destroys history you cannot go back and re-measure.

## Design rules

### 1. Canonical metric/SI units, always

Mass in kg, length in cm or m, duration in seconds or minutes, energy in kcal,
temperature in °C. The unit is part of every field name (`body_mass_kg`,
`duration_seconds`).

A user's preferred *display* units live on `UserProfile.unit_system` and never
affect storage. This deletes an entire class of unit-confusion bug from every
algorithm that will ever read this data.

### 2. Anything measurable and changeable is a dated snapshot

Height, body mass, VO2max and fitness scores all live in `biometrics` as
immutable dated records — even height, which barely moves. One consistent rule
removes the recurring "is this a profile attribute or a measurement?" argument,
and guarantees the engine can always ask a *trend* question.

This matters more than it looks. "Is this user's HRV suppressed relative to
their own 28-day baseline?" is the question that actually drives a deload
decision, and no current-value field can answer it.

Correcting a value means **appending a superseding record**, never mutating the
original. `ImmutableModel` enforces this — recorded facts are frozen.

### 3. Provenance travels with every measurement

Every record carries `source` (`MeasurementSource`) and optional `confidence`.
A wrist-optical HRV reading and a chest-strap one are not interchangeable
evidence, and only provenance makes that distinction recoverable after
ingestion. Vendor-computed indices (`readiness_score`, `strain_score`) are kept
*alongside* their raw inputs, never instead of them — vendor formulas are opaque
and change without notice.

### 4. Objectives are a weight vector, not a mode

`ObjectiveWeights` is a normalised distribution over `TrainingObjective`
(non-negative, sums to 1.0). Real users want blends, and an engine trading
qualities off against each other needs the trade-off stated numerically.

Normalisation is enforced so vectors stay comparable across users and over time;
an unnormalised vector would smuggle "total training intent" in alongside its
distribution. Build from raw shares with `ObjectiveWeights.normalised({...})`.

`FitnessAssessment.component_scores` is keyed by the *same* enum, so the engine
can compare where the user **is** against where they want to **be**, dimension
by dimension.

### 5. Hard constraints are distinct from soft preferences

| | Violating it produces | Engine should treat as |
|---|---|---|
| `HealthProfile` (injuries, medical) | an unsafe routine | inviolable bound |
| Equipment / time availability | a routine they *cannot* do | hard constraint |
| `TrainingPreferences` (novelty, dislikes) | a routine they *won't* do | soft cost term |

Contraindications are explicit ID and enum sets, not free text, so a planner can
mechanically exclude work rather than having to interpret a note.

### 6. Prescribed *and* performed are both recorded

A generated routine is a hypothesis; `history` records the outcome. A user told
`4x8@80` who did `4x6@80` at RPE 10 has said something crucial that a bare log
of "4x6@80" cannot express. Hence `prescribed_reps`/`prescribed_load_kg` on
`PerformedSet`, `substituted_from_exercise_id` on `PerformedExercise`, and
`SessionStatus` (so a *deliberately skipped* session is distinguishable from a
session that simply doesn't exist).

Adherence is a first-class signal. A routine that is repeatedly skipped is a
failed prescription regardless of its physiological merit.

### 7. Derived data is labelled as rebuildable cache

`ExercisePerformanceRecord` and `TrainingLoadSummary` are **materialised views**,
recomputable from session history. They exist because the engine needs "what can
this user lift on this movement?" on every prescription and recomputing from full
history doesn't scale. The session log is the source of truth; these are caches
that get rebuilt, never hand-edited.

Both are now built for real — `hibrid.training_memory` (M8a) produces the
records, `hibrid.load_management` (M8c) the load summary — and both deliberately
recompute from `user.sessions` rather than reading `user.exercise_records` /
`user.load_summary` back. Trusting a cache the caller may have loaded stale
would make this rule a comment rather than a behaviour.

One field on `TrainingLoadSummary` is easy to misread: **`chronic_load_28d`
holds the 28-day window's *weekly average*, not its total**, so
`acute_chronic_ratio` is the conventional figure that sits near 1.0 for steady
training rather than near 0.25.

### 8. Relationships are ID references

Every entity has a stable ID. Independent facts reference `user_id` and
`exercise_id` rather than being reachable only by walking a Python object tree.
This is what makes the schema graph-projectable — see below.

## Ownership boundary

The rule that decides whether something nests or stands alone:

- **Owned value objects** — `profile`, `background`, `preferences`, `health`,
  `goals`. Nested, no `user_id`. Meaningless apart from their user, never queried
  independently.
- **Independent facts** — measurements, sessions, derived records. Each carries
  its own `user_id` and stands alone. High-volume, queried across users, and the
  things that become their own rows/documents/nodes.

`User` validates that every independent fact actually belongs to it — a
mismatched `user_id` is exactly the kind of error that stays silent until one
person's training data has been quietly blended with a stranger's.

> **Persistence note.** A real deployment will not load a user's entire history
> into memory. `User` is the complete *logical* view; a repository layer is
> expected to page the history collections. Nothing in the schema assumes they
> are full.

## Persistence: everything sensitive stays on the device

**Settled, and it replaces the earlier Neo4j-plus-graph-ML endgame.** All
personal data — profile, health, biometrics, training history — is stored
locally on the user's device and is never transmitted to a server we operate.

Three independent reasons, any one of which would be sufficient:

- **Legal.** Health data is special-category under GDPR Art. 9: processing is
  prohibited unless explicit consent applies, and holding it server-side pulls
  in records of processing, most likely a DPIA, subject-access and erasure
  handling, 72-hour breach notification, and transfer mechanics. In the US,
  HIPAA generally does *not* apply to a direct-to-consumer fitness app, but the
  FTC Health Breach Notification Rule does, and Washington's My Health My Data
  Act carries a **private right of action** over a very broad definition of
  consumer health data.
- **Platform.** Apple's HealthKit terms and App Store Guideline 5.1.3, and
  Google's Health Connect policy, restrict what may be done with this data and
  where it may be stored. These are contractual and enforced at app review, so
  they bind before any regulator is involved.
- **Business model.** The product is a one-time purchase. Server-side health
  data creates obligations that recur forever — answering erasure requests,
  maintaining access controls and audit logs, carrying breach insurance —
  against revenue that happens exactly once.

The cheapest breach response is having no database. Anything not held cannot
leak, be subpoenaed, or be misconfigured.

### What this means concretely

> **Scope narrowed, Aug 2026.** The product is now a mobile client over a Python
> cloud backend, so "nothing leaves the device" applies to the **health bucket
> only** — `RecoveryReading`, `WellnessCheckIn`, `BodyComposition`, `Injury`,
> `MedicalConsideration`. Identity, routines, the training log and progress are
> stored server-side. The legal reasoning above is exactly why the line falls
> there: it is all about *special-category* data, and the rest is ordinary
> personal data. See [decisions.md](decisions.md#health-data-stays-on-the-device)
> for what was reversed and what it cost.

- The **health store is embedded and local** — SQLite on the device. The engine
  receives these records as request-scoped inputs and forgets them; nothing
  server-side persists them.
- **No telemetry carrying health values**, and no health field in any
  server-side table, log or crash breadcrumb. Sharing with a coach, if ever
  wanted, must arrive as an explicit separately-consented export — never as
  something that creeps in behind a convenience.
- **Device backup is a real leak path.** Apple excludes HealthKit data from
  iCloud backup, but *our own copy* of it is not excluded automatically. Those
  files must be marked, on both platforms. This is the most common way
  "local-only" quietly becomes "in someone's cloud".
- **Crash reporting and analytics SDKs are the other leak path.** Health values
  escaping through log lines or crash breadcrumbs is a routine real-world
  failure. See the encryption note below.

### Deferred to a later version: at-rest encryption and log hygiene

Recorded here so it is a known gap rather than an oversight. Local storage
removes the server-side exposure but not the on-device one. The intended shape:

- Encrypt the local store (SQLCipher or an equivalent), with the key held in
  the platform keystore — iOS Keychain, Android Keystore — so it is protected
  by the device's own secure element rather than by us.
- Make spillage structurally impossible rather than a review checklist item.
  In the Rust core (M9) that means wrapping sensitive scalars in a newtype that
  deliberately does **not** derive `Debug`/`Display`, so a health value reaching
  a log line is a compile error. Redaction enforced at the logging boundary is
  the weaker fallback for the Python engine.

Neither is implemented. Nothing in the current schema blocks either, since both
are storage- and transport-layer concerns rather than modelling ones.

### The graph model, and what survives of it

The earlier plan was Neo4j plus graph-based ML. **That endgame is retired.**
Graph ML earns its keep on a *multi-user* graph — "users with similar
embeddings responded well to this progression" — and a single-user, on-device,
one-time-purchase app has no such graph. Building one would mean centralising
exactly the data this section exists to keep off a server.

What survives, and must not be undone: the schema stays **graph-projectable**.
Stable IDs, relationships expressed as ID references rather than object-tree
reachability, and `PerformedSet` shaped as a relationship-with-properties are
good modelling against *any* store — they are what make the data a set of
relational rows rather than a nested blob. The shape below is retained as the
conceptual model the tables mirror, not as a deployment target:

```
(Exercise)-[:TARGETS]->(Muscle)
(Exercise)-[:REQUIRES]->(Equipment)
(Exercise)-[:HAS_PATTERN]->(MovementPattern)
(Exercise)-[:SUBSTITUTABLE_FOR {similarity}]->(Exercise)
(Exercise)-[:PROGRESSES_TO]->(Exercise)

(User)-[:HAS_GOAL]->(Goal)-[:WEIGHTS {weight}]->(Objective)
(User)-[:HAS_INJURY]->(Injury)-[:AFFECTS]->(BodyRegion)
(Injury)-[:CONTRAINDICATES]->(MovementPattern)
(User)-[:CAN_ACCESS]->(Equipment)
(User)-[:PERFORMED]->(TrainingSession)-[:INCLUDED]->(PerformedExercise)-[:OF]->(Exercise)
```

`PerformedSet` is deliberately shaped as a **relationship with properties** —
`(User)-[:PERFORMED {reps, load_kg, rpe, at}]->(Exercise)` — which is also
exactly a join row, so it lands in a relational table without restructuring.

The *traversal* queries this shape enables are still worth having and are
perfectly answerable locally: *"find an exercise two hops from bench press
sharing a primary muscle but different equipment"* is a couple of joins over the
exercise ontology, which is repo-local, non-personal, read-only data. What is
gone is only the cross-user collaborative half.

### Two kinds of data, two shapes

`RecoveryReading`, `WellnessCheckIn` and `BodyComposition` are high-volume
append-only facts you **aggregate**, not traverse — `readiness.py` already does
exactly this, rolling a 28-day window into a baseline. They want an indexed,
time-ordered table, not a node per reading.

Recommended local split:

| Data | Shape | Why |
|---|---|---|
| Exercise ontology | Read-only, ships with the app | Non-personal, identical for every user, regenerated at build time from `data/exercises.yaml` |
| User↔goal↔injury↔equipment relations | Local relational tables | Small, joined constantly during a variation |
| Biometric time series | Local table indexed on `(user_id, recorded_at)` | Rollups over a window, never traversal |
| Derived caches (`TrainingLoadSummary`, `ExercisePerformanceRecord`) | Local, rebuildable | Never the source of truth; drop and recompute |

Because every model is a pydantic model, `model_dump()` already yields a row
directly, and `model_json_schema()` gives the migration contract. Note that this
is the boundary the Rust port (M9) has to reproduce: `serde` structs plus
explicit validation, not a second hand-written schema.

### Point-in-time correctness

`latest_before(records, cutoff)` exists specifically for training future models.
Reconstructing what was known *then* — not what is known now — is what keeps a
training set free of **target leakage**. Using current values to explain past
decisions silently inflates offline accuracy and produces a model that fails in
production.

## Why pydantic here, dataclasses in `models.py`

A deliberate boundary, not an inconsistency:

- **`hibrid.models`** (`Exercise`, `RoutineEntry`, `Routine`) stays on stdlib
  dataclasses. It's internal, constructed from a trusted repo-local YAML, and
  sits in the variation engine's hot path where per-instance validation would
  cost real time during candidate search.
- **`hibrid.user`** uses pydantic. It ingests *untrusted external* data — device
  exports, API payloads, user forms — where a bad value silently entering the
  model corrupts every downstream decision.

`extra="forbid"` is the load-bearing setting: an unrecognised key from a renamed
device field raises at ingestion rather than vanishing and turning up much later
as a mysteriously absent feature.

Both share one vocabulary — `Equipment` and `MovementPattern` are imported from
`hibrid.models` and re-exported, never forked.

## Sex and gender

`BiologicalSex` is used strictly for physiological modelling — relative strength
norms, VO2max percentile tables, cycle-aware periodization. `gender_identity` is
free text, optional, for addressing the person, and carries no algorithmic
meaning. Conflating the two would make the model both less accurate and less
respectful.

`MenstrualPhase` is optional and nullable everywhere it appears; cycle phase
measurably affects recovery capacity and injury risk, so it's a legitimate
periodization input, but the schema must work identically when it's never
provided.

## Not yet modelled

Deliberately deferred, and worth naming so their absence is a decision rather
than an oversight:

- **Nutrition / hydration** — genuinely affects adaptation, but it's a large
  sub-domain of its own and nothing in the near-term roadmap consumes it.
- **Somewhere to persist the prescribed routine.** `Routine.routine_id` is a
  stable `UUID` since M1, so `TrainingSession.prescribed_routine_id` has a real
  target — but no store exists to resolve it against. Closed by V1's server
  persistence, the first item in the build order in [HANDOFF.md](../HANDOFF.md).
- **Multi-user / social graph** — now the product vision rather than out of
  scope, but the boundary above holds regardless: challenges and leaderboards
  get counts and achievements, never the health bucket. A coach-sharing feature
  has to be an explicit separately-consented export — never a background sync.
- **At-rest encryption and log redaction** — see the persistence section above.
  Parked to a later version, deliberately.
- **Equipment-aware load semantics** — the V1 limitation logged in
  `variation.py` (per-hand dumbbell vs. total-bar load, bodyweight movements)
  still applies and now also touches `PerformedSet.load_kg`.

# hibrid — agent handoff

Read this first if you are picking up this repository with no prior
conversation. It carries the three things that are *not* recoverable from the
code: **what we are building, how it is put together, and what to do next.**

| Section | Answers |
|---|---|
| [1. What we are building](#1-what-we-are-building) | The product, and which release we are in |
| [2. How the engine works](#2-how-the-engine-works) | The two things it does, and the invariant each one holds |
| [3. How the code is organised](#3-how-the-code-is-organised) | Where everything lives, and how to run it |
| [4. Where the project stands](#4-where-the-project-stands) | What is built, what is not |
| [5. What to build next](#5-what-to-build-next) | The numbered build order |
| [6. Out of scope, and open questions](#6-out-of-scope-and-open-questions) | What is deliberately not being done |

Companion documents, in reading order:

| | |
|---|---|
| [CLAUDE.md](CLAUDE.md) | How to write code here. Style rules, enforced mechanically. |
| [docs/decisions.md](docs/decisions.md) | Why the code is shaped the way it is. Every architectural decision with the argument behind it. |
| [docs/known-gaps.md](docs/known-gaps.md) | What is deliberately missing, and what closing each gap involves. Includes one case of shipped data that is actively wrong. |
| [docs/roadmap.md](docs/roadmap.md) | Release plan through the vision. |
| [docs/api-v1-draft.md](docs/api-v1-draft.md) | The V1 data model and HTTP contract. Draft, unimplemented. |
| [docs/user-schema.md](docs/user-schema.md) | Design rules for `src/hibrid/user/`. Read before extending the schema. |
| [docs/exercise-library.md](docs/exercise-library.md) | How the 4,531-exercise library was imported, what was dropped, and the licensing split. Read before touching `data/exercises.yaml` or the `Muscle` enum. |

---

## 1. What we are building

**A game-like social network for progressive fitness tracking.** That is the
destination. What exists today is the engine underneath it.

**The problem.** Training routines get monotonous. People repeat the same
routine with no controlled progressive overload, nothing keeps them engaged, and
they quit. The failure is rarely a bad programme — it is a programme that never
changes and never acknowledges the person following it.

**The answer.** An engine that adapts a routine to the person following it:
exercises substituted for near-equivalents, sets and reps and load nudged, and
the training stimulus held constant while the surface changes. The routine
shifts underneath the user in a way that is visibly deliberate rather than
random.

**The counter-force, and it is equally load-bearing.** Adaptation requires
*repetition*. Strength is a movement-specific motor skill, and it can only be
measured on a movement with a stable history — so an engine free to swap the
exercise every session trains nothing and can measure nothing. Variation and
progression pull against each other by construction, and every design decision
here is really a decision about where to put that line. `VariationPolicy` is
where the line now lives; §2 explains it.

**Shipped as a mobile app over a Python cloud backend.** The backend carries the
calculation and stores identity, routines, the training log and progress. Health
and biometric data stays on the device — that split is a deliberate safeguard,
not an implementation detail, and the reasoning is in
[decisions.md](docs/decisions.md#health-data-stays-on-the-device).

**This repo builds the backend and its API only.** The mobile client is a
separate project, built against the contract in
[api-v1-draft.md](docs/api-v1-draft.md).

### Releases, each earning the next

| | | |
|---|---|---|
| **V1** | Adaptive routine + progress counter | ← **current** |
| **V2** | Functional training, CrossFit WODs, yoga, pilates | |
| **V3** | Expanded gamification | |
| **Vision** | The social layer | |

**V1's acquisition is the routine visibly adapting** — finish a workout, come
back, and the programme has moved in a way you can interrogate. **Its retention
is the progress counter**: lifetime totals that only ever go up, plus level bars
that decay after two weeks of inactivity because detraining is real. There is
deliberately **no streak** — nothing in the design resets. Anything in the
backlog that serves neither waits.

---

## 2. How the engine works

The engine does two things. Both are pure functions over value objects — no I/O,
no clock they did not receive as a parameter.

### The shape of the system

```
   mobile client
        │  HTTPS, account key in the header
        ▼
   hibrid.api          ← untrusted boundary: pydantic, converts at the edge
        │
        ├──► store     ← identity, routines, training log, progress
        │
        ▼
   the engine          ← pure functions over value objects. No I/O, no clock.
   generation, variation, readiness, progression, load management, objectives
        │
        ▼
   data/exercises.yaml ← 4,531 exercises, generated from two sources
```

### Varying an existing routine

`vary_entry` does two things per routine entry:

1. With probability `substitution_prob`, swap the exercise for one sharing its
   **target muscle**, ranked by `Exercise.similarity` (target weighted 0.7,
   secondary-muscle overlap 0.3) and sampled from the top-scoring band.
2. Search nearby `(sets, reps)` schemes and solve the remaining variables so the
   entry's **invariant** and its **time** are both preserved.

**Which invariant is the objective's choice, and this is the part most easily
got wrong.** `ObjectiveStrategy.variation_policy` names one of two:

| | Holds | Solves | Right for |
|---|---|---|---|
| `Invariant.LOAD_VOLUME` | `sets × reps × weight` | the load, per candidate scheme | hypertrophy, muscular endurance |
| `Invariant.INTENSITY` | the load, at the reference | total work, within tolerance | strength |

Solving load from a volume target under a *strength* objective preserves the
arithmetic and destroys the training: a 4×4 at 100 kg and a 6×6 at 45 kg carry
identical volume, pass every tolerance, and are not the same session. Under
`INTENSITY` the bar is pinned and the scheme waves around it, which is also what
makes a taper come out the right shape — the adaptive multiplier moves the
volume target, so a deload takes sets away and leaves the bar alone.

The same policy caps `substitution_prob` per objective, whatever the caller or
the user's `novelty_preference` asked for. Strength is capped hard (0.10),
because a substitution discards the very history `TrainingMemory` is keyed on.
Hypertrophy is deliberately uncapped **for now** — the correct bound for it is
per training *block*, and blocks are step 1 of §5.

Volume and time are held **per entry**, not just per routine, so a variation
cannot quietly rob one exercise to pay another. `--seed` makes runs
reproducible, which is what the tests rely on.

The target is scaled by `VariationContext.load_multiplier`, which composes three
adaptive terms: the user's stated intent for today, their recovery against their
own 28-day baseline, and what the last four weeks of logged work and any
upcoming event allow. Time is never scaled with any of them. The multiplier is
1.0 whenever nothing is supplied and nothing is asked, so every caller without a
wearable or a training log sees the original behaviour exactly.

An entry that does not move **always says why** — see `DoseOutcome` and
`ExerciseOutcome`. That is a design commitment, not a debugging aid: an
unchanged row the user cannot interrogate reads as a broken app. Note
`UNVARIED_HOLDING_INTENSITY` in particular — for strength, a repeated
prescription is the *correct* answer, and must not be reported as a failed
search.

### Generating a session from nothing

`generate_session` answers the other direction — no input routine, just three
things a user can say on day one: **how long, which muscles, how hard.**

1. **Time is split**, evenly across the requested muscles and then across the
   blocks each muscle's share supports. One `(sets, reps, rest)` is solved so a
   block lands on its share, with every range owned by `ObjectiveStrategy`.
2. **Exercises are selected** per muscle from the permitted, in-modality pool,
   preferring distinct movement patterns so a chest slot is not four cable flys,
   and ordered compounds-first.
3. **Load is resolved** in priority order: the user's own logged lifts, then a
   deliberately light body-mass fraction, then nothing — and "nothing" is
   reported, never guessed.

The result is a `Routine` plus a `SessionBlock` per entry. **A block is the unit
a user can re-roll**: `vary_block` runs the same `vary_entry` search against that
block's own invariant and time, so the three requested parameters survive any
number of re-rolls. The one trap, and it is silent: the block's weight already
embodies `load_multiplier`, so re-rolling has to drop the adaptive tier
(`VariationContext.without_adaptive_load`) or a hard session compounds 15% per
press of the button.

Everything the session does *not* deliver is on the report —
`muscles_uncovered`, a time budget it could not fill, a load it had no basis
for. Same commitment as an unvaried entry: a silently smaller session reads as a
bug.

### The decisions behind all of it

One line each; the full argument is in [decisions.md](docs/decisions.md), which
is where to go before challenging one.

- **Personal data splits by class, and the split is the safeguard.** Identity,
  routines, the training log and progress are stored. Health and biometrics are
  never persisted server-side. *Based on:* special-category data under GDPR
  Art. 9 carries obligations an order of magnitude heavier than ordinary
  personal data, and Apple and Google restrict it contractually.
- **The device holds one secret; the server resolves it to an identity.** The
  client never sends a `user_id`. *Based on:* it keeps every ownership validator
  meaningful, and makes the account id and the user id the same value.
- **The engine core is pure.** *Based on:* it is what makes 524 tests run in ~4s
  with no fixtures, and what keeps a native client possible later.
- **Two model styles, deliberately.** Stdlib dataclasses inside the engine;
  pydantic v2 at every untrusted boundary. *Based on:* a renamed device field
  must raise at ingestion rather than vanish silently — but per-instance
  validation during candidate search costs real time.
- **Enums are shared, never forked.** *Based on:* two copies of a movement
  vocabulary would break every join between a routine and a user's history.
- **The engine is deterministic and explainable, not learned.** *Based on:* the
  product must be good on day one for a user with an empty history, which is
  exactly where a learned system is weakest.
- **Anything measurable and changeable is a dated immutable snapshot.** *Based
  on:* "is this user's HRV suppressed relative to their own 28-day baseline?" is
  unanswerable from a current-value field.
- **Hard constraints are separate from soft preferences.** Health is inviolable,
  equipment and time are hard, dislikes are soft cost terms. *Based on:* an
  engine must never trade a contraindication against an objective.
- **Training correctness outranks stated preference.** `novelty_preference` is a
  preference; how often a movement may rotate and still be trainable is a
  property of the objective, and bounds it. *Based on:* the same tiering as
  above — a preference that silently defeats the progression layer is not a
  preference, it is a bug with a dial on it.
- **The exercise library is generated, not authored.** Corrections go in the
  importers. *Based on:* an edit to the generated file does not survive the next
  re-import.

---

## 3. How the code is organised

```
src/hibrid/
  models.py         Core value objects: Muscle, BodyPart, MovementPattern,
                    Equipment, Exercise (+ similarity), Dose (RepsDose /
                    DurationDose / DistanceDose / RoundsDose), RoutineEntry,
                    Routine (has a stable routine_id)
  exercise_db.py    ExerciseDB — loads data/exercises.yaml, find_substitutes()
  routine_io.py     Routine <-> YAML, including per-modality Dose (de)serialisation

  objective_strategy.py
                    ObjectiveStrategy ABC + Strength / Hypertrophy /
                    MuscularEndurance. Owns two questions: what one session
                    looks like (rep/set/rest range, tempo, target RPE), and what
                    may change between sessions (VariationPolicy — which
                    invariant is preserved, and the substitution ceiling)
  variation_context.py
                    The bridge from hibrid.user to the engine. permits()
                    answers inviolable + hard, preference_score() answers soft
                    and cannot veto, load_multiplier answers adaptive and
                    likewise cannot veto
  readiness.py      The freshest RecoveryReading / WellnessCheckIn against that
                    user's own 28-day baseline, never an absolute threshold.
                    Yields a ReadinessState and a downward-only load multiplier
  training_memory.py
                    Walks TrainingSession / PerformedSet and rebuilds
                    ExercisePerformanceRecord per exercise, including an
                    estimated 1RM. Always recomputed from the log
  progression.py    Resolves each exercise's working load from TrainingMemory
                    instead of the routine's own weight, then moves it one
                    increment based on how the last session went against the
                    objective's target_rpe_range
  load_management.py
                    The same log read per *session*: an acute:chronic workload
                    ratio against this user's own four-week average, plus a
                    taper toward a dated event. Downward-only like readiness
  variation.py      vary_routine() -> RoutineVariation: the varied Routine plus
                    a per-entry EntryVariation carrying DoseOutcome and
                    ExerciseOutcome
  session_generation.py
                    generate_session() builds a session from a time budget,
                    muscles and a difficulty, as SessionBlocks — one exercise
                    slot each, owning the invariant a re-roll must hold.
                    vary_block() re-rolls one, neutralising the adaptive load
                    multiplier so difficulty cannot compound
  cli.py            python -m hibrid.cli <routine.yaml>
  py.typed          PEP 561 marker — KEEP IT

  api/              HTTP playground (needs the `api` extra). Pydantic schemas,
                    never the hibrid.models dataclasses, past the route handlers
    schemas.py      Request/response models + to_domain() / from_domain()
    app.py          Routes: /health, /objectives, /routines, /routines/{name},
                    POST /vary, POST /performance-records,
                    POST /sessions/generate, POST /sessions/blocks/vary
    __main__.py     python -m hibrid.api — runs uvicorn with --reload

  user/             The user schema (pydantic v2). No logic.
    types.py        Constrained scalars + the two model bases
    enums.py        All closed vocabularies; re-exports Equipment and
                    MovementPattern from hibrid.models
    profile.py      UserProfile, TrainingBackground
    objectives.py   ObjectiveWeights, TrainingGoal, PerformanceTarget, TargetEvent
    preferences.py  TrainingPreferences, AvailabilityWindow, EquipmentAccess
    health.py       Injury, MedicalConsideration, HealthProfile
    biometrics.py   Dated immutable measurements
    history.py      PerformedSet / PerformedExercise, TrainingSession
    user.py         User aggregate root, latest_before()

data/exercises.yaml       4,531 exercises. GENERATED — do not hand-edit
data/exercises.LICENSE    Upstream MIT notice, must travel with the data
tools/build_exercise_library.py
                          Entry point. Merges sources, assigns ids, resolves
                          collisions and precedence
tools/import_*.py         One per source. Hold the muscle / equipment / pattern
                          synonym maps — the real content of each import
routines/example_ppl.yaml Sample push-day routine, used by the CLI and tests
tests/                    524 tests, ~4s
playground.http           Scenario suite for the VS Code REST Client extension
.claude/                  mypy hook on every .py edit + the simplicity-gate skill
```

### Running it

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,api]"                             # api extra: hibrid.api + its tests

python -m pytest -q                                     # 524 tests
mypy src tools                                          # strict, must pass
python -m hibrid.cli routines/example_ppl.yaml --seed 7 # the demo
python -m hibrid.api                                    # playground on :8000, docs at /docs
```

`playground.http` is the fastest way to *see* what the engine does: it sweeps
objectives, seeds, tolerances and dose shapes against a running API, with the
measured result noted inline on each request. Its §7 documents real limits and
is worth reading before trusting engine output.

> **Legacy milestone labels.** Code comments still carry `M1`–`M9` markers from
> an older numbering scheme with gaps in it. They are historical provenance, not
> a plan: `M1` = modality-generic `Dose`, `M2` = `ObjectiveStrategy`, `M3` = user
> constraints and readiness, `M5` = cold-start generation, `M8a/b/c` = memory /
> progression / load management. **Do not add new ones** — the build order in §5
> is numbered from 1 with no gaps, and that is the only forward-looking list.

---

## 4. Where the project stands

**The engine is built and is the majority of the hard part.** 524 tests pass and
`mypy --strict` is clean across `src/` and `tools/`.

| Capability | Where | Status |
|---|---|---|
| Exercise library — 4,531 exercises, normalised muscles, enrichment attributes | `data/exercises.yaml`, `tools/` | **Built** |
| The user schema — everything the engine may know about a person | `user/` | **Built** |
| Modality-generic prescription (`Dose`) | `models.py` | **Built** |
| Per-objective rep/set/rest ranges | `objective_strategy.py` | **Built** |
| Per-objective variation policy — which invariant, and the substitution ceiling | `objective_strategy.py`, `variation.py` | **Built** |
| Micro-variation holding the invariant and time per entry | `variation.py` | **Built** |
| Health, equipment, preference and intent constraints | `variation_context.py` | **Built** |
| Readiness against the user's own baseline | `readiness.py` | **Built** |
| Remembered loads, RPE-driven progression | `training_memory.py`, `progression.py` | **Built** |
| Acute:chronic deload and event taper | `load_management.py` | **Built** |
| Cold-start generation — one session, as re-rollable blocks | `session_generation.py` | **Built** |
| Cold-start generation — the weekly plan | — | **Not built** |
| Exercise roles and training blocks | — | **Not built** |
| Persistence, accounts, logging, progress | — | **Not built** |

What exists today has **no persistence**: routines are YAML files on disk and
the API is stateless. `hibrid.api` is a dev playground — no auth, no store,
`CORS *` — not the V1 backend.

The user schema is largely consumed. Still unread: objective weight vectors,
`AvailabilityWindow`, and every biometric other than recovery and wellness. That
is deliberate — the schema was written ahead of the logic, because reshaping data
you have already collected destroys history you cannot re-measure, whereas an
algorithm can be rewritten any afternoon.

### V1 is the loop, end to end

```
questionnaire ──► generated routine ──► do the workout ──► log it
                        ▲                                    │
                        └──────── adapted for next time ◄─────┘
                                         │
                                    progress page:
                                    counter + objective bars
```

Four scope decisions are settled, so they are not open:

- **The first routine is engine-generated from a questionnaire**, not picked
  from templates and not authored by the user.
- **Accounts are anonymous device accounts** — a key issued on first launch, no
  signup wall, upgradeable to a real account before social lands. A lost key
  means a lost account for now; that is accepted.
- **Progress is two bars per objective, plus a lifetime counter.** One bar for
  engagement, one for level, both derived from logged training — never a
  self-assessment. No streak, and nothing that resets.
- **This repo builds the backend and its API only.**

---

## 5. What to build next

In dependency order, numbered from 1. Steps 1 and 2 are new: they close the gap
between what the engine varies and what a body actually adapts to, and step 1
has a hard ordering constraint against persistence.

### 1. Exercise roles and the training block — *model only*

`ExerciseRole` on `RoutineEntry` (anchor / primary / accessory / finisher), and
a `TrainingBlock` with a `block_id` on `Routine`. No logic, just the fields.

**This must land before step 3.** Once sessions are being persisted and logged,
a routine row with no role and no block id makes every session logged before the
fix permanently un-attributable — you cannot reconstruct afterwards whether a
logged squat was the anchor of a block or a rotating accessory. That is exactly
the class of unrecoverable history the schema-ahead-of-logic rule exists to
prevent, so paying for it now is cheap and paying later is impossible.

Small, and it unblocks step 2.

### 2. Role-aware and block-aware variation — *pure engine*

The half of the variation fix that steps 1's fields make possible:

- **Roles drive substitution.** An anchor is not substituted mid-block; an
  accessory rotates freely. Today `substitution_prob` is applied uniformly to
  every entry, so a barbell squat and a cable lateral raise are equally likely
  to be swapped — which is the wrong answer for both.
- **Blocks bound hypertrophy's rotation.** This is what
  `_HYPERTROPHY_MAX_SUBSTITUTION_PROB` is waiting for. Hypertrophy tolerates
  rotation *across* blocks and not within one: a novel movement's first two or
  three exposures are limited by coordination rather than by the muscle, so
  rotating every session under-stimulates the target while producing soreness
  that reads as a false positive. With a block boundary to rotate at, the
  correct bound becomes expressible.
- **Double progression becomes available on anchors.** `progression.py` reads
  RPE alone, and says so, *because* the scheme moves every session. With an
  anchor holding its scheme, "add reps within the range, then add load and reset"
  works from session one on a user who never logs RPE. Keep RPE as the
  modulator, not the sole input.

Pure engine work, no persistence dependency — it can run in parallel with
step 3.

**Product note worth settling here:** a block boundary is a better acquisition
moment than per-session shuffling. Per-session randomness reads as deliberate
exactly once; *"Block complete — 6 weeks, bench 82.5 → 92.5. Three movements
change on Monday"* is an event with a story, lands on a schedule, and is a
natural achievement for V3's gamification.

### 3. Persistence and accounts

The foundation everything else writes to. Accounts, profiles, preferences,
plans, sessions and progress in a real database behind a device-issued key. The
schema is already relational — every independent fact carries `user_id` and
`PerformedSet` is a join row by construction — so this is a mapping job, not a
remodelling one. Data model in
[api-v1-draft.md](docs/api-v1-draft.md#2-the-account-model).

### 4. The weekly plan type

`TrainingPlan` and `PlannedSession` in `hibrid.models`, which requires moving
`Weekday` down from `hibrid.user.enums` to avoid a circular import. Small, and
it blocks step 5. `TrainingBlock` from step 1 belongs here — a block is a
property of a plan, not of a session.

### 5. Cold-start generation — the week

The questionnaire → first routine. **The single-session half is built**
(`session_generation.py`, behind `POST /sessions/generate`): a time budget, the
muscles to train and a difficulty in, a session of re-rollable blocks out.

*The risk to manage was starting load*, and the mitigation held: loads come from
the user's own logged lifts where history exists, and otherwise from a named
table of deliberately light body-mass fractions. A first prescription 20% too
light self-corrects over two or three sessions; one 10% too heavy hurts someone
on day one. A loaded movement with no basis at all is reported as unprescribable
rather than guessed at.

**What remains is the week, not the session:** spreading muscles across several
days needs `AvailabilityWindow`, days per week, and step 4's `TrainingPlan`.
`AvailabilityWindow` is therefore still unread — a session duration binds a
session, a weekly calendar binds a plan.

### 6. Workout logging

`POST /sessions`. The schema is done; the endpoint and the "what did you
actually do" contract are not. Everything downstream derives from this row, so
it is the one most worth getting right — log RPE and the role/block ids from the
very first session, or progression and step 2 both have nothing to read.

### 7. Progress — the counter and the objective bars

A new pure module, `hibrid.progress`, reading the same log. Three parts:

- **A lifetime counter** — sessions, working sets, volume. Monotonic; nothing
  reduces it. Milestones fire as achievements, so every log is positive
  reinforcement with no failure state.
- **An engagement bar per objective** — "how often do I train hypertrophy", over
  a rolling 28-day window. Computable today.
- **A level bar per objective** — "how much hypertrophy do I have", decaying
  after 14 days of inactivity. **The formula is not yet specified**; the field
  shape is fixed so the client can be built against it, and `score` is null
  until it lands. Step 2 helps here: a level anchored on estimated 1RM is only
  defensible once anchors are stable.

Decay is computed on read from the log, never written by a scheduled job — a
number that changes while the user is asleep cannot be explained afterwards.
Shape and constants in
[api-v1-draft.md](docs/api-v1-draft.md#the-decay-rule).

### 8. Wire variation into the loop

The engine call exists; V1 needs it triggered on workout completion and the
result persisted, so the app shows an adapted routine on next open. This is the
acquisition moment — it should be the most carefully tuned thing in the release.

---

## 6. Out of scope, and open questions

### Deliberately not in V1

- **Health-based adjustment.** `readiness.py` and `load_management.py` work and
  stay in the backend, but nothing feeds them: the app ships the skeleton UI
  only and the health bucket never leaves the device.
- **Objective blending.** V1 asks for one objective at onboarding.
  `ObjectiveWeights` stays modelled and unread.
- **Anything social**, including leaderboards.
- **The duration/distance dose search**, so V1 prescribes resistance work only.
  That is the first thing V2 has to fix, and it also blocks the cardio,
  flexibility and mobility strategies — 686 non-resistance exercises already in
  the library cannot be prescribed or varied until it exists.
- **Movement-family memory.** Letting history survive a substitution at a
  discount, rather than resetting to `NO_HISTORY`, would make rotation cost
  precision instead of everything. It is gated on distinguishing per-hand from
  total-bar load first — see [known-gaps.md](docs/known-gaps.md) — because a
  family transfer across those is actively wrong data.

### Open questions that need an answer before V3

- **Monetisation.** One-time purchase is no longer a settled decision: recurring
  server and compliance costs do not come out of a single payment, and social
  multiplies both.
- **Account recovery.** Any real path needs a second factor, which needs an
  identity. The credential model keeps the door open without forcing it.
- **Legal review** of the training log at rest before public launch — see
  [decisions.md](docs/decisions.md#health-data-stays-on-the-device).

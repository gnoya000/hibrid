# Roadmap — from engine to product

**Vision: a game-like social network for progressive fitness tracking.**

The problem being solved has not changed: training routines go stale, people
repeat the same sets three times a week with no controlled progressive overload,
and quit. What changed is the delivery shape — see "The shipping shape" below,
and [decisions.md](decisions.md) for the decisions that were reversed to get here.

Releases, in order. Each is independently shippable and earns the next.

| | Release | Earns |
|---|---|---|
| **V1** | Adaptive routine + progress counter. Questionnaire → generated routine → workout → *the routine adapted itself* → RPG-style progress page | First real feedback |
| **V2** | Widen the training perimeter: functional, CrossFit WODs, yoga, pilates | Reach beyond lifters |
| **V3** | Expand gamification | Retention past the counter |
| **Vision** | The social layer | Network effects |

**Acquisition in V1 is the routine visibly adapting** — finish a workout, come
back, and the programme has moved in a way you can interrogate. **Retention in
V1 is the progress counter**: lifetime totals that only ever go up, plus
per-objective level bars that decay after two weeks of inactivity because
detraining is real. There is deliberately no streak — nothing in the design
resets. Everything in V1's scope below exists to serve one of those two, or it
waits.

> **Numbering.** The build order below is numbered from 1 with no gaps, and it
> is the only forward-looking list. Code comments still carry `M1`–`M9` labels
> from an older scheme; those are historical provenance and are mapped in
> [HANDOFF.md §3](../HANDOFF.md#3-how-the-code-is-organised). Do not add new ones.

## The shipping shape

**A mobile app over a Python cloud backend.** The engine runs server-side; the
app is a client. This reverses the earlier on-device/Rust plan — see
[decisions.md](decisions.md#reversed-in-aug-2026--read-this-before-trusting-older-comments),
which records what was given up and why.

**Personal data splits by class, and the split is load-bearing:**

| Class | Where | Why |
|---|---|---|
| Health & biometrics — `RecoveryReading`, `WellnessCheckIn`, `BodyComposition`, `Injury`, `MedicalConsideration` | **On the device only.** V1 ships the UI skeleton with nothing behind it | Special-category data under GDPR Art. 9, and restricted by Apple HealthKit / Google Health Connect terms that bind at app review. Keeping it off the server keeps all of that off the company |
| Identity, routines, training log, progress | Cloud | The backend carries the calculation, and the social vision needs a server eventually anyway |
| Exercise library | Ships with the backend | Non-personal, generated, read-only |

The training log in the cloud is a deliberate, *accepted* risk rather than a
free one: activity data may qualify as consumer health data under Washington's
My Health My Data Act, which carries a private right of action. Get legal advice
before public launch — this is the one item on this page that cannot be fixed
later by writing code.

**The one-time-purchase model is now an open question.** Recurring server and
compliance costs do not come out of a single payment, and social multiplies
both. Not settled here; flagging it because V3 and the Vision cannot be planned
without an answer.

---

## V1 — adaptive routine + progress counter ← **CURRENT**

The loop, end to end:

```
questionnaire ──► generated routine ──► do the workout ──► log it
                        ▲                                    │
                        └──────── adapted for next time ◄─────┘
                                         │
                                    progress page:
                                    counter + objective bars
```

### What already exists

The engine is done and is the majority of the hard part. Built, tested, and
`mypy --strict` clean:

| | |
|---|---|
| Micro-variation holding each objective's invariant and time, per entry | `variation.py` |
| Per-objective rep/set/rest ranges and variation policy | `objective_strategy.py` |
| 4,531-exercise library with substitution by muscle, pattern, plane and force | `exercise_db.py` |
| Health, equipment, preference and intent constraints | `variation_context.py` |
| Remembered loads, RPE-driven progression | `training_memory.py`, `progression.py` |
| Acute:chronic deload and event taper | `load_management.py` |
| Readiness against the user's own baseline | `readiness.py` |
| One session generated from time + muscles + difficulty, as re-rollable blocks | `session_generation.py` |

### The variation/progression tension, and where the line sits

Worth stating plainly at the top of the roadmap, because it shapes several rows
below and it was got wrong once already.

**Variation and adaptation pull against each other.** The product's pitch is
that the routine changes; the physiology is that adaptation requires repetition.
Strength is largely a movement-specific motor skill, and it can only be
*measured* on a movement with a stable history — and since `TrainingMemory` is
keyed on the exercise, a substitution discards the history the progression layer
reads. Unbounded variation therefore does not merely annoy a lifter, it defeats
the engine's own progression.

**Half of the answer is built.** `ObjectiveStrategy.variation_policy` now names
which invariant a variation preserves — load-volume for hypertrophy and
endurance, *intensity* for strength — and caps the substitution probability per
objective. Under a strength objective the bar weight is pinned and the scheme
waves around it, so a deload takes sets away rather than lightening the bar.

**The other half needs a training block**, which is rows 1 and 2 below.
Hypertrophy is deliberately left uncapped until then: it tolerates rotation
*across* blocks and not within one, and capping it per session with no block
boundary to rotate at would trade one wrong answer for another.

### The build order

In dependency order. Full detail for each row is in
[HANDOFF.md §5](../HANDOFF.md#5-what-to-build-next).

| # | Row | Why here |
|---|---|---|
| 1 | **Exercise roles and the training block** — `ExerciseRole` on `RoutineEntry`, `TrainingBlock` + `block_id` on `Routine`. Model fields only | Must precede row 3: a session logged without a role or block id is permanently un-attributable |
| 2 | **Role-aware and block-aware variation** — anchors hold, accessories rotate, hypertrophy's bound becomes expressible, double progression becomes available | Pure engine; can run in parallel with row 3 |
| 3 | **Persistence and accounts** — anonymous device key, real database | The foundation everything else writes to |
| 4 | **The weekly plan type** — `TrainingPlan` / `PlannedSession`, and the `Weekday` move | Blocks row 5; hosts row 1's `TrainingBlock` |
| 5 | **Cold-start generation: the week** — the single-session half is built | Needs row 4 |
| 6 | **Workout logging** — `POST /sessions` | Everything downstream derives from it |
| 7 | **Progress** — lifetime counter, engagement bar, level bar | Needs row 6; the level formula benefits from row 2 |
| 8 | **Wire variation into the loop** — triggered on completion, result persisted | The acquisition moment |

#### How work is attributed to an objective

Both progress bars need to know which logged sets count as hypertrophy work, and
`TrainingSession` does not record what it served. **V1 infers the objective from
the performed rep count**, and the rule is deliberately narrow:

**Attribution reads the dose, never the exercise's provenance.** Which source
library or discipline an exercise came from says nothing about the quality it
trained on a given day — a 3-rep kettlebell clean from the functional set is
strength work, and a 15-rep barbell squat from the resistance set is not.
Attributing by library would misclassify both, and would need a new mapping every
time a discipline is added.

The implementation is a reuse rather than a new rule: `ObjectiveStrategy` already
owns a `rep_range` per objective, so attribution is "which strategy's rep range
contains this set". Tuning a strategy's range moves attribution with it
automatically, and there is one source of truth rather than two that can drift.

Two known limits, both accepted for V1:

- **Rep count is a coarse proxy.** It cannot tell a heavy triple from a
  technically-limited one, and load relative to 1RM would be the better signal.
  The 1RM estimate already exists, so this is a refinement the data supports later.
- **It only works for `RepsDose`.** A 60-second plank and a 60-second hamstring
  stretch are the same dose shape and different qualities. Separating them needs
  `Exercise.modality` as a second input — an intrinsic property of the
  *movement*, not a label of where it came from, so it does not violate the rule
  above. Nothing needs this until the dose search lands in V2.

### Deliberately NOT in V1

- **Health-based adjustment.** `readiness.py` and `load_management.py` work and
  stay in the backend, but nothing in V1 feeds them: the app ships the skeleton
  UI only. They switch on when health data has a home, which is a device-side
  decision (see the shipping shape above).
- **Objective blending.** V1 asks for one objective at onboarding.
- **Anything social.** Including leaderboards.
- **The duration/distance dose search** — so V1 prescribes resistance work.
  Fine for a lifting app; it is exactly what V2 has to fix.
- **Movement-family memory** — letting history survive a substitution at a
  discount rather than resetting to `NO_HISTORY`. Gated on distinguishing
  per-hand from total-bar load first, since a family transfer across those is
  actively wrong data.

---

## V2 — widen the training perimeter

Functional training, CrossFit WODs, yoga and pilates. Two things gate it, and
neither is small:

**Content.** The library skews hard toward resistance work, and the shape of the
gap matters more than its size:

| Modality | Rows | Enough to programme from? |
|---|---|---|
| resistance | 3,845 | Yes |
| plyometric | 335 | Yes |
| balance / coordination | 233 | Probably — untested |
| mobility / flexibility | 89 | No |
| cardio | 29 | No |
| pilates, yoga | 0 | No |

No amount of engine work invents content that is not there, which is why
sourcing starts early and finishes late. The enrichment contract below is the
acquisition spec.

**The dose search — and this is the binding constraint, not the content.**
`DurationDose` / `DistanceDose` made a plank and a 2 km row *expressible*, but
`vary_entry` still only re-solves a `RepsDose`. So **686 non-resistance
exercises already in the library cannot be prescribed or varied today.** Varying
them means trading pace against duration — a different search, not a harder
version of this one. Until it exists there is no cardio, flexibility or mobility
strategy, and objective blending can only mix the three resistance objectives.

Worth stating plainly, because it inverts the intuitive order: **sourcing more
mobility content buys nothing until the dose search exists.** The 89 mobility
rows already there are equally unusable, and so are the 233 balance rows.

WODs and circuits are a third shape again: they are prescription *formats*
(EMOM, AMRAP, rounds-for-time), which is what `RoundsDose` was put in for and
what nothing has exercised yet.

### Per-discipline variation — the shape it will take

*Direction, not a design. Nothing here is built, and nothing should be built
until V2 forces it.*

Two changes arrive together once the perimeter widens, and they are **different
problems**:

**Generation will target a subset of the library.** A yoga session should not
draw from the barbell pool. This half needs no new architecture:
`session_generation.py` already filters candidates on
`objective.preferred_modality` in one predicate alongside
`VariationContext.permits`. Because every implemented strategy prescribes
`RESISTANCE`, that filter currently narrows generation *to* resistance work, and
a requested muscle the library only reaches otherwise is reported as
`modality_not_supported`. Widening it is a matter of adding strategies, not of
redesigning selection.

**Variation itself will need adapting per discipline, and that is the real
change.** The invariant machinery now exists — `VariationPolicy` already names
which quantity a variation preserves, and already carries two answers. Each new
discipline is a third, fourth and fifth answer to the same question:

| Discipline | Invariant | Status |
|---|---|---|
| Resistance, hypertrophy/endurance | Load volume + time | **Built** |
| Resistance, strength | Intensity + time | **Built** |
| Cardio | Duration or distance at a held intensity | Needs the dose search |
| Flexibility / mobility | Total time under stretch, positions covered | Needs the dose search |
| Balance / coordination | Difficulty progression, not volume | Needs the dose search |

That the first two already sit behind an objective-owned enum is the useful
precedent: adding a discipline should be adding an `Invariant` member and the
search that solves it, not restructuring `vary_entry`.

---

## V3 — expand gamification

Beyond the counter and the objective bars. Not designed yet, and deliberately
so: what to build here should be decided by what V1's users actually come back
for. What the schema already supports without new modelling: per-objective
progression curves, `PerformanceTarget` as explicit quests, `TargetEvent` as a
dated boss fight (the taper already aims at it), and adherence as a first-class
signal.

**One candidate is already implied by V1's row 1:** a completed training block
is a natural achievement — bounded, earned, and with a real number attached
("6 weeks, bench 82.5 → 92.5"). Per-session randomness cannot produce that
because nothing about it is an accomplishment.

---

## Vision — the social layer

A game-like social network for progressive fitness tracking. Requires the
account model to have graduated from anonymous device tokens, a moderation and
abuse story, and an answer to the business-model question above. It is also
where the data-sharing boundary gets tested hardest: challenges and leaderboards
need *counts and achievements*, never the health bucket, and that line is much
easier to hold if it is designed in from the first social feature rather than
retrofitted.

---

## Longer-running work

Two threads run across releases rather than sitting in one.

### Multi-discipline content acquisition

*The long pole. Sourcing runs in parallel with everything else.*

**Functional training: done.** A 3,242-row functional dataset landed, adding
kettlebell, clubbell, macebell, sandbag, rings, sliders, landmine and carry work,
taking the library to 4,531 exercises with 686 non-resistance. It satisfied most
of the enrichment contract below and closed the same-target substitution
weakness outright.

**Still needed for V2:** pilates/yoga (duration- and position-based),
conditioning *formats* rather than movements (intervals, circuits, EMOM/AMRAP —
prescription structures, so they depend on the dose search), and dedicated
agility/change-of-direction drills.

Each brings attributes resistance training doesn't have — hold duration,
work:rest ratio, joint action and range-of-motion targets, impact level, skill
prerequisites, contraindications. **Run a data spike before committing to the
dose schema for these**, so the model is validated against real pilates and
interval data instead of guessed at.

Licensing needs the same care as the existing import: the current library is
usable because its *data* is MIT while its media is not, and that distinction was
checked before vendoring.

#### The enrichment contract

The per-exercise attributes worth requiring of any new content, and what each
unblocks. The "still needed" rows are **deliberately not yet fields on
`Exercise`** — a column that is `None` for every row is dead weight until
something populates it. This is the acquisition spec, not a TODO list.

| Attribute | Unblocks | Status |
|---|---|---|
| **Modality** | The dose model, cross-discipline allocation | **Done** — all 4,531 |
| **Difficulty** / prerequisite skill | Cold-start generation | **Done** — 71%, eight ordered levels |
| **Force type** + **mechanics** | Substitution quality | **Done** — 49% / 71% |
| **Plane of motion** | Substitution quality | **Done** — 71%. Not on the original list; it turned out to be the signal that actually broke same-target ties |
| **Symmetry** | Unilateral programming | **Done** — 72% |
| **Loading mode** (per-hand vs total-bar) | Movement-family memory; correct dumbbell prescriptions | **Still needed.** Blocks letting history survive a substitution |
| **MET** (metabolic equivalent) | Cross-discipline allocation | **Still needed.** The one credible cross-modality dose currency. Source from the published Compendium of Physical Activities, not from any vendor |
| **Safety flags** (axial loading, joint-sparing) | Health filtering | **Still needed.** Would let `HealthProfile` filter mechanically instead of by movement pattern alone |
| **Objective suitability** | Blending, attribution | **Still needed, no longer blocking.** V1 infers the objective from the performed rep range instead, which is coarser but needs no new data |

Two cautions learned while evaluating sources:

- **Force type and mechanics must come from data, not derivation.** Deriving
  them from `MovementPattern` is circular — it re-encodes what is already known
  and adds no discriminating power.
- **Check the licence before the schema.** A dataset forbidding redistribution
  of derived datasets cannot be vendored into `data/exercises.yaml` at all,
  however good its fields are. In-app-only terms permit shipping a product but
  not committing the data, and that has to be settled before import work.

### Deferred engine work

Neither is scheduled; both are recorded so the reasoning is not re-derived.

**Objective blending.** Blend the strategies by `ObjectiveWeights` — a user at
`{strength: 0.7, mobility: 0.3}` getting a routine that reflects the ratio rather
than a winner-takes-all mode. `ObjectiveWeights` has sat in the schema unread
since the user schema landed.

*Settle the design question first: where the blend applies.* Interpolating rep
ranges between strength (1–6) and muscular endurance (15–25) lands on ~8–15,
which is hypertrophy — so a 50/50 blend would silently become a third objective
the user asked for none of. Allocating whole entries per objective keeps each
stimulus intact and composes with `vary_entry`, which already takes exactly one
strategy. Note this now also has to decide which *invariant* a blended session
preserves, which is a further argument for allocating whole entries: an entry
allocated to strength keeps strength's invariant, and nothing has to be averaged.

Half-blocked until the dose search exists: a blend naming `MOBILITY` or
`CARDIOVASCULAR_ENDURANCE` has no strategy to route to.

**Cross-discipline allocation.** Given objective weights, available days and
time, decide **how much of each discipline** a week should contain, then fill
each slot. Plus the interaction rules that make a plan coherent rather than a
pile of sessions: interference between heavy lifting and conditioning, mobility
placement relative to strength work, recovery cost per modality.

**Be honest that this is where engineering becomes modelling.** Trading 30
minutes of mobility against 30 minutes of strength requires each modality's
dose-response toward each objective, which is not derivable from the exercise
data. Start with explicit, editable heuristics grounded in published literature,
written as named constants — they will be revised by a human reading a paper.

A cloud backend *does* make outcome data collectable, which the on-device plan
ruled out. That reopens fitting these heuristics on real adherence and outcomes
later. It does not make it a good idea for V1: a one-shot, day-one-good product
still needs defensible defaults, and a learned system is weakest exactly where a
new user starts.

**Shelved: the Rust core and on-device store.** The port existed to ship the
engine onto a phone without a server. With the engine running server-side in
Python it buys nothing and is not planned. Two things survive it on their own
merits: `mypy --strict` with explicit signatures, and no Python-specific
cleverness in the engine — which keeps a future native client possible rather
than merely difficult. On-device encryption for the health bucket remains a real
requirement whenever that skeleton gets filled in — see
[user-schema.md](user-schema.md).

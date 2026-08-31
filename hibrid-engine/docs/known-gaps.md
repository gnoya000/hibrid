# Known gaps

Everything here is **deferred on purpose, not an oversight.** Each entry records
what is missing, why it was left, and what closing it would involve.

Read this before concluding that something is broken — several of these look
like bugs and are not, and one of them is a case of shipped data that is
actively wrong.

---

## Data integrity — the one that is actively wrong

### The library cannot be regenerated

`tools/build_exercise_library.py` takes the exercisedb source JSON as `argv[1]`,
and **that file is not vendored.** Only the functional CSV is in `data/`. The
generated artifact has outlived its inputs, which makes the repo's own correction
doctrine — fix the importer, re-import — unenforceable.

**Consequence right now:** importer fixes from the Aug 2026 data audit are
written and unit-tested but *not applied* to `data/exercises.yaml`. The shipped
library still contains these uncorrected:

- 21 hamstring curls labelled `SQUAT` (including "Bodyweight Nordic Hamstring
  Curl"), from the functional source's broad "Knee Dominant" category
- 18 shrugs labelled `ISOLATION_SHOULDERS` rather than `ISOLATION_SCAPULAR`
- 1 leg curl labelled `VERTICAL_PULL` because of the machine it uses
- 40 exercisedb entries with no pattern that the new rules now resolve

**Treat those labels as known-wrong.** Get the JSON, run the build, and diff.

### The functional CSV's licence is unconfirmed

Every other source was checked before vendoring, and one was rejected on its
terms. Confirm this one before public release or commercial use.

---

## The exercise library

### Movement pattern is 94% derived, 6% `None` — but most of that 6% is correct

Of 287 exercises without a pattern, 91 *should* have none: 29 cardio (a rower is
not a horizontal pull — already deliberate), 53 mobility (a stretch has no
push/pull/hinge) and 9 balance. The genuine gap is 196, and closing it means
adding rules to an importer.

Absent means *unknown*. `find_substitutes` treats it that way rather than making
those exercises unsubstitutable, but `VariationContext.permits` deliberately
fails *closed* on it against health contraindications.

### The exercisedb import is bare of enrichment attributes

2.0–2.6% coverage on difficulty, force type, mechanics, plane of motion and
symmetry, against 69–100% for the functional source. Every headline coverage
figure in the roadmap's enrichment contract is really "the functional source,
diluted".

Deliberately **not** backfilled by derivation: force type and mechanics are
barred by a settled decision (deriving them from `MovementPattern` is circular),
plane of motion is the signal that actually broke same-target ties and derivation
would degrade it, and difficulty affects beginner safety at 1,290 rows with no
defensible basis.

### Exercise instructions are not imported

~670 KB of English cueing text, ~2.6× the rest of the library, that no engine
reads. Belongs in a separate lazily-loaded file when a UI needs it.

### Per-hand vs total-bar load is not distinguished

A dumbbell press at 40 kg and a barbell press at 40 kg are different claims, so
swapping across them implies a weight that means something different in practice.
Also touches `PerformedSet.load_kg`.

The related bodyweight half **is** closed: `find_substitutes` refuses to swap a
loaded exercise for a bodyweight one, which matters at 1,125 bodyweight exercises
out of 4,531.

---

## The engine

### Substitution discards the history progression reads

`TrainingMemory` is keyed on `exercise_id`, and `vary_entry` resolves progression
for the *post*-substitution exercise. A swap therefore returns `NO_HISTORY`, the
routine's own prescribed weight stands, and no progression decision is made. That
is correct per entry — a user's barbell bench history genuinely says nothing about
their dumbbell press — and destructive in aggregate: at a high substitution rate a
user's log scatters across dozens of exercise ids holding one or two observations
each, which is below what `working_load` and `last_performance` need to act on.

**Bounded, not closed.** `VariationPolicy.max_substitution_prob` caps the rate per
objective, hard for strength (0.10). Hypertrophy is uncapped until a training
block exists to rotate at — see the next entry.

Two things would close it properly, and both are on the build order:

- **Exercise roles**, so an anchor lift is never swapped mid-block while
  accessories rotate freely. Today `substitution_prob` is applied uniformly, so a
  barbell squat and a cable lateral raise are equally likely to be swapped.
- **Movement-family memory**, so a swap costs precision rather than everything —
  a dumbbell lateral raise to a cable lateral raise should not reset the ladder.
  Gated on the per-hand vs total-bar gap below, because a family-level load
  transfer across those is actively wrong data.

### Hypertrophy's substitution rate is unbounded, pending a training block

`_HYPERTROPHY_MAX_SUBSTITUTION_PROB` is 1.0. That is not a claim that rotation is
free for hypertrophy — a novel movement's first two or three exposures are limited
by coordination rather than by the muscle, so rotating every session
under-stimulates the target while producing soreness that reads as a false
positive.

It is a claim that the *correct* bound is per training block rather than per
session, and the engine does not model a block yet. Capping it per session with no
block boundary to rotate at would trade one wrong answer for another: the result
would be a static routine, where what hypertrophy actually wants is stability
within a block and wholesale rotation between blocks.

### A single progression increment can round away

The step is defined against the *input* scheme but applied through the *output*
one, and those differ by design.

Worked example: +2.5 kg on a 4×8 entry is 80 volume units, but if the winning
candidate is 3×12, one 2.5 kg increment is 90 — so the step is smaller than the
output's granularity and rounds to the same prescribed weight as holding would.
Tightening `volume_tolerance` does not help, because it is rounding rather than
tolerance.

The decision is never hidden — `EntryVariation.progression` always reports it —
but the prescribed numbers may not move. Fixing it properly means progressing
*relatively* (a percentage of the reference) rather than in absolute kilograms,
which is a real change to how the increment is expressed.

**Does not apply under `Invariant.INTENSITY`**, where the output scheme cannot
change the solved load: the increment is applied to the reference and the
reference *is* the prescribed weight. Exercise roles would extend the same
property to anchor lifts under any objective, since an anchor holds its scheme.

### Progression is one weight increment regardless of the load's magnitude

2.5 kg on a 100 kg bench is 2.5%; on a 20 kg curl it is 12.5%. One increment is
the smallest representable step on real equipment, so this is closer to a fact
about plates than a design flaw — but light exercises do progress
proportionally faster than heavy ones.

### The taper lowers load under a volume-preserving objective — **closed for strength**

`load_management.py` expresses a taper as a multiplier on the volume target. Under
`Invariant.LOAD_VOLUME`, `vary_entry` solves weight from that target — so a
tapering athlete got a lighter bar rather than fewer sets at the same bar, which
is the right shape for a strain deload and the wrong shape for peaking.

**Closed for strength.** `Invariant.INTENSITY` pins the load to the reference and
lets total work absorb the multiplier, so a strength deload or taper now takes
sets away and leaves the bar alone — the shape the fix was described as needing.

**Still open for hypertrophy and muscular endurance**, and deliberately: under
those objectives a deload *should* reduce the load, because volume is what they
adapt to. The residual gap is narrow — an athlete peaking for an event on a
hypertrophy objective still gets a lighter bar — and the fix is to select the
strength strategy for a peaking block rather than to change the invariant.

### Strain reaches `RepsDose` entries only

A deload cannot touch a plank or a run, because there is no search that varies a
`DurationDose`/`DistanceDose`. A mixed-modality routine under strain comes back
partly deloaded, with the untouched entries reporting `UNVARIED_NOT_REPS_DOSE`.

This is the same gap that limits V1 to resistance work, and it is the first
thing V2 has to fix — it also blocks the cardio, flexibility and mobility
strategies.

### Generation cannot preserve a metabolic equivalent, so functional work is out

The variation invariant is "hold this block's own dose currency and its time".
`Dose.load_volume` already defines that currency per shape — kg-reps, seconds,
metres, rounds — so the shape of the guarantee generalises past resistance work.
Two things stop it, and neither is an engine decision:

- **There is no MET column on `Exercise`.** MET is the one credible
  cross-modality currency and the roadmap's enrichment contract requires sourcing
  it from the published Compendium of Physical Activities rather than deriving
  it. A guessed metabolic cost is wrong data, not missing data — the same trap as
  a wrong movement pattern.
- **`vary_entry` still only re-solves a `RepsDose`**, which is the gap above.

So `generate_session` filters to `objective.preferred_modality` and a requested
muscle reachable only outside it comes back as
`UnmetConstraintKind.MODALITY_NOT_SUPPORTED`. `Muscle.CARDIOVASCULAR_SYSTEM` is
the reliable example. This is reported, never silently dropped.

### Repeated re-rolls of one block random-walk within tolerance

Each `vary_block` call measures its tolerances against the block it was *given*,
not against the block the session was generated with. Eight consecutive re-rolls
of one block can therefore drift several percent from the original volume even
though every individual step was inside `volume_tolerance`.

The compounding that *would* have mattered is fixed: the adaptive load multiplier
is neutralised on re-roll (`VariationContext.without_adaptive_load`), so a
`challenging` session no longer climbs 15% per press of the button. What remains
is ordinary tolerance drift. Pinning it properly means passing the original
block's volume as the target rather than the current one, which is a change to
`vary_block`'s contract — worth doing when a UI actually offers unlimited
re-rolls.

### Difficulty is invisible on a bodyweight block

Difficulty scales the volume target, and `vary_entry` solves a weight from it.
A bodyweight block's weight is 0 and its volume is 0, so `light` and
`challenging` produce an identical prescription for it, and a session made
entirely of bodyweight work does not respond to the dial at all. `is_variable`
reports this per block.

It is the same root cause as the strain gap above — the engine expresses "how
much work" as a load — and it surfaces most for a cold-start user with no body
mass supplied, since that pool is deliberately tilted toward bodyweight
movements. Fixing it means letting difficulty move reps or sets when it cannot
move load, which changes the block's time and therefore needs the time budget to
give.

### Generation defaults to a beginner skill ceiling, which is a third of the library

`generate_session` maps `ExperienceLevel` onto `Exercise.difficulty` and allows
one grade of stretch above the user's own label. With no `background` supplied it
defaults to the beginner ceiling, because that is the safe direction to be wrong
in — and that leaves 2,816 of 4,531 exercises (62%). `untrained` leaves 1,711
(38%).

This looks like a bug from the outside, which is why
`GenerationReportOut.skill_filter` and `skill_ceiling` exist: `context_filter`
knows only about health, equipment and preferences, so without them a session
drawn from a third of the library would report `4531 / 4531` and appear
unfiltered. The narrowing is declared, not hidden.

Two deliberate softenings: the ceiling fails **open** on the 1,297 exercises with
no declared difficulty (absent means unknown, and failing closed would draw every
session from the functional source alone), and `familiar_exercise_ids` overrides
it outright, since a movement the user is recorded as performing with sound
technique is direct evidence where the ceiling is only a proxy.

### The conservative starting-load fractions are unfitted heuristics

`_CONSERVATIVE_LOAD_FRACTION` and `_BODY_PART_LOAD_FRACTION` in
`session_generation.py` are body-mass fractions per movement pattern, chosen to
sit around half of published novice standards. They are the same class of number
as the readiness multipliers: named and inspectable so a human can argue with
them, not derived from outcome data, and explicitly not the defensible norms
table keyed on age/sex/bodyweight/experience that M5 describes as research.

Two consequences worth knowing:

- **They inherit every wrong movement pattern in the library.** A hamstring curl
  mislabelled `SQUAT` gets the squat fraction. Every row is biased light, so the
  error lands on the safe side, but it is still the wrong number.
- **They are expressed as total external load**, so they inherit the per-hand vs
  total-bar gap above: a dumbbell prescription derived from them is a total across
  both hands.

### Load management reads two signals out of a much richer log

The acute:chronic ratio and a taper date, and nothing else.

- Adherence (`sessions_completed` / `sessions_prescribed`) is computed into the
  summary but consumed by nothing.
- `volume_load_by_objective` is left empty, because a `TrainingSession` does not
  record which objective it served and recovering that needs the prescribing
  routine — which has no store to resolve against yet.
- Monotony and strain (the SD-based companions to the ratio) are not computed at
  all.

### Readiness reads five signals out of a much richer record

HRV (RMSSD), resting heart rate, perceived recovery, energy and soreness.
`RecoveryReading` also models sleep debt, sleep efficiency, respiratory rate,
blood oxygen, skin-temperature deviation and menstrual phase; none is read.

That is scope, not oversight — each added signal changes how often the aggregate
trips, and adding them without an outcome measure is tuning blind. Note the
aggregation is a plain count of signals outside 1 SD, so adding *correlated*
signals would make the state fire more eagerly, not more accurately.

### The readiness and load-management multipliers are unfitted heuristics

`0.90` for one suppressed signal and `0.75` for two-or-more (or illness) are
numbers a human can argue with, chosen so they *can* be argued with. They are not
derived from outcome data.

`SWEET_SPOT_RATIO`, `SPIKE_RATIO`, `PEAK_VOLUME_FRACTION` and
`TAPER_WINDOW_DAYS` are the same kind of number, though these at least start from
published ranges rather than from nothing.

That is a reason to keep them named, inspectable constants rather than a reason
to distrust them.

---

## Scope

### Objective blending is unimplemented

`ObjectiveWeights` is modelled and validated but read by nothing. V1 asks for one
objective at onboarding. Every biometric other than recovery and wellness is
likewise unread.

The schema was written deliberately ahead of the logic, because reshaping data
you have already collected destroys history you cannot re-measure, whereas an
algorithm can be rewritten any afternoon. The unread parts are a contract later
releases satisfy, not an unfinished job.

### Nutrition and hydration

Real, but a large sub-domain of its own, and nothing near-term consumes it.

### Coach relationships and the social graph

**Out of scope, not merely deferred** — see
[decisions.md](decisions.md#reversed-in-aug-2026--read-this-before-trusting-older-comments).
Social is the vision, but it gets counts and achievements, never the health
bucket.

# Exercise library

`data/exercises.yaml` holds **4,531 exercises** merged from two sources. It
replaced a hand-written 21-exercise seed file, which was too small for
substitution to have real choices.

| Source | Records | Brings |
|---|---|---|
| `exercisedb` — [hasaneyldrm/exercises-dataset](https://github.com/hasaneyldrm/exercises-dataset) | 1,324 | Gym/resistance breadth, muscle tags |
| `functional` — `data/functional_tranining_bare_dataset.csv` | 3,207 net-new | Kettlebell, clubbell, macebell, sandbag, rings, sliders, landmine, carries — plus difficulty, force type, mechanics, plane of motion, symmetry |

A further 35 rows appear in **both**; those keep their original id and are
*enriched* rather than duplicated, so a routine file referencing
`barbell-bench-press` keeps working and gains the new attributes.

**It is a generated file — do not hand-edit.** Regenerate with:

```bash
python tools/build_exercise_library.py path/to/exercises.json
```

The functional CSV is committed so it is picked up automatically; the
ExerciseDB JSON is 17 MB (mostly translations we drop) and is not, so its path
is passed in.

The importers are committed because the mapping decisions in them, not their
output, are the actual content. A vendored 4,500-entry library nobody can
regenerate is a file nobody dares correct.

## How the merge is arranged

Each source owns its own vocabulary mapping, in its own module:

```
tools/import_exercise_dataset.py    exercisedb  -> library records
tools/import_functional_dataset.py  functional  -> library records
tools/build_exercise_library.py     merge, assign ids, write YAML
```

The build script owns only what must be decided *across* sources — id
assignment, collision handling, and precedence. Precedence is
**exercisedb first, functional second**, and a later source may only fill
enrichment fields the earlier one left empty. Letting a second source rewrite
target muscle or equipment would make the library's meaning depend on import
order.

Two bugs this structure caught, both worth keeping in mind when adding a third
source:

- Sources return **lists, not name-keyed dicts.** Six exercisedb records share
  an exact name with another record; keying by name silently dropped them.
- "Same exercise" means *a different source describes it*. Two identically named
  rows **within** one source are distinct exercises that happen to share a name,
  and both must survive with disambiguated ids.



## What was dropped, and why it was safe

Four source fields were verified redundant across all 1,324 records:

| Dropped | Why |
|---|---|
| `category` | Byte-identical to `body_part` in every record |
| `muscle_group` | Already present in `secondary_muscles` in every record |
| `body_part` | A strict function of `target` — no target maps to two body parts, so it lives on `Muscle.body_part` instead of being repeated 1,324 times |
| 9 of 10 instruction languages | Only English is kept; the rest were ~90% of the file |

Instructions are currently dropped entirely — see *Not yet imported* below.

## The muscle vocabulary is normalised, and that is the point

The source expresses muscles as free text, and collides with itself:

```
traps / trapezius          lats / latissimus dorsi
quads / quadriceps         delts / deltoids / shoulders
chest / pectorals / upper chest        abs / abdominals / core / lower abs
```

Substitution matches on shared muscles, so this is not cosmetic. Left alone, a
barbell row tagged `traps` would not match a shrug tagged `trapezius` — the
candidate silently disappears, and nothing in the output signals that it was
ever considered.

`Muscle` in `hibrid.models` is therefore a closed 30-member enum, and the
importer's `MUSCLE_SYNONYMS` resolves every source spelling into it. Two
judgment calls worth knowing:

- **`core` collapses into `abs`.** As a *secondary* tag it means trunk
  stabilisation. A separate member would overlap `abs`/`obliques` without ever
  being a distinct training target.
- **Grip terms collapse into `forearms`.** `hands`, `wrists`, `grip muscles`,
  `wrist flexors`/`extensors` are regions, not distinct trainable muscles.

`soleus` deliberately stays separate from `calves`: it responds to bent-knee
work specifically, which is a real programming distinction.

Secondary muscles are deduplicated and stripped of the target — the source often
repeats the target inside `secondary_muscles`, and a muscle cannot be a
synergist of itself.

## Movement pattern is derived, and honestly incomplete

The dataset has no movement pattern, but V1 substitution uses one. The importer
derives it from name keywords, falling back to the target muscle for isolation
work. **Coverage is 83%; the remaining 17% is `None`, not a guess.**

`find_substitutes` treats an absent pattern as *unknown*, not as *matches
nothing* — it applies the pattern filter only when both exercises declare one.
An unclassified exercise stays substitutable rather than becoming unreachable.

Rules match on **word boundaries**, not bare substrings. This was found the hard
way: `row` matched inside *"throw down"*, classifying a batch of core exercises
as horizontal pulls. `tests/test_exercise_db.py` pins that case.

Order in `PATTERN_RULES` is load-bearing — *split squat* must reach the lunge
rule before the squat rule sees it, and *reverse fly* is a pull that must be
caught before the fly rule.

## Ids are slugs, not the source's numbers

Routine files are hand-written and reference exercise ids, so `0025` would be a
regression in usability. Ids are slugified names (`barbell-bench-press`). Eight
names are duplicated upstream; only those eight get their numeric id appended,
keeping every other id clean.

## Substitution at 1,300 exercises

Scaling the library changed two behaviours that were fine at 21 exercises:

**Loaded and bodyweight exercises are no longer interchangeable.** The engine
solves weight from volume, so an "implied weight" for a push-up is physically
meaningless. With 325 bodyweight exercises now in the library this went from a
corner case to a common path, so `find_substitutes` refuses the swap. This
closes the bodyweight half of the limitation logged in `variation.py`; the
per-hand-vs-total-bar half is still open.

**Substitutes are ranked, and the top band is sampled rather than truncated.**
`Exercise.similarity` weights a shared target at 0.7 and secondary-muscle
overlap (Jaccard) at 0.3 — an exercise sharing only secondaries trains something
different, so it must never outrank one hitting the same primary target.

But muscle tags are coarse and ties are massive: **39 exercises tie at the top
score for a dumbbell lateral raise.** Taking a fixed top-N off the ranked list
would not pick the best of them — it would pick whichever ids sort first,
biasing every routine toward names beginning with "band" and "barbell". So
`variation.best_matches` keeps everything within `SUBSTITUTE_SCORE_BAND` of the
best score and lets the seeded rng choose among genuinely-equivalent candidates.

## Modality

Every exercise carries a `Modality` — `resistance` (3,845), `plyometric` (335),
`balance` (233), `mobility` (89), `cardio` (29).

The functional source states its discipline directly in
*Primary Exercise Classification*, which is the most reliable modality signal
anywhere in the project's data; the exercisedb records are derived instead.
`Modality.BALANCE` was added for its Balance and Animal Flow work — 233
exercises whose dose is time under control rather than reps, and which serve the
`balance` and `agility` objectives that resistance training cannot reach.

Cardio is decided by **target muscle**, not by name, because that is
authoritative source data rather than a keyword guess; it settles the seven
exercises like *"jack burpee"* and *"mountain climber"* that read as plyometric
by name but are conditioning work. Mobility and plyometric fall back to
word-boundary name matching (*"single leg bridge with outstretched leg"* is
resistance, not mobility — `outstretched` is not `stretch`).

`find_substitutes` never crosses modality. A quad stretch and a leg press share
a target muscle but are not alternatives, and their doses are not even expressed
in the same units.

The counts still make the project's remaining gap concrete: **686 of 4,531
exercises are non-resistance**, and flexibility work is 89 stretches with no
pilates or yoga (deliberately deferred to a later version). No engine change
makes flexibility reachable from this library — that needs content. See
`docs/roadmap.md` M6.

## Enrichment attributes

The functional source carries the attributes the roadmap's enrichment contract
asked for. They are **optional on `Exercise`**, because they are only as good as
the source that supplied them — inventing values for the 1,289 records that
never had them would be worse than an honest `None`.

| Attribute | Coverage | Purpose |
|---|---|---|
| `difficulty` | 71% | Eight levels, ordered via `.rank`. Cold-start progression (M5) |
| `plane_of_motion` | 71% | Sagittal / frontal / transverse |
| `mechanics` | 71% | Compound / isolation |
| `symmetry` | 72% | Bilateral / unilateral / contralateral / ipsilateral |
| `force_type` | 49% | Push / pull / both / other |

`Difficulty` keeps the source's eight levels rather than collapsing to three.
The top four are a real distinction in this domain — a press handstand is not
merely an "advanced" push-up — and collapsing later is trivial where
re-splitting is impossible.

`Symmetry` is deliberately **not** called `Laterality`:
`hibrid.user.enums.Laterality` already means left/right/bilateral for an injury
*site*. Sharing the name would invite exactly the quiet mismatch the
shared-vocabulary rule exists to prevent.

## The known weakness is now fixed

Previously the metric could not separate exercises sharing a target and
secondaries but differing in intent: a dumbbell lateral raise and a cable
external rotation both tag `delts`+`traps` and tied exactly, so the engine
swapped one for the other.

`plane_of_motion` and `force_type` supply that missing signal, and
`Exercise.similarity` now uses them — but only when **both** exercises declare
them, so an enriched exercise is never penalised for being compared against one
from a source that lacked the field. The contribution is applied as a *scale*
rather than an addition, keeping the score in `[0, 1]` and preserving the rule
that a shared target outranks any amount of agreement on secondary axes.

The effect is large. Substitutes for a dumbbell lateral raise went from **39
loosely-tied candidates down to 5**, all of them actual lateral raises, and the
CLI now swaps it for a resistance-band lateral raise instead of a shoulder
external rotation.

Movement-pattern coverage also rose from **83% to 94%**, because the functional
source states its patterns rather than requiring them to be guessed from names.

## Not yet imported

- **Instructions.** English step-by-step text is ~670 KB, roughly 2.6× the rest
  of the library, and no engine reads cueing text. It belongs in a separate
  lazily-loaded file whenever a UI needs it; the importer drops it for now.
- **Media.** Licensed separately — see above.

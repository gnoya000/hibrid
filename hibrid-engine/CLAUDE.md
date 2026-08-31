# hibrid — how to write code here

> **Picking this project up fresh?** Read [HANDOFF.md](HANDOFF.md) first. It
> covers *what we are building and why*; this file covers *how to write code
> here*. For the reasoning behind any rule below, see
> [docs/decisions.md](docs/decisions.md).

The backend for a game-like fitness app: a mobile client over this Python cloud
service. The engine adapts a routine to the person following it, holding each
objective's own training invariant and the session's time while the surface
changes.

| Section | Rule |
|---|---|
| [1. Before writing new code](#1-before-writing-new-code) | The simplicity checklist. Run it first. |
| [2. Code style](#2-code-style) | Types and structure, enforced by `mypy --strict` |
| [3. The four structural rules](#3-the-four-structural-rules) | Where most mistakes happen |
| [4. The exercise library](#4-the-exercise-library) | Generated, not authored |
| [5. Commands](#5-commands) | How to run everything |

---

## 1. Before writing new code

Run this checklist first, and **state which step resolved the decision** before
writing the code, so the reasoning is visible rather than just the result. It is
also encoded as the `simplicity-gate` skill in `.claude/skills/`, and it exists
because the maintainer wants heavily-typed, OOP-structured Python — but *not*
speculative infrastructure.

1. Does this need to exist? → no: skip it (YAGNI)
2. Already in this codebase? → reuse it, don't rewrite
3. Stdlib does it? → use it
4. Native platform feature? → use it
5. Installed dependency? → use it
6. One line? → one line
7. Only then: the minimum that works

Step 1 has teeth. **A field nothing reads is dead weight**, so do not add one
ahead of its consumer — the schema-ahead-of-logic exception in
[docs/user-schema.md](docs/user-schema.md) applies to *user data you would
otherwise have to re-collect*, and to nothing else.

---

## 2. Code style

The maintainer comes from Java and wants Java's rigor around types and
structure, expressed as idiomatic Python — not Java-in-Python.

- **Type hints on every function signature, return type, and class attribute.**
  No bare `Any` except at a true external boundary, such as parsed YAML before
  it is mapped into a typed model.
- **Model structured data as classes.** `@dataclass` for value objects, `Enum`
  for closed sets. Never pass a bare `dict` or `tuple` for anything with more
  than one ephemeral use — `models.py` is the pattern to follow.
- **Prefer explicit `Protocol` / `ABC` interfaces** for anything pluggable, over
  duck typing. `ObjectiveStrategy` is the example.
- **No `*args` / `**kwargs` catch-all signatures.** Explicit named parameters,
  matching the existing `vary_routine` / `vary_entry` style.
- **No metaclasses or dynamic attribute tricks.**
- **Comments carry the argument, not the mechanics.** The codebase's comments
  explain *why a thing is the way it is* and what breaks otherwise. Match that
  register — a comment restating the line below it is noise; a comment recording
  the failure a guard prevents is the most valuable thing in the file.

This is enforced mechanically, not by convention: **`mypy --strict` must pass on
`src/` and `tools/`.** A `PostToolUse` hook in `.claude/settings.json` runs it
after every `.py` edit and blocks on failure. If the hook errors, the usual
cause is a missing `.venv` with dev extras installed.

Test files are outside mypy's scope on purpose — the schema tests deliberately
construct invalid values to assert they are rejected. `tools/` is *inside* it
despite not shipping, because the importers hold the muscle and equipment
mapping tables, where a typo corrupts the whole generated library silently.

The package ships a `py.typed` marker so consumers type-check across the package
boundary. Keep it.

> **Do not add new `M1`–`M9` milestone labels to comments.** The existing ones
> are historical provenance from a numbering scheme with gaps in it; HANDOFF.md
> §3 maps them. The forward-looking build order is numbered from 1 in
> [HANDOFF.md §5](HANDOFF.md#5-what-to-build-next).

---

## 3. The four structural rules

These four are where most mistakes happen, because each one looks like an
inconsistency until you know what it is protecting.

### 3.1 pydantic vs. dataclasses — a boundary, not an inconsistency

- **`hibrid.models`** (`Exercise`, `RoutineEntry`, `Routine`) stays on **stdlib
  dataclasses**. It is internal, built from trusted repo-local YAML, and sits on
  the variation engine's hot path where per-instance validation would cost real
  time during candidate search.
- **`hibrid.user`** uses **pydantic v2**. It ingests untrusted external data —
  device exports, API payloads, forms — where a bad value entering silently
  corrupts every downstream decision. `extra="forbid"` is load-bearing: a
  renamed device field must raise at ingestion, not vanish.
- **`hibrid.api`** is the same boundary as `hibrid.user`, for the same reason.
  Its schemas are pydantic v2 and convert to and from the `hibrid.models`
  dataclasses at the edge. Request and response models never leak past the route
  handlers in `hibrid/api/app.py`.

Both sides share one vocabulary: `Equipment` and `MovementPattern` are imported
from `hibrid.models` and re-exported by `hibrid.user.enums`. **Never fork an
enum** — two copies of a movement vocabulary would break every join between a
routine and a user's history.

### 3.2 The engine core stays pure

`hibrid.models`, `variation.py`, `objective_strategy.py`, `variation_context.py`,
`readiness.py`, `training_memory.py`, `progression.py`, `load_management.py`,
`session_generation.py` and `exercise_db.py` are **pure functions over value
objects** — no I/O, no database session, no network, no clock they did not
receive as a parameter.

That purity is what makes them trivially testable (524 tests in ~4s with no
fixtures beyond the library) and what keeps a future native client possible.
Persistence and HTTP live at the edges — `hibrid/api` and the store — and call
*into* the engine, never the reverse.

`tools/` (build-time importers) is not part of the service at all. Write it for
convenience.

### 3.3 Health data stays on the device

Personal data splits by class, and the split is the safeguard. Identity,
routines, the training log and progress are stored server-side. Health and
biometrics — `HealthProfile`, `Injury`, `MedicalConsideration`,
`RecoveryReading`, `WellnessCheckIn`, `BodyComposition` — are **never persisted
server-side**. The engine accepts them as request-scoped inputs and forgets
them.

One scalar from that bucket arrives on its own rather than inside a model:
`POST /sessions/generate` takes a **`body_mass_kg`**, because a first
prescription with no training history has nothing else to derive a starting load
from. Same rule, no exception — request-scoped, used, forgotten.

In practice, while working here:

- Do not add a table, column or log line that holds a value from the health
  bucket.
- Do not `repr()` one into an error message or a validation error.
- If a feature seems to need health data at rest, **that is a decision to
  escalate, not to implement.**

The full argument — GDPR Art. 9, and the app-store terms that enforce it long
before a regulator does — is in
[decisions.md](docs/decisions.md#health-data-stays-on-the-device).

### 3.4 Every input is tiered, and a lower tier can never veto a higher one

The engine resolves four tiers, and the separation is structural rather than
stylistic:

| Tier | Examples | Can it veto? |
|---|---|---|
| **Inviolable** | health contraindications | Yes — nothing overrides it |
| **Hard constraint** | equipment, session time | Yes |
| **Training correctness** | which invariant an objective preserves, its substitution ceiling | Yes, over anything below |
| **Soft preference** | dislikes, `novelty_preference` | No — a cost term only |
| **Adaptive** | readiness, session intent, accumulated load | No — scales, never vetoes |

The third tier is the one most easily missed. `novelty_preference` is a stated
preference, but *how often a movement may rotate and still be trainable* is a
property of the objective — so `ObjectiveStrategy.variation_policy` bounds it,
and an explicit caller argument does not outrank it either. A preference that
silently defeats the progression layer is not a preference, it is a bug with a
dial on it.

When adding an input, decide its tier first. If you cannot say which one it is,
that is the design question to answer before writing code.

---

## 4. The exercise library

`data/exercises.yaml` holds 4,531 exercises and is **not hand-written**.
Regenerate it with `python tools/build_exercise_library.py <exercises.json>`
rather than editing entries. Corrections belong in the relevant importer's
mapping tables, where they survive the next re-import.

> ⚠️ **The library currently cannot be regenerated** — the exercisedb source JSON
> is not vendored, and the build requires it as `argv[1]`. Importer corrections
> written since then are *pending*, so some shipped labels are known-wrong.
> Details in [docs/known-gaps.md](docs/known-gaps.md#the-library-cannot-be-regenerated).

Two rules matter most when touching the importers:

**A wrong movement pattern is worse than an absent one.** Derived-field rules
are name-matched, and names are ambiguous in ways that create *wrong* data
rather than missing data — a tricep kickback is not a glute kickback, a leg curl
on a pull-up machine is not a vertical pull. Both were real over-matches.
`VariationContext.permits` fails closed on an unknown pattern but lets a
confidently-wrong one straight through the health guard. Simulate a rule change
over the existing library before trusting it, and pin the trap in
`tests/test_importer_patterns.py`.

**`Muscle` is a closed enum, and free text must never re-enter it.** The
upstream data collides with itself (`traps`/`trapezius`, `lats`/`latissimus
dorsi`). Substitution matches on shared muscles, so an unnormalised value does
not error — it silently stops matching its own equivalents. Synonyms are
resolved once, at import.

Read [docs/exercise-library.md](docs/exercise-library.md) before touching
`data/exercises.yaml`, the importers, or the `Muscle` enum.

---

## 5. Commands

```bash
source .venv/bin/activate
pip install -e ".[dev,api]"                             # api extra: hibrid.api + its tests

python -m pytest -q                                     # 524 tests
mypy src tools                                          # strict, must pass
python -m hibrid.cli routines/example_ppl.yaml --seed 7 # run the CLI
python -m hibrid.api                                    # playground on :8000, docs at /docs
```

`playground.http` is a scenario suite for the VS Code REST Client extension,
covering every endpoint, the objective/seed/tolerance knobs, and the algorithm's
known limits. Its inline "observed" notes are **measured behaviour** — when an
engine change makes one stale, update the note rather than deleting it.

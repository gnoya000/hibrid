---
name: simplicity-gate
description: Mandatory pre-implementation checklist for this repo. Run before writing any new function, class, or module to find the minimum real solution instead of custom-building something that already exists somewhere cheaper. Use before starting new feature work, not for reviewing already-written code (that's the simplify skill).
---

# Simplicity Gate

Before writing new code in this repo, walk this checklist in order and stop at the first "yes":

1. **Does this need to exist?** → no: skip it (YAGNI). Don't build for a hypothetical V-next requirement; the project evolves in versions specifically so later needs get handled when they're real.
2. **Already in this codebase?** → reuse it, don't rewrite. Check `models.py`, `exercise_db.py`, `variation.py`, `routine_io.py` before adding a parallel helper.
3. **Stdlib does it?** → use it. Don't add a dependency or hand-roll something `itertools`, `dataclasses`, `enum`, `pathlib`, etc. already provide.
4. **Native platform feature?** → use it.
5. **Installed dependency does it?** → use it (currently: `pyyaml`, `pytest`, `mypy`). Don't reimplement something `pyyaml` or the stdlib already covers.
6. **One line?** → one line. Don't wrap a one-liner in a helper function or class for its own sake.
7. **Only then**: write the minimum that works — matching this repo's typed/OOP conventions in `CLAUDE.md`, but no more abstraction than the current task needs.

State briefly which step resolved the decision (e.g. "step 2 — reuse `ExerciseDB.find_substitutes`") before writing the code, so the reasoning is visible, not just the result.

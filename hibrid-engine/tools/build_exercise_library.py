"""Build ``data/exercises.yaml`` by merging every exercise source.

    python tools/build_exercise_library.py path/to/exercises.json

The functional CSV lives in the repo and is picked up automatically; the
ExerciseDB JSON is not committed (it is 17 MB, mostly translations we drop) so
its path is passed in. Sources own their own vocabulary mapping; this script
owns only what has to be decided *across* sources: id assignment, collision
handling, and precedence when two sources describe the same exercise.

Precedence: ExerciseDB first, functional second. Where both carry an exercise,
the functional record's enrichment attributes (difficulty, force type,
mechanics, plane of motion, symmetry) are merged onto the existing entry rather
than replacing it, so an id already referenced by a routine file keeps its
meaning while still gaining the new fields.
"""

from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

import import_exercise_dataset
import import_functional_dataset

REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = REPO_ROOT / "data" / "exercises.yaml"
FUNCTIONAL_CSV = REPO_ROOT / "data" / "functional_tranining_bare_dataset.csv"

#: Attributes a later source may contribute to an entry an earlier source
#: already created. Deliberately only the enrichment fields -- letting a second
#: source rewrite target muscle or equipment would make the library's meaning
#: depend on import order.
ENRICHMENT_FIELDS = ("difficulty", "force_type", "mechanics", "plane_of_motion", "symmetry")

HEADER = """\
# Exercise library -- GENERATED FILE, do not hand-edit.
#
# Regenerate with:
#   python tools/build_exercise_library.py path/to/exercises.json
#
# Sources
#   exercisedb  https://github.com/hasaneyldrm/exercises-dataset
#               exercise data MIT, (c) 2026 Hasan Emir Yildirim
#               -- see data/exercises.LICENSE. Its images/GIFs are (c) Gym
#               visual, licensed separately, and are NOT included here.
#   functional  data/functional_tranining_bare_dataset.csv
#               kettlebell / clubbell / macebell / sandbag / rings / carry work,
#               plus difficulty, force type, mechanics, plane of motion.
#
# Muscle names are normalised to the Muscle enum in hibrid.models; each source's
# free-text synonyms (traps/trapezius, quadriceps femoris/quadriceps) are
# resolved by its importer. body_part is not stored -- it is derived from
# target. movement_pattern is heuristic and absent where undetermined.

"""


def slugify(name: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", name.lower())).strip("-")


def merge(
    library: dict[str, dict[str, Any]],
    incoming: list[dict[str, Any]],
) -> tuple[int, int]:
    """Fold ``incoming`` into ``library``. Returns (added, enriched)."""
    by_slug = {slugify(fields["name"]): eid for eid, fields in library.items()}
    slug_counts = Counter(slugify(fields["name"]) for fields in incoming)
    added = enriched = 0

    for fields in incoming:
        slug = slugify(fields["name"])
        existing_id = by_slug.get(slug)
        # Only a *different* source describes the same exercise. Two identically
        # named rows within one source are two distinct exercises that happen to
        # share a name, and must both survive with disambiguated ids.
        if existing_id is not None and library[existing_id].get("source") == fields.get("source"):
            existing_id = None
        if existing_id is not None:
            # Same exercise from a second source: keep the established id and
            # take only the attributes the first source could not supply.
            target = library[existing_id]
            gained = {
                key: fields[key]
                for key in ENRICHMENT_FIELDS
                if key in fields and key not in target
            }
            if gained:
                target.update(gained)
                enriched += 1
            continue

        # Names duplicated *within* a source get their source id appended;
        # suffixing only the colliding ones keeps every other id clean and
        # hand-writable in a routine file.
        exercise_id = slug
        if slug_counts[slug] > 1 and fields.get("source_id"):
            exercise_id = f"{slug}-{fields['source_id']}"
        while exercise_id in library:
            exercise_id = f"{exercise_id}-2"
        library[exercise_id] = fields
        by_slug[slug] = exercise_id
        added += 1

    return added, enriched


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 1

    library: dict[str, dict[str, Any]] = {}

    exercisedb = import_exercise_dataset.build(Path(sys.argv[1]))
    added, _ = merge(library, exercisedb)
    print(f"exercisedb : {added} added")

    functional, skipped = import_functional_dataset.build(FUNCTIONAL_CSV)
    added, enriched = merge(library, functional)
    print(f"functional : {added} added, {enriched} enriched existing, {skipped} unmappable")

    OUTPUT_PATH.write_text(
        HEADER + yaml.safe_dump(library, sort_keys=False, allow_unicode=True, width=100)
    )

    print(f"\nwrote {len(library)} exercises to {OUTPUT_PATH.relative_to(REPO_ROOT)}")
    for label, counter in (
        ("modality", Counter(f.get("modality", "resistance") for f in library.values())),
        ("source", Counter(f.get("source", "?") for f in library.values())),
    ):
        print(f"  {label}: {dict(counter.most_common())}")
    for field in ("movement_pattern", *ENRICHMENT_FIELDS):
        n = sum(1 for f in library.values() if field in f)
        print(f"  {field}: {n} ({n / len(library):.0%})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

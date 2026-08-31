"""Guards on the imported exercise library.

data/exercises.yaml is generated from an external dataset, so these tests check
the *import contract* rather than individual entries: that the normalisation
actually collapsed the source's synonyms, that no free-text muscle leaked
through, and that substitution still returns sane candidates at 1300-exercise
scale rather than the 21 it was designed against.
"""

import re
from collections import Counter

import pytest

from hibrid.exercise_db import ExerciseDB
from hibrid.models import (
    BodyPart,
    Difficulty,
    Equipment,
    Modality,
    MovementPattern,
    Muscle,
    Symmetry,
)

SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


@pytest.fixture(scope="module")
def db():
    return ExerciseDB.load()


def test_library_is_fully_imported(db):
    # 1324 from exercisedb + 3207 net-new from the functional CSV (35 of its
    # 3242 rows enrich existing entries rather than adding new ones).
    assert len(db) == 4531
    by_source = Counter(ex.source for ex in db.all())
    assert by_source == {"functional": 3207, "exercisedb": 1324}


def test_every_id_is_a_readable_slug(db):
    # Routine files are hand-written and reference these ids, so "0025" would
    # be a regression even though it is what the source dataset uses.
    assert all(SLUG.match(ex.id) for ex in db.all())


def test_ids_are_unique_and_traceable_to_source(db):
    ids = [ex.id for ex in db.all()]
    assert len(ids) == len(set(ids))
    assert all(ex.source for ex in db.all())
    # Only exercisedb carries an upstream numeric id; the functional CSV has no
    # id column of its own, so its records are traced by source alone.
    assert all(
        re.fullmatch(r"\d{4}", ex.source_id or "")
        for ex in db.all()
        if ex.source == "exercisedb"
    )


def test_no_free_text_muscle_survived_the_import(db):
    """The whole point of the Muscle enum. A raw string here means a synonym
    slipped past the importer and silently stopped matching its equivalents."""
    for ex in db.all():
        assert isinstance(ex.target, Muscle)
        assert all(isinstance(m, Muscle) for m in ex.secondary_muscles)


def test_target_is_never_its_own_secondary(db):
    # The source frequently repeats the target inside secondary_muscles; a
    # muscle cannot be a synergist of itself, and leaving it in would inflate
    # every similarity score.
    assert all(ex.target not in ex.secondary_muscles for ex in db.all())


def test_secondary_muscles_are_deduplicated(db):
    for ex in db.all():
        assert len(ex.secondary_muscles) == len(set(ex.secondary_muscles))


def test_body_part_is_derived_not_stored(db):
    # body_part was dropped at import because it is a strict function of target.
    assert all(isinstance(ex.body_part, BodyPart) for ex in db.all())
    assert db["barbell-bench-press"].body_part is BodyPart.CHEST
    assert db["barbell-bench-press"].target is Muscle.PECTORALS


def test_synonym_collapse_actually_happened(db):
    """traps/trapezius and lats/latissimus dorsi were distinct strings upstream.
    If the collapse failed, one of these sets would come back near-empty."""
    by_muscle = {m: [ex for ex in db.all() if m in ex.muscles] for m in (Muscle.TRAPS, Muscle.LATS)}
    assert len(by_muscle[Muscle.TRAPS]) > 50
    assert len(by_muscle[Muscle.LATS]) > 50


def test_bodyweight_classification(db):
    assert db["barbell-bench-press"].is_bodyweight is False
    assert db["push-up"].is_bodyweight is True
    assert db["push-up"].equipment is Equipment.BODYWEIGHT


def test_throw_down_is_core_not_a_row(db):
    """Regression: 'row' was matched as a bare substring, so 'throw down'
    classified a batch of core exercises as horizontal pulls."""
    throw_downs = [ex for ex in db.all() if "throw down" in ex.name.lower()]
    assert throw_downs
    assert all(ex.movement_pattern.value == "core" for ex in throw_downs)


def test_every_modality_is_represented(db):
    present = {ex.modality for ex in db.all()}
    assert present == set(Modality)


def test_cardio_is_decided_by_target_not_by_name(db):
    """'Jack burpee' and 'mountain climber' read as plyometric by keyword but
    target the cardiovascular system, which is authoritative source data."""
    burpee = next(ex for ex in db.all() if ex.name.lower().startswith("jack burpee"))
    assert burpee.modality is Modality.CARDIO


def test_stretches_are_mobility_not_resistance(db):
    # Word-boundary matched, like the importer: "single leg bridge with
    # outstretched leg" contains "stretch" but is resistance work.
    stretches = [ex for ex in db.all() if re.search(r"\bstretch(?:es|ing)?\b", ex.name.lower())]
    assert len(stretches) > 20
    assert all(ex.modality is Modality.MOBILITY for ex in stretches)
    outstretched = db["single-leg-bridge-with-outstretched-leg"]
    assert outstretched.modality is Modality.RESISTANCE


def test_substitutes_never_cross_modality(db):
    """A quad stretch and a leg press share a target muscle but are not
    alternatives -- their doses are not even in the same units."""
    for exercise_id in ("barbell-bench-press", "push-up"):
        source = db[exercise_id]
        assert all(ex.modality is source.modality for ex in db.find_substitutes(exercise_id))

    stretch = next(ex for ex in db.all() if ex.modality is Modality.MOBILITY)
    assert all(
        ex.modality is Modality.MOBILITY for ex in db.find_substitutes(stretch.id)
    )


def test_functional_equipment_is_representable(db):
    """The point of the functional import: implements the gym-centric library
    had no way to express at all."""
    for equipment in (
        Equipment.KETTLEBELL,
        Equipment.CLUBBELL,
        Equipment.MACEBELL,
        Equipment.SANDBAG,
        Equipment.GYMNASTIC_RINGS,
        Equipment.SLIDERS,
        Equipment.LANDMINE,
        Equipment.BATTLE_ROPES,
    ):
        assert [ex for ex in db.all() if ex.equipment is equipment], equipment


def test_functional_movement_patterns_are_populated(db):
    """A loaded carry is not a squat, a press or a pull. If these came back
    empty the functional patterns were folded into the gym vocabulary."""
    for pattern in (
        MovementPattern.LOADED_CARRY,
        MovementPattern.LOCOMOTION,
        MovementPattern.ROTATION,
        MovementPattern.ISOMETRIC_HOLD,
        MovementPattern.ISOLATION_HIP,
    ):
        assert [ex for ex in db.all() if ex.movement_pattern is pattern], pattern


def test_enrichment_attributes_are_present_where_the_source_had_them(db):
    functional = [ex for ex in db.all() if ex.source == "functional"]
    assert len(functional) > 3000
    assert sum(1 for ex in functional if ex.difficulty is not None) > 3000
    assert sum(1 for ex in functional if ex.plane_of_motion is not None) > 3000
    assert sum(1 for ex in functional if ex.mechanics is not None) > 3000


def test_enrichment_is_absent_rather_than_invented(db):
    """Records the functional source never described carry no difficulty or
    plane of motion. Fabricating values for them would be worse than an honest
    None, so the field stays unset rather than guessed."""
    untouched = [
        ex for ex in db.all() if ex.source == "exercisedb" and ex.mechanics is None
    ]
    assert len(untouched) == 1324 - 35
    assert all(ex.difficulty is None for ex in untouched)
    assert all(ex.plane_of_motion is None for ex in untouched)


def test_cross_source_records_were_enriched_not_duplicated(db):
    """35 exercises appear in both sources. They keep their original id -- a
    routine file referencing one must not break -- and gain the new attributes
    instead of arriving a second time under a different id."""
    bench = db["barbell-bench-press"]
    assert bench.source == "exercisedb"
    assert bench.source_id is not None  # original provenance retained
    assert bench.difficulty is not None  # functional attributes merged in
    assert bench.plane_of_motion is not None

    enriched = [ex for ex in db.all() if ex.source == "exercisedb" and ex.mechanics is not None]
    assert len(enriched) == 35
    assert not [ex for ex in db.all() if ex.name.lower() == "barbell bench press" and ex is not bench]


def test_difficulty_is_ordered(db):
    assert Difficulty.BEGINNER.rank < Difficulty.INTERMEDIATE.rank < Difficulty.LEGENDARY.rank
    ranks = [d.rank for d in Difficulty]
    assert ranks == sorted(ranks)


def test_symmetry_is_not_confused_with_injury_laterality():
    """hibrid.user.enums.Laterality means left/right for an injury *site*.
    Exercise symmetry is a different concept and must not share the name."""
    from hibrid.user.enums import Laterality

    assert {s.value for s in Symmetry} != {latin.value for latin in Laterality}
    assert "unilateral" in {s.value for s in Symmetry}
    assert "left" in {latin.value for latin in Laterality}


def test_plane_of_motion_discriminates_where_muscles_cannot(db):
    """The known weakness this import was meant to fix. Exercises sharing a
    target muscle were previously indistinguishable; plane of motion separates
    them, so a single target must now span more than one plane."""
    for target in (Muscle.DELTS, Muscle.GLUTES, Muscle.ABS):
        planes = {ex.plane_of_motion for ex in db.all() if ex.target is target}
        planes.discard(None)
        assert len(planes) > 1, target


def test_substitutes_share_the_target_muscle(db):
    subs = db.find_substitutes("barbell-bench-press")
    assert subs
    assert all(ex.target is Muscle.PECTORALS for ex in subs)
    assert all(ex.id != "barbell-bench-press" for ex in subs)


def test_substitutes_are_ranked_best_first(db):
    source = db["barbell-bench-press"]
    scores = [source.similarity(ex) for ex in db.find_substitutes("barbell-bench-press")]
    assert scores == sorted(scores, reverse=True)


def test_substitutes_never_cross_the_bodyweight_boundary(db):
    for exercise_id in ("barbell-bench-press", "push-up"):
        source = db[exercise_id]
        assert all(
            ex.is_bodyweight == source.is_bodyweight for ex in db.find_substitutes(exercise_id)
        )


def test_substitutes_respect_equipment_lock(db):
    subs = db.find_substitutes("barbell-bench-press", allow_equipment_change=False)
    assert subs
    assert all(ex.equipment is Equipment.BARBELL for ex in subs)


def test_substitute_limit_returns_the_best_ones(db):
    top = db.find_substitutes("barbell-bench-press", limit=5)
    assert len(top) == 5
    assert top == db.find_substitutes("barbell-bench-press")[:5]


def test_similarity_is_bounded_and_self_maximal(db):
    bench = db["barbell-bench-press"]
    assert bench.similarity(bench) == pytest.approx(1.0)
    assert all(0.0 <= bench.similarity(ex) <= 1.0 for ex in db.all())


def test_similarity_ranks_target_match_above_secondary_overlap(db):
    """An exercise sharing only secondaries trains something different, so it
    must never outrank one that hits the same primary target."""
    bench = db["barbell-bench-press"]
    same_target = next(ex for ex in db.all() if ex.target is bench.target and ex.id != bench.id)
    different_target = next(ex for ex in db.all() if ex.target is not bench.target)
    assert bench.similarity(same_target) > bench.similarity(different_target)


def test_every_muscle_maps_to_a_body_part():
    # Muscle.body_part does a dict lookup; a member added without an entry
    # would raise only when that muscle happened to be queried.
    assert all(isinstance(m.body_part, BodyPart) for m in Muscle)

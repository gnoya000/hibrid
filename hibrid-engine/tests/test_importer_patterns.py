"""Movement-pattern derivation rules in the importers.

Every case here is a real over-match caught while adding ISOLATION_KNEE and
ISOLATION_SCAPULAR -- naive name rules relabelled correct data as wrong data.
A wrong pattern is worse than a missing one, because ``VariationContext.
permits`` fails closed on an unknown pattern but lets a confidently-wrong one
straight through the health guard. These are the traps, pinned.

``tools/`` is not a package, so it goes on the path explicitly.
"""

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tools"))

import import_exercise_dataset as exercisedb  # noqa: E402
import import_functional_dataset as functional  # noqa: E402

from hibrid.models import MovementPattern, Muscle  # noqa: E402


# --- exercisedb: name rules ------------------------------------------------


@pytest.mark.parametrize(
    "name,target,expected",
    [
        # "Kickback" is ambiguous: a tricep kickback is elbow extension, a
        # glute kickback is hip extension. An unqualified rule relabelled 11
        # correct tricep kickbacks as hip work.
        ("Dumbbell tricep kickback", Muscle.TRICEPS, MovementPattern.ISOLATION_ARMS),
        ("Cable two arm tricep kickback", Muscle.TRICEPS, MovementPattern.ISOLATION_ARMS),
        ("Dumbbell kickback", Muscle.TRICEPS, MovementPattern.ISOLATION_ARMS),
        ("Cable glute kickback", Muscle.GLUTES, MovementPattern.ISOLATION_HIP),
        ("Bodyweight donkey kick", Muscle.GLUTES, MovementPattern.ISOLATION_HIP),
    ],
)
def test_kickback_is_disambiguated_by_the_joint_it_moves(name, target, expected):
    assert exercisedb.resolve_pattern(name, target) is expected


def test_knee_isolation_beats_the_machine_it_is_performed_on():
    """This one shipped wrong: the exercise was labelled a vertical pull
    because it is performed on a pull-up cable machine."""
    assert (
        exercisedb.resolve_pattern("Inverse leg curl (on pull-up cable machine)", Muscle.HAMSTRINGS)
        is MovementPattern.ISOLATION_KNEE
    )


@pytest.mark.parametrize(
    "name,target",
    [
        ("Lever leg extension", Muscle.QUADS),
        ("Dumbbell lying femoral", Muscle.HAMSTRINGS),
        ("Assisted prone hamstring", Muscle.HAMSTRINGS),
        ("Lever kneeling leg curl", Muscle.HAMSTRINGS),
    ],
)
def test_single_joint_knee_work_is_knee_isolation(name, target):
    assert exercisedb.resolve_pattern(name, target) is MovementPattern.ISOLATION_KNEE


@pytest.mark.parametrize(
    "name", ["Barbell shrug", "Cable shrug", "Dumbbell incline shrug", "Dumbbell decline shrug"]
)
def test_shrugs_are_scapular_not_glenohumeral(name):
    assert exercisedb.resolve_pattern(name, Muscle.TRAPS) is MovementPattern.ISOLATION_SCAPULAR


def test_a_squat_is_still_a_squat():
    """The knee rules run before the squat rule; they must not swallow it."""
    assert exercisedb.resolve_pattern("Barbell full squat", Muscle.QUADS) is MovementPattern.SQUAT
    assert exercisedb.resolve_pattern("Lever leg press", Muscle.QUADS) is MovementPattern.SQUAT


def test_back_extension_stays_a_hinge_not_hip_isolation():
    """`hip extension` matches ISOLATION_HIP, but the HINGE rule owns
    `back extension` and runs first."""
    assert exercisedb.resolve_pattern("Barbell back extension", Muscle.GLUTES) is MovementPattern.HINGE


def test_cardio_still_has_no_pattern():
    """Settled: a rower or bike is not a horizontal pull."""
    assert exercisedb.resolve_pattern("Stationary bike run", Muscle.CARDIOVASCULAR_SYSTEM) is None


# --- functional: scoped recovery from an over-broad source category --------


def _row(pattern: str) -> dict[str, str]:
    return {"Movement Pattern #1": pattern, "Movement Pattern #2": "", "Movement Pattern #3": ""}


@pytest.mark.parametrize(
    "name",
    [
        "Bodyweight Nordic Hamstring Curl",
        "Cable Prone Bench Hamstring Curl",
        "Stability Ball Hamstring Curl",
        "Slider Hamstring Curl",
    ],
)
def test_knee_dominant_curls_are_recovered_from_the_squat_bucket(name):
    """The source files squats, lunges and curls together under
    'Knee Dominant', which was labelling Nordic curls as SQUAT."""
    assert functional.resolve_pattern(_row("Knee Dominant"), name) is MovementPattern.ISOLATION_KNEE


@pytest.mark.parametrize(
    "name",
    [
        "Ring Tuck Front Lever with Alternating Single Leg Extensions",
        "Bar Tuck Back Lever with Alternating Single Leg Extensions",
        "Bodyweight Glute Bridge Isometric with Alternating Single Leg Extension",
    ],
)
def test_holds_that_merely_mention_a_leg_extension_stay_holds(name):
    """The recovery is scoped to the knee-dominant bucket precisely because
    these name a leg extension performed *during* an isometric hold. Applied
    globally, the same markers turned a front lever into knee isolation."""
    assert functional.resolve_pattern(_row("Isometric Hold"), name) is MovementPattern.ISOMETRIC_HOLD


def test_knee_dominant_squats_are_left_alone():
    assert functional.resolve_pattern(_row("Knee Dominant"), "Barbell Back Squat") is MovementPattern.SQUAT


def test_lunges_are_still_recovered_by_name():
    assert functional.resolve_pattern(_row("Knee Dominant"), "Dumbbell Reverse Lunge") is MovementPattern.LUNGE


def test_functional_scapular_elevation_is_its_own_pattern():
    assert (
        functional.resolve_pattern(_row("Scapular Elevation"), "Barbell Shrug")
        is MovementPattern.ISOLATION_SCAPULAR
    )

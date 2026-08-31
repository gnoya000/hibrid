"""M8a: what this user has actually done, per exercise.

The first module that reads ``hibrid.user.history``. Everything before it looked
at the person as they are *now* -- their constraints, their equipment, this
morning's HRV. This looks at what they have lifted, which is the input every
form of progression needs and none of the earlier milestones had.

It computes ``ExercisePerformanceRecord``, which the schema already declares as
**derived data**: recomputable from the session log, stored only as a
materialised view because "what can this user currently lift on this movement?"
is asked on every prescription and walking full history each time does not
scale. The session log stays the source of truth. Rebuild these; never hand-edit
them.

The headline output is an **estimated 1RM**, and it is worth being clear about
why that number matters more than it looks. Today the engine solves load from
volume, which is why ``playground.http`` §7 has to warn that a ``4x8@80`` bench
becomes ``4x4@160`` under a strength objective -- volume-equivalent, physically
absurd. An e1RM is the reference that makes "heavy" mean something, and the same
number is what would let ``ObjectiveStrategy.target_rpe_range`` (declared since
M2, consumed by nothing) actually drive a prescription.

Three deliberate limits, each a place where a plausible shortcut is wrong:

* **Estimates are refused above ``MAX_ESTIMABLE_REPS``.** Epley and Brzycki are
  validated in the 1-10 rep range and diverge badly beyond it; a 20-rep set
  says far more about endurance than about maximal strength. A refused estimate
  is ``None``, never a quietly extrapolated number.
* **The formula travels with the value.** Epley and Brzycki disagree by several
  percent on the same set, so a bare kilogram figure is uninterpretable. The
  schema has a ``one_rep_max_formula`` field for exactly this reason; it is
  always populated when the estimate is.
* **Only completed and partial sessions count, and only working sets.** A
  skipped session is a real record with real meaning (see
  ``SessionStatus``) but it is evidence about adherence, not about strength.
  Warm-ups are excluded by ``PerformedExercise.working_sets``.
"""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from uuid import UUID

from hibrid.readiness import as_utc
from hibrid.user.enums import SessionStatus
from hibrid.user.history import ExercisePerformanceRecord, PerformedSet, TrainingSession
from hibrid.user.user import User

#: Beyond this, a rep-max formula is extrapolation rather than estimation.
#: Both estimators below were fitted on low-rep sets and diverge sharply above
#: it -- at 20 reps Epley and Brzycki disagree by roughly a quarter.
MAX_ESTIMABLE_REPS = 10

#: Rolling windows the schema's volume fields are defined over. 7-vs-28 is the
#: acute-to-chronic pairing that M8c's deload trigger reads.
ACUTE_WINDOW_DAYS = 7
CHRONIC_WINDOW_DAYS = 28

#: Sessions that describe work actually done. ``SKIPPED`` and ``ABORTED`` are
#: kept in history deliberately -- they are the adherence signal -- but they are
#: not evidence about what this user can lift.
#:
#: Public because ``load_management`` deliberately uses a *different* set and
#: says so against this one: an abandoned session is not evidence about
#: strength, but the work done before it was abandoned still accumulated.
PERFORMED_STATUSES = frozenset(
    {SessionStatus.COMPLETED, SessionStatus.PARTIAL, SessionStatus.UNPLANNED}
)


class OneRepMaxFormula(str, Enum):
    """Which rep-max estimator produced a number.

    A closed enum rather than the schema's free-text ``one_rep_max_formula``
    field, for the reason ``Muscle`` is closed: two spellings of "epley" would
    silently stop comparing equal, and the whole point of recording the formula
    is that values from different ones are not interchangeable.
    """

    EPLEY = "epley"
    BRZYCKI = "brzycki"

    def load_for_reps(self, one_rep_max_kg: float, reps: int) -> float | None:
        """The inverse of ``estimate``: what to load for ``reps`` reps.

        This is what makes a remembered load comparable across rep schemes, and
        the engine varies the scheme on purpose -- so "what they lifted last
        time" is meaningless without it. A user whose last session was 5x100
        and whose next is prescribed at 8 reps should not be given 100 kg.

        Must round-trip with ``estimate`` for the same formula, or a load
        derived from history would drift every time it passed through."""
        if one_rep_max_kg <= 0 or reps < 1 or reps > MAX_ESTIMABLE_REPS:
            return None
        if reps == 1:
            return one_rep_max_kg
        if self is OneRepMaxFormula.EPLEY:
            return one_rep_max_kg / (1.0 + reps / 30.0)
        return one_rep_max_kg * (37.0 - reps) / 36.0

    def estimate(self, load_kg: float, reps: int) -> float | None:
        """Estimated 1RM, or ``None`` where the formula does not apply.

        ``None`` covers a bodyweight or unloaded set (nothing to extrapolate
        from), a set outside the validated rep range, and a zero-rep set. All
        three are cases where returning a number would be inventing data."""
        if load_kg <= 0 or reps < 1 or reps > MAX_ESTIMABLE_REPS:
            return None
        if reps == 1:
            # A completed single IS a one-rep max -- there is nothing to
            # estimate. Special-cased because Epley is not an identity here:
            # w x (1 + 1/30) overstates a genuinely measured max by 3.3%, and
            # that error would propagate into every load solved from it.
            # Brzycki happens to be exact at one rep; relying on that would
            # make correctness depend on which formula the caller chose.
            return load_kg
        if self is OneRepMaxFormula.EPLEY:
            return load_kg * (1.0 + reps / 30.0)
        return load_kg * 36.0 / (37.0 - reps)


@dataclass(frozen=True)
class LastPerformance:
    """The most recent session's working sets for one exercise.

    Kept separate from ``ExercisePerformanceRecord`` because the two answer
    different questions and one cannot be derived from the other. The record is
    a *lifetime* summary -- its ``average_rpe`` is over all history, which is
    exactly the wrong signal for "should this user progress today". Progression
    reads the last session; the record answers "what can they lift at all".
    """

    exercise_id: str
    performed_at: datetime
    sets: tuple[PerformedSet, ...]

    @property
    def mean_rpe(self) -> float | None:
        rpes = [s.rpe for s in self.sets if s.rpe is not None]
        return statistics.fmean(rpes) if rpes else None

    @property
    def form_breakdown(self) -> bool:
        return any(s.form_breakdown for s in self.sets)

    @property
    def pain_reported(self) -> bool:
        return any(s.pain_reported for s in self.sets)

    @property
    def met_prescribed_reps(self) -> bool | None:
        """``None`` when nothing was prescribed to compare against.

        Distinguished from ``False`` on purpose: an unplanned session where the
        user simply trained is not a missed prescription, and treating it as
        one would hold their load back for no reason."""
        compared = [
            (s.reps_completed, s.prescribed_reps)
            for s in self.sets
            if s.prescribed_reps is not None and s.reps_completed is not None
        ]
        if not compared:
            return None
        return all(completed >= prescribed for completed, prescribed in compared)


@dataclass(frozen=True)
class TrainingMemory:
    """Per-exercise history, resolved once and queried many times.

    A stdlib dataclass wrapping pydantic records: the wrapper is internal
    engine state, while ``ExercisePerformanceRecord`` is the schema's declared
    contract and the thing that gets persisted and validated against
    ``User.exercise_records``. Keeping the collection typed rather than passing
    a bare ``dict`` around is the same rule the rest of the engine follows.

    ``as_of`` is stored because every window in the records is measured back
    from it. A memory built for one moment is not valid for another, and the
    rolling volume figures would be silently wrong if it were reused.
    """

    records: dict[str, ExercisePerformanceRecord]
    as_of: datetime
    formula: OneRepMaxFormula = OneRepMaxFormula.EPLEY
    last_performances: dict[str, LastPerformance] = field(default_factory=dict)

    def __contains__(self, exercise_id: str) -> bool:
        return exercise_id in self.records

    def record_for(self, exercise_id: str) -> ExercisePerformanceRecord | None:
        """``None`` means never performed -- which is different from performed
        badly, and callers deciding a starting load need to tell them apart."""
        return self.records.get(exercise_id)

    def last_performance(self, exercise_id: str) -> LastPerformance | None:
        return self.last_performances.get(exercise_id)

    def working_load(self, exercise_id: str, reps: int) -> float | None:
        """What this user should be loading for ``reps`` reps, from history.

        Derived from the estimated 1RM rather than from the last session's
        weight, which matters for two reasons that are easy to miss:

        * **The scheme moves every session by design.** "They lifted 100 kg
          last time" is not an instruction when last time was 5 reps and this
          time is 8.
        * **A deload would otherwise ratchet the user down.** If strain cut
          last session to 90%, reading last session's weight forward would
          treat the reduced load as the new normal, and every subsequent
          session would compound the loss. An e1RM is a best-over-history
          figure, so a light week leaves it untouched.

        ``None`` where no estimate exists or the rep count is outside the
        formula's validated range -- the caller falls back to whatever the
        input routine prescribed."""
        record = self.records.get(exercise_id)
        if record is None or record.estimated_one_rep_max_kg is None:
            return None
        return self.formula.load_for_reps(record.estimated_one_rep_max_kg, reps)

    def estimated_one_rep_max(self, exercise_id: str) -> float | None:
        """Best estimate for this movement, or ``None`` if there isn't one.

        ``None`` here is common and expected, not exceptional: it covers a
        never-performed exercise, a bodyweight one, and one only ever trained
        in sets too long to estimate from."""
        record = self.records.get(exercise_id)
        return record.estimated_one_rep_max_kg if record else None

    @classmethod
    def empty(cls, as_of: datetime) -> "TrainingMemory":
        """The no-history case, named rather than left implicit -- exactly as
        ``VariationContext.unconstrained`` is."""
        return cls(records={}, as_of=as_utc(as_of))

    @classmethod
    def from_sessions(
        cls,
        sessions: Sequence[TrainingSession],
        *,
        user_id: UUID,
        as_of: datetime,
        formula: OneRepMaxFormula = OneRepMaxFormula.EPLEY,
    ) -> "TrainingMemory":
        """Rebuild every per-exercise record from the session log.

        ``as_of`` is required rather than defaulted to now, because these
        records are the input to a prescription and reconstructing a past
        decision has to see the history as it stood *then*. Using later
        sessions to explain an earlier prescription is target leakage -- the
        same reason ``user.latest_before`` exists.
        """
        moment = as_utc(as_of)
        grouped: dict[str, list[tuple[datetime, PerformedSet]]] = {}
        sessions_seen: dict[str, set[UUID]] = {}
        latest: dict[str, LastPerformance] = {}

        for session in sessions:
            if session.status not in PERFORMED_STATUSES:
                continue
            performed_at = as_utc(session.performed_at)
            if performed_at > moment:
                continue
            for exercise in session.exercises:
                sets = exercise.working_sets
                if not sets:
                    continue
                previous = latest.get(exercise.exercise_id)
                if previous is None or performed_at > previous.performed_at:
                    latest[exercise.exercise_id] = LastPerformance(
                        exercise_id=exercise.exercise_id,
                        performed_at=performed_at,
                        sets=sets,
                    )
                # Keyed on what was actually done, not on what was prescribed:
                # a session where the user swapped in a dumbbell press is
                # evidence about the dumbbell press. `substituted_from_
                # exercise_id` keeps the prescription recoverable for the
                # adherence analysis that is M8b's concern, not this one.
                grouped.setdefault(exercise.exercise_id, []).extend(
                    (performed_at, performed_set) for performed_set in sets
                )
                sessions_seen.setdefault(exercise.exercise_id, set()).add(session.session_id)

        records = {
            exercise_id: _build_record(
                exercise_id=exercise_id,
                dated_sets=dated_sets,
                session_count=len(sessions_seen[exercise_id]),
                user_id=user_id,
                as_of=moment,
                formula=formula,
            )
            for exercise_id, dated_sets in grouped.items()
        }
        return cls(
            records=records, as_of=moment, formula=formula, last_performances=latest
        )

    @classmethod
    def from_user(
        cls,
        user: User,
        *,
        as_of: datetime,
        formula: OneRepMaxFormula = OneRepMaxFormula.EPLEY,
    ) -> "TrainingMemory":
        """Rebuild from a whole ``User``.

        Deliberately recomputed from ``user.sessions`` rather than read from
        ``user.exercise_records``: that field is a cache of this computation,
        and trusting a cache the caller may have loaded stale would make the
        source-of-truth rule a comment rather than a behaviour."""
        return cls.from_sessions(
            user.sessions, user_id=user.user_id, as_of=as_of, formula=formula
        )


def _build_record(
    *,
    exercise_id: str,
    dated_sets: list[tuple[datetime, PerformedSet]],
    session_count: int,
    user_id: UUID,
    as_of: datetime,
    formula: OneRepMaxFormula,
) -> ExercisePerformanceRecord:
    best_estimate: float | None = None
    best_set: PerformedSet | None = None
    best_at: datetime | None = None

    for performed_at, performed_set in dated_sets:
        if performed_set.reps_completed is None or performed_set.load_kg is None:
            continue
        estimate = formula.estimate(performed_set.load_kg, performed_set.reps_completed)
        if estimate is None:
            continue
        # Strictly greater, so the *earliest* set achieving a given estimate
        # wins the date. A later set that merely matches an old best is not
        # when the user got stronger.
        if best_estimate is None or estimate > best_estimate:
            best_estimate, best_set, best_at = estimate, performed_set, performed_at

    rpes = [s.rpe for _, s in dated_sets if s.rpe is not None]

    return ExercisePerformanceRecord(
        user_id=user_id,
        exercise_id=exercise_id,
        computed_at=as_of,
        estimated_one_rep_max_kg=best_estimate,
        # Only ever set together with the estimate: a formula name attached to
        # nothing, or a load attached to no formula, are both uninterpretable.
        one_rep_max_formula=formula.value if best_estimate is not None else None,
        best_set_load_kg=best_set.load_kg if best_set else None,
        best_set_reps=best_set.reps_completed if best_set else None,
        best_estimated_1rm_date=best_at,
        last_performed_at=max(performed_at for performed_at, _ in dated_sets),
        total_sessions=session_count,
        total_working_sets=len(dated_sets),
        volume_load_last_7d_kg=_volume_within(dated_sets, as_of, ACUTE_WINDOW_DAYS),
        volume_load_last_28d_kg=_volume_within(dated_sets, as_of, CHRONIC_WINDOW_DAYS),
        average_rpe=statistics.fmean(rpes) if rpes else None,
        # technical_proficiency is deliberately left unset. The schema describes
        # it as confidence informed by form-breakdown flags and exposure count,
        # but no consumer exists yet and inventing a formula now would mean a
        # number nothing validates -- the same reason the enrichment contract
        # refuses to add columns ahead of the logic that reads them.
        technical_proficiency=None,
    )


def _volume_within(
    dated_sets: list[tuple[datetime, PerformedSet]], as_of: datetime, days: int
) -> float:
    """Working-set volume load inside a trailing window.

    Sets missing reps or load contribute nothing rather than raising: a plank
    logged against a strength exercise has no volume load, and dropping it is
    correct, not an error."""
    window_start = as_of - timedelta(days=days)
    return sum(
        performed_set.volume_load_kg or 0.0
        for performed_at, performed_set in dated_sets
        if window_start <= performed_at <= as_of
    )

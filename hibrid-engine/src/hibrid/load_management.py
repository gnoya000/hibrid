"""M8c: what the last four weeks, and the next two, say about today's dose.

The third and last piece of M8. M8a remembered what the user has lifted, M8b
turned that into a working load for one movement. This reads the *whole* log at
session granularity and answers a question neither of them can: is this person
accumulating work faster than they are adapting to it, and is there a date they
are supposed to be sharp for?

Unlike progression, this composes cleanly with what already exists. Progression
had to replace the reference load, because "add 2.5 kg" is an increment against
a remembered target rather than a scale factor. Load management is a scale
factor -- another multiplicative term beside session intent and readiness, on
the same volume target they already move.

Two inputs, deliberately different in kind:

* **The acute:chronic workload ratio** (``TrainingLoadSummary``) -- a
  measurement of what the user has already done. Like readiness, it is judged
  against this user's own recent history rather than any population figure, and
  it only ever moves the dose *down*.
* **A ``TargetEvent`` taper** -- a directive implied by a date the user chose.
  Like ``SessionIntent`` it needs no baseline at all: a race in nine days is a
  race in nine days on install day.

Five decisions worth knowing before changing anything here:

* **The chronic load is normalised to the acute window's length**, so a steady
  trainee sits at a ratio near 1.0 and the thresholds below mean what the
  published ones mean. ``TrainingLoadSummary.chronic_load_28d`` therefore holds
  the 28-day window's *weekly average*, not its total -- dividing a 7-day total
  by a 28-day total would put steady training at 0.25 and make every threshold
  a private invention. The field carries that note in the schema too.
* **Thin or short history is ``UNKNOWN``, never ``OPTIMAL``.** A log that does
  not yet reach back four weeks has an artificially small chronic load, so
  every ordinary week reads as a spike -- which is the standard criticism of
  this ratio and the reason it is guarded rather than trusted. Someone
  returning from a layoff hits the same guard: their first week back is
  infinitely more than the nothing before it, and no honest number comes out of
  that.
* **The ratio only ever reduces load.** A ratio *below* the sweet spot means
  the user is detrained relative to a month ago, and the response to that is
  progressive overload -- which M8b already owns, one increment at a time and
  anchored on measured effort. Adding a second, independent upward push here
  would double-count it. This keeps the asymmetry the whole design rests on:
  backing off needs no permission, pushing does.
* **The taper and the ratio combine by taking the deeper cut, not by
  multiplying.** Both are protective reductions of the same quantity for
  different reasons, and 0.55 x 0.75 is 0.41 -- a cut neither input asked for
  and no coach would write. Whichever binds is named in ``explain()``.
  Multiplication is still right *between* modules: readiness is about today and
  this is about the block, so a user who is both acutely wrecked and chronically
  overloaded should get both reductions.
* **Adherence is computed but not consumed.** ``sessions_completed`` /
  ``sessions_prescribed`` are filled in because the summary is a persistable
  view and leaving them zero would make ``adherence_rate`` read "nothing was
  ever prescribed". Nothing in the engine reads them yet.

**Known limit, stated rather than discovered later: this tapers volume by
lowering load, when a real taper lowers volume and *holds* intensity.** The
engine solves weight from a volume target, so a reduced target comes out as a
lighter bar rather than fewer sets at the same bar. That is the correct shape
for a strain deload and the wrong shape for peaking -- an athlete tapering for a
meet needs to keep touching near-maximal loads. Fixing it means letting the
candidate search drop sets while holding the solved load near the reference,
which is a change to ``vary_entry``'s search rather than to this module. Until
then this delivers the taper half of "peaking and taper" and not the peaking
half.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import Enum
from uuid import UUID

from hibrid.readiness import as_utc
from hibrid.training_memory import ACUTE_WINDOW_DAYS, CHRONIC_WINDOW_DAYS
from hibrid.user.enums import SessionStatus
from hibrid.user.history import TrainingLoadSummary, TrainingSession
from hibrid.user.objectives import TargetEvent
from hibrid.user.user import User

#: The conventional "sweet spot" band for the acute:chronic ratio: enough new
#: work to drive adaptation, not so much that the body is behind it. Numbers
#: from the injury-risk literature rather than from this project's data, and
#: kept as named constants for the reason ``docs/roadmap.md`` M7 gives -- they
#: will be revised by a human reading a paper, never by a training job.
SWEET_SPOT_RATIO = (0.8, 1.3)

#: Above this the ratio is in the range repeatedly associated with elevated
#: injury risk. Two tiers rather than one so the response is proportionate, and
#: the multipliers below match ``readiness.py``'s on purpose: one vocabulary of
#: protective cuts is easier to argue with than two.
SPIKE_RATIO = 1.5

#: Measurable sessions needed inside the chronic window before the average
#: means anything. Below roughly 1.5 sessions a week the weekly average is
#: dominated by whether one session happened to land inside the window, and the
#: ratio swings wildly on no new information.
MIN_CHRONIC_SESSIONS = 6

#: How long before a target event the taper begins. The meta-analytic support
#: sits at 8-14 days; the wider end is used so the reduction can be gradual
#: rather than a cliff the user notices as a broken app.
TAPER_WINDOW_DAYS = 14

#: Volume fraction on event day. A 40-60% reduction is the range the taper
#: literature supports; 0.55 sits inside it. Intensity is supposed to be held
#: while this falls -- see the module docstring for why it currently is not.
PEAK_VOLUME_FRACTION = 0.55

#: Sessions that cost the body something. This deliberately differs from
#: ``training_memory.PERFORMED_STATUSES``, which additionally excludes
#: ``ABORTED``: the two sets answer different questions of the same record. An
#: abandoned session is not evidence about what the user can lift, but the work
#: they did before abandoning it still accumulated. ``SKIPPED`` is the only
#: status that describes no work at all.
LOAD_BEARING_STATUSES = frozenset(
    {
        SessionStatus.COMPLETED,
        SessionStatus.PARTIAL,
        SessionStatus.UNPLANNED,
        SessionStatus.ABORTED,
    }
)

#: Sessions the user was meant to do, for the adherence denominator. An
#: unplanned session was never prescribed, so counting it would let extra
#: training paper over a missed prescription.
PRESCRIBED_STATUSES = frozenset(
    {
        SessionStatus.COMPLETED,
        SessionStatus.PARTIAL,
        SessionStatus.SKIPPED,
        SessionStatus.ABORTED,
    }
)


class LoadMetric(str, Enum):
    """How one session's workload is measured.

    A closed choice that travels with the value, for the same reason
    ``OneRepMaxFormula`` does: the two units are not interchangeable, and a
    ratio built from a mix of them is meaningless rather than approximate. The
    window sums never fall back from one to the other -- a session the chosen
    metric cannot measure is invisible to it, which understates load rather
    than inventing it.
    """

    #: session-RPE x duration in minutes. The standard cheap workload unit, and
    #: the only one here that a run, a circuit and a squat session all report in
    #: the same currency.
    SESSION_RPE = "session_rpe"

    #: Summed reps x load over working sets. Available from a plain lifting log
    #: with no perceived-exertion entry at all, but blind to every non-resistance
    #: session -- which is exactly the cross-modality currency problem roadmap M7
    #: is about.
    VOLUME_LOAD = "volume_load"

    def of(self, session: TrainingSession) -> float | None:
        """``None`` when this session carries nothing this metric can read."""
        if self is LoadMetric.SESSION_RPE:
            return session.session_load
        total = session.total_volume_load_kg
        return total if total > 0 else None


class WorkloadState(str, Enum):
    """The verdict on accumulated load. ``UNKNOWN`` is not ``OPTIMAL``."""

    UNKNOWN = "unknown"
    UNDERLOADED = "underloaded"
    OPTIMAL = "optimal"
    ELEVATED = "elevated"
    SPIKE = "spike"

    @property
    def load_multiplier(self) -> float:
        """What to scale an entry's volume target by. Never above 1.0."""
        return _STATE_MULTIPLIER[self]

    @property
    def reason(self) -> str:
        return _STATE_REASON[self]


_STATE_MULTIPLIER: dict[WorkloadState, float] = {
    WorkloadState.UNKNOWN: 1.0,
    WorkloadState.UNDERLOADED: 1.0,
    WorkloadState.OPTIMAL: 1.0,
    WorkloadState.ELEVATED: 0.90,
    WorkloadState.SPIKE: 0.75,
}

_STATE_REASON: dict[WorkloadState, str] = {
    WorkloadState.UNKNOWN: (
        "not enough logged training to compare this week against a four-week "
        "average -- too few sessions, or a log that does not yet reach back a "
        "full four weeks. The dose was left exactly as prescribed, which is NOT "
        "the same as having checked and found the workload sensible"
    ),
    WorkloadState.UNDERLOADED: (
        "this week is well below this user's own four-week average. Nothing was "
        "added for it: rebuilding after a light block is progressive overload, "
        "which the progression layer already does one increment at a time"
    ),
    WorkloadState.OPTIMAL: (
        "this week sits in the usual band relative to this user's own four-week "
        "average, so the prescribed dose stands"
    ),
    WorkloadState.ELEVATED: (
        "this week is running ahead of this user's own four-week average -- the "
        "volume target was trimmed, holding sets, reps and session time"
    ),
    WorkloadState.SPIKE: (
        "this week is far ahead of this user's own four-week average, the "
        "pattern most consistently associated with injury -- the volume target "
        "was cut back accordingly"
    ),
}


@dataclass(frozen=True)
class WorkloadAssessment:
    """The acute:chronic verdict, carrying the summary it was read from.

    The evidence travels with the verdict for the reason
    ``BaselineComparison`` does: a user told to train lighter will ask why, and
    "this week is 1.8x your four-week average" answers that where a state name
    cannot.
    """

    state: WorkloadState
    metric: LoadMetric
    #: ``None`` only when there were no sessions at all to summarise. A summary
    #: exists even for ``UNKNOWN``, because "you have logged three sessions" is
    #: itself the explanation.
    summary: TrainingLoadSummary | None = None

    @property
    def load_multiplier(self) -> float:
        return self.state.load_multiplier

    @property
    def modulates_load(self) -> bool:
        return self.load_multiplier != 1.0

    @property
    def acute_chronic_ratio(self) -> float | None:
        return self.summary.acute_chronic_ratio if self.summary else None

    def describe(self) -> str:
        ratio = self.acute_chronic_ratio
        if self.summary is None or ratio is None:
            return self.state.reason
        return (
            f"{self.state.reason}: {self.metric.value} load {self.summary.acute_load_7d:.0f} "
            f"this week against a {self.summary.chronic_load_28d:.0f} weekly average "
            f"(ratio {ratio:.2f})"
        )


@dataclass(frozen=True)
class TaperPlan:
    """How far into a taper toward one dated event today sits.

    Always constructed when an event is supplied, even far out from it, so the
    output can say "your event is 40 days away and nothing was changed for it"
    rather than being silent in a way that looks like the feature is missing.
    """

    event_name: str
    event_date: date
    days_until_event: int
    load_multiplier: float

    @property
    def is_tapering(self) -> bool:
        return self.load_multiplier < 1.0

    def describe(self) -> str:
        if self.days_until_event < 0:
            return f"{self.event_name} has passed; nothing was changed for it"
        if not self.is_tapering:
            return (
                f"{self.event_name} is {self.days_until_event} days away, outside "
                f"the {TAPER_WINDOW_DAYS}-day taper window -- nothing was changed for it"
            )
        return (
            f"tapering for {self.event_name}, {self.days_until_event} days away: "
            f"the volume target was scaled to {self.load_multiplier:.2f} of normal, "
            "holding session time"
        )

    @classmethod
    def for_event(cls, event: TargetEvent, *, as_of: datetime) -> "TaperPlan":
        days = (event.event_date - as_utc(as_of).date()).days
        return cls(
            event_name=event.name,
            event_date=event.event_date,
            days_until_event=days,
            load_multiplier=_taper_multiplier(days),
        )


def _taper_multiplier(days_until_event: int) -> float:
    """Linear from 1.0 at the window's edge to ``PEAK_VOLUME_FRACTION`` on the day.

    Ramped rather than stepped because a single cliff-edge drop is both harder
    to justify physiologically and reads as a bug to the user who trains on
    either side of it. A past event changes nothing: what to do *after* a race
    depends on how it went, and the log cannot say that yet.
    """
    if days_until_event < 0 or days_until_event >= TAPER_WINDOW_DAYS:
        return 1.0
    progress = (TAPER_WINDOW_DAYS - days_until_event) / TAPER_WINDOW_DAYS
    return 1.0 - (1.0 - PEAK_VOLUME_FRACTION) * progress


@dataclass(frozen=True)
class LoadManagementAssessment:
    """What accumulated load and an upcoming event say about today's volume.

    A stdlib dataclass rather than a pydantic model, matching
    ``ReadinessAssessment`` and ``VariationContext``: by the time this exists
    the untrusted sessions have been validated at the ``hibrid.user`` boundary.
    """

    workload: WorkloadAssessment | None = None
    taper: TaperPlan | None = None

    @property
    def load_multiplier(self) -> float:
        """The deeper of the two cuts, never their product.

        Both terms reduce the same quantity for different reasons, so
        compounding them would prescribe a session neither input asked for.
        Taking the minimum satisfies whichever is more protective and leaves
        the other visible in ``explain()``.
        """
        return min(
            self.workload.load_multiplier if self.workload else 1.0,
            self.taper.load_multiplier if self.taper else 1.0,
        )

    @property
    def modulates_load(self) -> bool:
        return self.load_multiplier != 1.0

    @property
    def binding_taper(self) -> bool:
        """Whether the taper, rather than the workload ratio, set the number.

        Worth distinguishing: one is the user's own race showing up in their
        programme, the other is the engine telling them they have overreached.
        """
        return self.taper is not None and self.taper.load_multiplier <= self.load_multiplier < 1.0

    def explain(self) -> str:
        """Every term, binding or not, deepest cut first."""
        parts = []
        if self.taper is not None:
            parts.append(self.taper.describe())
        if self.workload is not None:
            parts.append(self.workload.describe())
        return "; ".join(parts) if parts else "no training history and no target event"

    @classmethod
    def none(cls) -> "LoadManagementAssessment":
        """Nothing known. Named, so "we did not look" is explicit in the engine."""
        return cls()

    @classmethod
    def from_sessions(
        cls,
        sessions: Sequence[TrainingSession],
        *,
        as_of: datetime,
        event: TargetEvent | None = None,
        metric: LoadMetric = LoadMetric.SESSION_RPE,
    ) -> "LoadManagementAssessment":
        """Summarise the log and resolve any taper.

        ``as_of`` is required rather than defaulted to now for the reason
        ``TrainingMemory.from_sessions`` gives: both windows are measured back
        from it, and reconstructing a past prescription has to see the history
        as it stood then.

        The owning user is read off the sessions rather than passed in
        separately -- they already carry it, and a second source for the same
        fact is a way to get it wrong. Sessions from more than one user raise,
        because a blended log is exactly the error that stays silent until
        someone's training data has been mixed with a stranger's.
        """
        moment = as_utc(as_of)
        return cls(
            workload=_assess_workload(sessions, moment, metric),
            taper=TaperPlan.for_event(event, as_of=moment) if event is not None else None,
        )

    @classmethod
    def from_user(
        cls,
        user: User,
        *,
        as_of: datetime,
        metric: LoadMetric = LoadMetric.SESSION_RPE,
    ) -> "LoadManagementAssessment":
        """Rebuild from a whole ``User``, taking the nearest upcoming event.

        Deliberately recomputed from ``user.sessions`` rather than read from
        ``user.load_summary``: that field is a cache of this computation, and
        trusting a cache the caller may have loaded stale would make the
        source-of-truth rule a comment rather than a behaviour.
        """
        return cls.from_sessions(
            user.sessions,
            as_of=as_of,
            event=next_target_event(user, as_of=as_of),
            metric=metric,
        )


def next_target_event(user: User, *, as_of: datetime) -> TargetEvent | None:
    """The soonest event an active goal is pointed at, if any.

    Ties break toward the more important event, which is the only thing
    ``TargetEvent.importance`` is read for. It deliberately does not scale how
    deep the taper goes: an event either is being peaked for or is not, and
    interpolating a physiological decision through a 1-10 slider would be a
    formula with nothing behind it.
    """
    today = as_utc(as_of).date()
    upcoming = [
        goal.target_event
        for goal in user.active_goals
        if goal.target_event is not None and goal.target_event.event_date >= today
    ]
    if not upcoming:
        return None
    return min(upcoming, key=lambda event: (event.event_date, -event.importance))


def _assess_workload(
    sessions: Sequence[TrainingSession], as_of: datetime, metric: LoadMetric
) -> WorkloadAssessment | None:
    if not sessions:
        return None

    dated = [(as_utc(session.performed_at), session) for session in sessions]
    acute_start = as_of - timedelta(days=ACUTE_WINDOW_DAYS)
    chronic_start = as_of - timedelta(days=CHRONIC_WINDOW_DAYS)

    acute = 0.0
    chronic = 0.0
    measurable = 0
    completed = 0
    prescribed = 0
    for performed_at, session in dated:
        if not chronic_start <= performed_at <= as_of:
            continue
        if session.status in PRESCRIBED_STATUSES:
            prescribed += 1
            if session.status is SessionStatus.COMPLETED:
                completed += 1
        if session.status not in LOAD_BEARING_STATUSES:
            continue
        load = metric.of(session)
        if load is None:
            continue
        measurable += 1
        chronic += load
        if performed_at >= acute_start:
            acute += load

    summary = TrainingLoadSummary(
        user_id=_single_user_id(sessions),
        # The moment being planned for, not wall-clock now: a summary stamped
        # with a later time than the window it covers cannot be reconciled with
        # the decision it justified.
        computed_at=as_of,
        window_end=as_of,
        acute_load_7d=acute,
        # Normalised to the acute window's length so the ratio is the
        # conventional one -- see the module docstring.
        chronic_load_28d=chronic / (CHRONIC_WINDOW_DAYS / ACUTE_WINDOW_DAYS),
        # Deliberately left empty: a TrainingSession does not record which
        # objective it served, and recovering that needs the prescribing
        # routine, which has no store to resolve against until roadmap M9.
        volume_load_by_objective={},
        sessions_completed=completed,
        sessions_prescribed=prescribed,
    )
    covers_window = min(performed_at for performed_at, _ in dated) <= chronic_start
    return WorkloadAssessment(
        state=_resolve_state(summary.acute_chronic_ratio, measurable, covers_window),
        metric=metric,
        summary=summary,
    )


def _resolve_state(
    ratio: float | None, measurable_sessions: int, covers_window: bool
) -> WorkloadState:
    """Refuse to judge before comparing, exactly as ``readiness.py`` does.

    ``covers_window`` is the guard that stops a new user's every ordinary week
    from reading as a spike: until the log reaches back a full four weeks the
    chronic average is divided by weeks that could not have contained training,
    so it is small for a reason that has nothing to do with this user.
    """
    if ratio is None or measurable_sessions < MIN_CHRONIC_SESSIONS or not covers_window:
        return WorkloadState.UNKNOWN
    low, high = SWEET_SPOT_RATIO
    if ratio >= SPIKE_RATIO:
        return WorkloadState.SPIKE
    if ratio > high:
        return WorkloadState.ELEVATED
    if ratio < low:
        return WorkloadState.UNDERLOADED
    return WorkloadState.OPTIMAL


def _single_user_id(sessions: Sequence[TrainingSession]) -> UUID:
    owners = {session.user_id for session in sessions}
    if len(owners) > 1:
        raise ValueError(
            "sessions belong to more than one user: "
            f"{sorted(str(owner) for owner in owners)}"
        )
    return owners.pop()

"""M3 pass 2: strain and recovery, read against the user's own baseline.

Pass 1 answered *what this person may be given* — contraindications, equipment,
dislikes. This answers a different question that the same schema was built for:
*how much work should this body take today*. It is the one thing that changes
between two runs of the same routine for the same person, and it is why
``biometrics.py`` records dated immutable snapshots instead of current-value
fields.

**Everything here is relative to the user's own history, never to a population
threshold.** An HRV of 45 ms is unremarkable for one person and a 30% crash for
another; "is this reading suppressed against this user's own 28-day baseline"
is the only form of the question the data can actually answer. That is stated
in ``biometrics.py``'s module docstring as the reason the schema is shaped this
way, and it is the rule this module implements.

Four deliberate calls, each one a place where a plausible alternative was
rejected:

* **Objective and subjective evidence stay separate signals.**
  ``RecoveryReading`` (wearable) and ``WellnessCheckIn`` (self-report) have
  different failure modes — sensors miss life stress, self-report is biased —
  so they are compared independently and each contributes its own signal.
  ``ReadinessMetric.is_objective`` keeps which one fired recoverable, because
  "HRV is down" and "they feel terrible" warrant different follow-ups.
* **Vendor ``readiness_score`` / ``strain_score`` are deliberately NOT read.**
  They are opaque functions of the same HRV and resting-heart-rate inputs read
  here, so counting both double-weights one piece of physiology, and their
  formulas change without notice. They stay in the schema as evidence; they are
  not an input to this decision.
* **Modulation is downward only.** A suppressed user gets less work. A user
  whose readings are *better* than baseline does not get more, because
  increasing prescribed volume is progressive overload — a decision that needs
  accumulated training load (``TrainingLoadSummary.acute_chronic_ratio``) and
  belongs to roadmap M8. Backing off needs no such context.
* **Absent or thin data means ``UNKNOWN``, which changes nothing.** A z-score
  off two readings is noise, and a reading from three weeks ago is not evidence
  about today. Both are distinguished from ``NORMAL`` so that "we did not
  deload" is never confused with "we checked and they were fine".

The multipliers below are explicit editable heuristics, in the sense
``docs/roadmap.md`` M7 means it: start with numbers a human can argue with and
replace them with fitted values once real adherence and outcome data exists.
"""

from __future__ import annotations

import statistics
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import TypeVar

from hibrid.user.biometrics import MeasurementRecord, RecoveryReading, WellnessCheckIn

#: Trailing window a reading is compared against. 28 days is long enough to
#: absorb a normal training week's ups and downs and short enough to track a
#: genuine shift in fitness rather than averaging it away.
BASELINE_WINDOW_DAYS = 28

#: Readings needed inside that window before a baseline means anything. Below
#: this the standard deviation is dominated by sampling noise, and a z-score
#: computed from it would deload people at random.
MIN_BASELINE_READINGS = 7

#: How stale the newest reading may be and still describe today. A wearable
#: that was not worn last night has no opinion about this session.
MAX_READING_AGE_HOURS = 48

#: Standard deviations from baseline that count as suppression. 1.0 is the
#: conventional "outside normal daily variation" line used by HRV-guided
#: training protocols.
SUPPRESSION_Z = 1.0

RecordT = TypeVar("RecordT", bound=MeasurementRecord)


class ReadinessMetric(str, Enum):
    """A continuous signal compared against the user's own baseline.

    Closed enum for the same reason ``Muscle`` is: these are the metrics the
    engine actually reads, and a free-text metric name would silently stop
    matching itself between the comparison and whatever reports it."""

    HRV_RMSSD = "hrv_rmssd"
    RESTING_HEART_RATE = "resting_heart_rate"
    PERCEIVED_RECOVERY = "perceived_recovery"
    ENERGY = "energy"
    SORENESS = "soreness"

    @property
    def is_objective(self) -> bool:
        """Sensor-measured rather than self-reported."""
        return self in (ReadinessMetric.HRV_RMSSD, ReadinessMetric.RESTING_HEART_RATE)

    @property
    def higher_is_better(self) -> bool:
        """Which direction of deviation means *worse* readiness.

        Without this the sign of a z-score is meaningless: HRV falling and
        resting heart rate rising are the same physiological event."""
        return self not in (ReadinessMetric.RESTING_HEART_RATE, ReadinessMetric.SORENESS)


class ReadinessFlag(str, Enum):
    """A categorical self-report that has no baseline to compare against.

    Illness is not a z-score. These are read as absolutes precisely because
    the baseline-relative rule does not apply to them -- a user does not have a
    normal amount of fever to deviate from."""

    ILLNESS_REPORTED = "illness_reported"
    INJURY_FLARE_REPORTED = "injury_flare_reported"


class ReadinessState(str, Enum):
    """The engine-facing verdict. ``UNKNOWN`` is not ``NORMAL``."""

    UNKNOWN = "unknown"
    NORMAL = "normal"
    SUPPRESSED = "suppressed"
    STRONGLY_SUPPRESSED = "strongly_suppressed"

    @property
    def load_multiplier(self) -> float:
        """What to scale an entry's volume target by. Never above 1.0."""
        return _STATE_MULTIPLIER[self]

    @property
    def reason(self) -> str:
        return _STATE_REASON[self]


_STATE_MULTIPLIER: dict[ReadinessState, float] = {
    ReadinessState.UNKNOWN: 1.0,
    ReadinessState.NORMAL: 1.0,
    ReadinessState.SUPPRESSED: 0.90,
    ReadinessState.STRONGLY_SUPPRESSED: 0.75,
}

_STATE_REASON: dict[ReadinessState, str] = {
    ReadinessState.UNKNOWN: (
        "no recovery or wellness data close enough to today, or too few "
        "readings in the trailing window to establish a baseline -- the dose "
        "was left exactly as prescribed, which is NOT the same as having "
        "checked and found this user recovered"
    ),
    ReadinessState.NORMAL: (
        "the latest readings sit inside this user's own normal variation, so "
        "the prescribed dose stands"
    ),
    ReadinessState.SUPPRESSED: (
        "one signal is outside this user's own normal variation -- the volume "
        "target was reduced, holding sets, reps and session time"
    ),
    ReadinessState.STRONGLY_SUPPRESSED: (
        "illness or an injury flare was reported, or two or more signals are "
        "outside this user's own normal variation -- the volume target was "
        "cut back accordingly"
    ),
}


@dataclass(frozen=True)
class BaselineComparison:
    """One metric's latest reading against its own trailing baseline.

    Carries the inputs, not just the verdict. A deload a user did not expect is
    the sort of output that gets argued with, and "your HRV was 38 ms against a
    28-day mean of 55 ms" answers the argument where a bare state cannot."""

    metric: ReadinessMetric
    latest: float
    baseline_mean: float
    baseline_sd: float
    sample_size: int
    z_score: float

    @property
    def indicates_suppression(self) -> bool:
        if self.metric.higher_is_better:
            return self.z_score <= -SUPPRESSION_Z
        return self.z_score >= SUPPRESSION_Z

    def describe(self) -> str:
        direction = "below" if self.z_score < 0 else "above"
        return (
            f"{self.metric.value} {self.latest:.1f} is {abs(self.z_score):.1f} SD "
            f"{direction} a {self.sample_size}-reading baseline of "
            f"{self.baseline_mean:.1f}"
        )


@dataclass(frozen=True)
class ReadinessAssessment:
    """How much work this person should take today, and the evidence for it.

    A stdlib dataclass rather than a pydantic model, matching
    ``VariationContext``: by the time this exists the untrusted readings have
    already been validated at the ``hibrid.user`` boundary."""

    state: ReadinessState
    comparisons: tuple[BaselineComparison, ...] = ()
    flags: frozenset[ReadinessFlag] = frozenset()
    as_of: datetime | None = None

    @property
    def load_multiplier(self) -> float:
        return self.state.load_multiplier

    @property
    def modulates_load(self) -> bool:
        return self.load_multiplier != 1.0

    @property
    def suppressing_metrics(self) -> tuple[ReadinessMetric, ...]:
        return tuple(c.metric for c in self.comparisons if c.indicates_suppression)

    def explain(self) -> str:
        """One line naming the state and every signal that drove it."""
        evidence = [c.describe() for c in self.comparisons if c.indicates_suppression]
        evidence.extend(sorted(flag.value for flag in self.flags))
        if not evidence:
            return self.state.reason
        return f"{self.state.reason}: {'; '.join(evidence)}"

    @classmethod
    def unknown(cls) -> "ReadinessAssessment":
        """No data. Named rather than left implicit, so that "we did not look"
        is an explicit state in the engine."""
        return cls(state=ReadinessState.UNKNOWN)

    @classmethod
    def assess(
        cls,
        *,
        recovery: Sequence[RecoveryReading] = (),
        wellness: Sequence[WellnessCheckIn] = (),
        as_of: datetime | None = None,
    ) -> "ReadinessAssessment":
        """Compare the newest reading in each channel against its own baseline.

        ``as_of`` is the moment being planned for; it defaults to now, and is
        accepted explicitly so that a decision can be reconstructed from the
        history as it stood *then*. Explaining a past prescription with today's
        readings is target leakage -- the same reason ``user.latest_before``
        exists."""
        moment = as_utc(as_of) if as_of is not None else datetime.now(timezone.utc)
        window_start = moment - timedelta(days=BASELINE_WINDOW_DAYS)

        comparisons: list[BaselineComparison] = []
        comparisons.extend(_compare_channel(recovery, _RECOVERY_METRICS, moment, window_start))
        comparisons.extend(_compare_channel(wellness, _WELLNESS_METRICS, moment, window_start))

        flags = _report_flags(wellness, moment)
        return cls(
            state=_resolve_state(comparisons, flags),
            comparisons=tuple(comparisons),
            flags=flags,
            as_of=moment,
        )


#: Which field on each record type carries each metric. Accessors rather than
#: field-name strings so mypy checks the shape of every read.
_RECOVERY_METRICS: dict[ReadinessMetric, Callable[[RecoveryReading], float | None]] = {
    ReadinessMetric.HRV_RMSSD: lambda reading: reading.hrv_rmssd_ms,
    ReadinessMetric.RESTING_HEART_RATE: lambda reading: reading.resting_heart_rate_bpm,
}

_WELLNESS_METRICS: dict[ReadinessMetric, Callable[[WellnessCheckIn], float | None]] = {
    ReadinessMetric.PERCEIVED_RECOVERY: lambda checkin: checkin.perceived_recovery,
    ReadinessMetric.ENERGY: lambda checkin: checkin.energy,
    ReadinessMetric.SORENESS: lambda checkin: checkin.soreness,
}


def as_utc(moment: datetime) -> datetime:
    """Naive timestamps are read as UTC.

    Device exports routinely arrive without a timezone, and mixing one naive
    record into an otherwise-aware history would otherwise raise a ``TypeError``
    from a comparison deep inside the baseline maths rather than at ingestion.

    Public because ``training_memory`` walks the same kind of dated history and
    must make the same choice. Two copies of this would be two chances to
    diverge, and the failure would be a crash on real data rather than a test
    failure."""
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=timezone.utc)


def _freshest(records: Sequence[RecordT], moment: datetime) -> RecordT | None:
    """The newest record at or before ``moment``, if it is recent enough to
    describe it.

    Deliberately not ``user.latest_before``: that helper compares
    ``recorded_at`` values directly, which raises on a history mixing naive and
    aware timestamps, and it has no notion of staleness."""
    eligible = [record for record in records if as_utc(record.recorded_at) <= moment]
    if not eligible:
        return None
    latest = max(eligible, key=lambda record: as_utc(record.recorded_at))
    if moment - as_utc(latest.recorded_at) > timedelta(hours=MAX_READING_AGE_HOURS):
        return None
    return latest


def _compare_channel(
    records: Sequence[RecordT],
    accessors: dict[ReadinessMetric, Callable[[RecordT], float | None]],
    moment: datetime,
    window_start: datetime,
) -> list[BaselineComparison]:
    latest = _freshest(records, moment)
    if latest is None:
        return []
    # The newest record is excluded from its own baseline: leaving it in pulls
    # the mean toward the very value being tested and shrinks the deviation it
    # is supposed to stand out from.
    window = [
        record
        for record in records
        if record is not latest and window_start <= as_utc(record.recorded_at) <= moment
    ]
    comparisons = []
    for metric, accessor in accessors.items():
        comparison = _compare(metric, accessor(latest), [accessor(r) for r in window])
        if comparison is not None:
            comparisons.append(comparison)
    return comparisons


def _compare(
    metric: ReadinessMetric, latest: float | None, window: list[float | None]
) -> BaselineComparison | None:
    """``None`` whenever the comparison cannot be made honestly.

    A metric the device did not record, or one with too thin a baseline, is
    absent from the evidence rather than scored as normal -- the difference
    between the two is exactly what ``UNKNOWN`` exists to preserve."""
    if latest is None:
        return None
    samples = [value for value in window if value is not None]
    if len(samples) < MIN_BASELINE_READINGS:
        return None
    baseline_sd = statistics.stdev(samples)
    if baseline_sd <= 0.0:
        # A perfectly flat baseline makes every deviation infinite. Real
        # physiology does not do this; synthetic or stuck-sensor data does.
        return None
    baseline_mean = statistics.fmean(samples)
    return BaselineComparison(
        metric=metric,
        latest=float(latest),
        baseline_mean=baseline_mean,
        baseline_sd=baseline_sd,
        sample_size=len(samples),
        z_score=(latest - baseline_mean) / baseline_sd,
    )


def _report_flags(
    wellness: Sequence[WellnessCheckIn], moment: datetime
) -> frozenset[ReadinessFlag]:
    latest = _freshest(wellness, moment)
    if latest is None:
        return frozenset()
    flags = set()
    if latest.illness_reported:
        flags.add(ReadinessFlag.ILLNESS_REPORTED)
    if latest.injury_flare_reported:
        flags.add(ReadinessFlag.INJURY_FLARE_REPORTED)
    return frozenset(flags)


def _resolve_state(
    comparisons: Sequence[BaselineComparison], flags: frozenset[ReadinessFlag]
) -> ReadinessState:
    """Count how many independent signals fired.

    A flag short-circuits: illness needs no baseline and no corroboration. Two
    corroborating baseline signals are treated as strongly as one flag, because
    a single metric drifting is common and two agreeing is not."""
    if flags:
        return ReadinessState.STRONGLY_SUPPRESSED
    if not comparisons:
        return ReadinessState.UNKNOWN
    suppressed = sum(1 for comparison in comparisons if comparison.indicates_suppression)
    if suppressed >= 2:
        return ReadinessState.STRONGLY_SUPPRESSED
    if suppressed == 1:
        return ReadinessState.SUPPRESSED
    return ReadinessState.NORMAL

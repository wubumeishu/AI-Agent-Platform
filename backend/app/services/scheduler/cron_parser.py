"""Cron expression parser (5-field and 6-field-with-seconds variants).

Self-contained, pure-Python implementation - no external dependency
(croniter / APScheduler are intentionally NOT introduced for the V1
single-node version; keeps next-fire computation trivially testable and
sub-second accurate).

Supported per field (minute hour day-of-month month day-of-week [+seconds]):
    *          wildcard
    N          literal value
    A-B        inclusive range
    N/S        range with step (*/15, 10-40/5)
    a,b,c      comma-separated list of any of the above

Conventions (standard cron):
    - day-of-week: 0-7 with both 0 and 7 meaning Sunday.
    - DOM/DOW interaction: when BOTH are restricted (not *), a datetime
      matches when EITHER matches (Vixie-cron OR semantics). When exactly
      one is restricted, it must match (implicit AND).

All matching is evaluated on **wall-clock components in a chosen timezone**;
the caller converts the result to UTC for storage. Accuracy target: the
engine tick (<250ms) keeps fire error well under 1 second.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import FrozenSet, Optional

__all__ = [
    "CronSpec",
    "CronParseError",
    "parse_cron",
    "compute_next_cron_time",
]


class CronParseError(ValueError):
    """Raised when a cron expression cannot be parsed / is invalid."""


_SECONDS = (0, 59)
_MINUTE = (0, 59)
_HOUR = (0, 23)
_DOM = (1, 31)
_MONTH = (1, 12)
_DOW = (0, 7)  # 0=Sun .. 6=Sat, 7=Sun (cron convention)


@dataclass(frozen=True)
class CronSpec:
    """Parsed, frozen cron specification (sets of allowed wall-clock values)."""

    minutes: FrozenSet[int]
    hours: FrozenSet[int]
    days_of_month: FrozenSet[int]
    months: FrozenSet[int]
    days_of_week: FrozenSet[int]
    seconds: Optional[FrozenSet[int]]  # None -> seconds always 0
    dom_restricted: bool
    dow_restricted: bool
    expression: str
    has_seconds: bool

    def matches(self, moment: datetime) -> bool:
        """Whether a wall-clock datetime matches this spec.

        ``moment`` may be naive or aware; only its local wall-clock
        components are consulted.
        """
        if moment.month not in self.months:
            return False
        if moment.minute not in self.minutes or moment.hour not in self.hours:
            return False
        if self.seconds is not None and moment.second not in self.seconds:
            return False
        # Python: Monday=0..Sunday=6 -> cron Sunday=0..Saturday=6 (+7=Sunday)
        dow = (moment.weekday() + 1) % 7
        dom_ok = moment.day in self.days_of_month
        dow_ok = dow in self.days_of_week
        if self.dom_restricted and self.dow_restricted:
            return dom_ok or dow_ok
        if self.dom_restricted:
            return dom_ok
        if self.dow_restricted:
            return dow_ok
        return True


def _parse_field(token: str, lo: int, hi: int, what: str) -> set:
    """Parse one cron field token into a set of ints. Raises CronParseError."""
    values = set()
    for part in token.split(","):
        part = part.strip()
        if not part:
            raise CronParseError(f"{what}: empty list item in {token!r}")
        step = 1
        if "/" in part:
            range_part, step_str = part.split("/", 1)
            if not step_str.isdigit() or int(step_str) == 0:
                raise CronParseError(f"{what}: invalid step in {part!r}")
            step = int(step_str)
        else:
            range_part = part
        if range_part == "*":
            start, end = lo, hi
        elif "-" in range_part:
            a, b = range_part.split("-", 1)
            if not (a.isdigit() and b.isdigit()):
                raise CronParseError(f"{what}: invalid range {range_part!r}")
            start, end = int(a), int(b)
            if start > end:
                raise CronParseError(f"{what}: reversed range {range_part!r}")
        else:
            if not range_part.isdigit():
                raise CronParseError(f"{what}: invalid value {range_part!r}")
            start = end = int(range_part)
            if step != 1:
                # "N/step": start at N, step to the field maximum (cron-extended)
                end = hi
        if start < lo or end > hi:
            raise CronParseError(
                f"{what}: value {start}-{end} out of allowed range {lo}-{hi}"
            )
        values.update(range(start, end + 1, step))
    if not values:
        raise CronParseError(f"{what}: no values in {token!r}")
    return values


def parse_cron(expression: str) -> CronSpec:
    """Parse a 5-field (or 6-field with seconds) cron expression.

    Fields: [second] minute hour day-of-month month day-of-week.
    Raises CronParseError on invalid input.
    """
    if not isinstance(expression, str):
        raise CronParseError("cron expression must be a string")
    fields = expression.split()
    if len(fields) == 5:
        f_sec, f_min, f_hour, f_dom, f_month, f_dow = ("*", *fields)
        has_seconds = False
    elif len(fields) == 6:
        f_sec, f_min, f_hour, f_dom, f_month, f_dow = fields
        has_seconds = True
    else:
        raise CronParseError(
            f"cron expression must have 5 or 6 fields, got {len(fields)}: {expression!r}"
        )
    minutes = _parse_field(f_min, *_MINUTE, what="minute")
    hours = _parse_field(f_hour, *_HOUR, what="hour")
    doms = _parse_field(f_dom, *_DOM, what="day-of-month")
    months = _parse_field(f_month, *_MONTH, what="month")
    dows = _parse_field(f_dow, *_DOW, what="day-of-week")
    if has_seconds:
        secs = _parse_field(f_sec, *_SECONDS, what="second")
        seconds = frozenset(secs)
    else:
        seconds = None
    # Map dow 7 -> 0 (both mean Sunday)
    if 7 in dows:
        dows.discard(7)
        dows.add(0)
    return CronSpec(
        minutes=frozenset(minutes),
        hours=frozenset(hours),
        days_of_month=frozenset(doms),
        months=frozenset(months),
        days_of_week=frozenset(dows),
        seconds=seconds,
        dom_restricted=(f_dom != "*"),
        dow_restricted=(f_dow != "*"),
        expression=" ".join(fields),
        has_seconds=has_seconds,
    )


def compute_next_cron_time(
    spec: CronSpec, after: datetime, max_search_days: int = 366 * 2
) -> Optional[datetime]:
    """Earliest matching instant strictly after ``after`` (same tz-awareness).

    Day-level pre-filter makes even a once-a-year spec fast; bounded to
    ~2 years so impossible specs (e.g. 31 Feb) terminate with None.
    ``after`` must be the same tz-awareness the spec is meant to run in
    (the caller handles conversion to/from UTC).

    5-field (minute) specs iterate whole-minute candidates pinned to
    second=0 - unchanged and exact. 6-field (seconds) specs iterate the
    allowed (hour, minute, second) sets in ascending order within each
    matching day, so sub-minute resolution is preserved instead of
    collapsing to ``min(spec.seconds)``.
    """
    day = (after + timedelta(seconds=1)).replace(microsecond=0)
    for _ in range(max_search_days):
        # Day-level pre-filter: does this (month, day) admit any match?
        if day.month in spec.months and _day_may_match(spec, day):
            base_day = day.replace(hour=0, minute=0, second=0, microsecond=0)
            if spec.seconds is not None:
                # Seconds-cron: iterate allowed (hour, minute, second) in
                # ascending order. Candidates are strictly ascending in time
                # within the day; the first one strictly after ``after`` wins.
                for hour in sorted(spec.hours):
                    for minute in sorted(spec.minutes):
                        for second in sorted(spec.seconds):
                            cand = base_day.replace(
                                hour=hour, minute=minute, second=second
                            )
                            if cand > after and spec.matches(cand):
                                return cand
            else:
                # Minute-cron: whole-minute candidates pinned to second=0.
                d0 = base_day
                for _m in range(1440):
                    cand = d0 + timedelta(minutes=_m)
                    if cand > after and spec.matches(cand):
                        return cand
        day = (day + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return None


def _day_may_match(spec: CronSpec, day: datetime) -> bool:
    """Fast day filter: DOM/DOW OR-semantics (seconds/minute already excluded)."""
    dow = (day.weekday() + 1) % 7
    dom_ok = day.day in spec.days_of_month
    dow_ok = dow in spec.days_of_week
    if spec.dom_restricted and spec.dow_restricted:
        return dom_ok or dow_ok
    if spec.dom_restricted:
        return dom_ok
    if spec.dow_restricted:
        return dow_ok
    return True


def next_cron_time(expression: str, after: datetime, max_search_days: int = 366 * 2) -> Optional[datetime]:
    """Convenience wrapper: parse + compute in one call. Raises CronParseError."""
    return compute_next_cron_time(parse_cron(expression), after, max_search_days)

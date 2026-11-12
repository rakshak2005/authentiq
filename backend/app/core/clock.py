"""Reader-aware date helpers.

Every timestamp in AUTHENTIQ is stored and transported in UTC. That is the
right contract for an audit trail, but a *day* bucket, a *month* bucket, or a
printed certificate has to be rendered in the timezone of the person reading
it. Otherwise a record registered at 00:35 in India is filed under the
previous day and the workspace reads as if it belongs to yesterday.

The reader's timezone travels as a plain UTC offset in minutes, so the API
stays stateless and the browser stays the single source of truth.
"""

from datetime import date, datetime, timedelta, timezone

MAX_OFFSET_MINUTES = 14 * 60


def clamp_offset(tz_offset_minutes: int | None) -> int:
    try:
        value = int(tz_offset_minutes or 0)
    except (TypeError, ValueError):
        return 0
    return max(-MAX_OFFSET_MINUTES, min(MAX_OFFSET_MINUTES, value))


def offset_delta(tz_offset_minutes: int | None) -> timedelta:
    return timedelta(minutes=clamp_offset(tz_offset_minutes))


def offset_label(tz_offset_minutes: int | None = 0) -> str:
    minutes = clamp_offset(tz_offset_minutes)
    if minutes == 0:
        return "UTC"
    sign = "+" if minutes > 0 else "-"
    hours, remainder = divmod(abs(minutes), 60)
    return f"UTC{sign}{hours:02d}:{remainder:02d}"


def to_reader_time(value: datetime | None, tz_offset_minutes: int = 0) -> datetime | None:
    """Move a UTC timestamp into the reader's timezone."""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc) + offset_delta(tz_offset_minutes)


def reader_date(value: datetime | None, tz_offset_minutes: int = 0) -> date | None:
    moment = to_reader_time(value, tz_offset_minutes)
    return moment.date() if moment else None


def reader_now(tz_offset_minutes: int = 0) -> datetime:
    return datetime.now(timezone.utc) + offset_delta(tz_offset_minutes)


def reader_stamp(
    value: datetime | None,
    tz_offset_minutes: int = 0,
    pattern: str = "%Y-%m-%d %H:%M:%S",
) -> str:
    moment = to_reader_time(value, tz_offset_minutes)
    if moment is None:
        return "Not available"
    return f"{moment.strftime(pattern)} {offset_label(tz_offset_minutes)}"

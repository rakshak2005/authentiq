"""The reader's timezone decides which day a record belongs to.

A record registered at 00:35 in India is stored as 19:05 UTC on the previous
day. If the API groups it by the UTC day while the interface renders local
days, the activity lands on yesterday's cell and the workspace reads as stale.
"""

from datetime import datetime, timedelta, timezone

from app.core.clock import offset_label, reader_date, reader_now, reader_stamp, to_reader_time
from app.core.database import SessionLocal
from app.models import Registration
from sqlalchemy import select
from tests.conftest import _freeze_clock
from tests.helpers import create_registration

INDIA = 330  # UTC+05:30


def test_reader_day_rolls_over_at_local_midnight():
    # 19:05 UTC is 00:35 the next day in India.
    moment = datetime(2026, 11, 11, 19, 5, 31, tzinfo=timezone.utc)

    assert reader_date(moment, 0).isoformat() == "2026-11-11"
    assert reader_date(moment, INDIA).isoformat() == "2026-11-12"
    assert reader_date(moment, -INDIA).isoformat() == "2026-11-11"


def test_reader_stamp_labels_the_offset():
    moment = datetime(2026, 11, 11, 19, 5, 31, tzinfo=timezone.utc)

    assert reader_stamp(moment, 0) == "2026-11-11 19:05:31 UTC"
    assert reader_stamp(moment, INDIA) == "2026-11-12 00:35:31 UTC+05:30"
    assert offset_label(INDIA) == "UTC+05:30"
    assert offset_label(0) == "UTC"


def test_reader_now_tracks_the_offset():
    difference = reader_now(INDIA) - reader_now(0)

    assert abs(difference - timedelta(minutes=INDIA)) < timedelta(seconds=1)


def test_naive_timestamps_are_read_as_utc():
    naive = datetime(2026, 11, 11, 19, 5, 31)

    assert to_reader_time(naive, INDIA).isoformat() == "2026-11-12T00:35:31+00:00"


def _set_registered_at(client, headers, title, fixed_at):
    """Create a registration then override its registered_at to a fixed time."""
    create_registration(client, headers, title=title)
    with SessionLocal() as db:
        reg = db.execute(select(Registration).where(Registration.title == title)).scalar_one()
        reg.registered_at = fixed_at
        db.commit()


def test_dashboard_heatmap_uses_the_reader_day(client, user_factory, dashboard_clock):
    creator = user_factory(display_name="Ada Lovelace")
    _set_registered_at(
        client,
        creator["headers"],
        "Engine",
        datetime(2026, 11, 11, 10, 0, 0, tzinfo=timezone.utc),
    )

    utc_view = client.get("/api/dashboard/summary", headers=creator["headers"]).json()
    reader_view = client.get(
        "/api/dashboard/summary?tz_offset=330", headers=creator["headers"]
    ).json()

    utc_cells = {cell["date"]: cell["total"] for cell in utc_view["charts"]["activity_heatmap"]}
    reader_cells = {cell["date"]: cell["total"] for cell in reader_view["charts"]["activity_heatmap"]}

    assert sum(reader_cells.values()) == sum(utc_cells.values()) == 1
    # The same event, filed under the reader's calendar day.
    assert utc_view["charts"]["activity_heatmap"][-1]["date"] == reader_view["charts"]["activity_heatmap"][-1]["date"]
    assert reader_cells[reader_view["charts"]["activity_heatmap"][-1]["date"]] == 1


def test_dashboard_rejects_an_out_of_range_offset(client, user_factory):
    creator = user_factory(display_name="Ada Lovelace")

    response = client.get("/api/dashboard/summary?tz_offset=9999", headers=creator["headers"])

    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Regression tests: UTC / reader-local date boundaries at midnight
# ---------------------------------------------------------------------------


def test_reader_date_at_india_midnight_boundary(fixed_clock):
    """18:30 UTC is exactly midnight in India (UTC+05:30).

    A record at 18:30 UTC belongs to Nov 11 in UTC but Nov 12 in India.
    """
    moment = datetime(2026, 11, 11, 18, 30, 0, tzinfo=timezone.utc)

    assert reader_date(moment, 0).isoformat() == "2026-11-11"
    assert reader_date(moment, INDIA).isoformat() == "2026-11-12"


def test_reader_date_just_before_india_midnight(fixed_clock):
    """18:29 UTC is still Nov 11 in India (one minute before midnight)."""
    moment = datetime(2026, 11, 11, 18, 29, 0, tzinfo=timezone.utc)

    assert reader_date(moment, 0).isoformat() == "2026-11-11"
    assert reader_date(moment, INDIA).isoformat() == "2026-11-11"


def test_reader_date_just_after_india_midnight(fixed_clock):
    """18:31 UTC is already Nov 12 in India (one minute after midnight)."""
    moment = datetime(2026, 11, 11, 18, 31, 0, tzinfo=timezone.utc)

    assert reader_date(moment, 0).isoformat() == "2026-11-11"
    assert reader_date(moment, INDIA).isoformat() == "2026-11-12"


def test_dashboard_heatmap_files_event_under_reader_day_at_midnight(
    client, user_factory, monkeypatch
):
    """An event at 18:30 UTC (India midnight) appears on Nov 12 in the reader view.

    The UTC view files it under Nov 11; the reader view (UTC+05:30) files it
    under Nov 12. Both views agree on the total count.
    """
    import datetime as dt_module
    from datetime import datetime, timezone

    # Freeze reader_now at Nov 12 01:00 UTC (= Nov 12 06:30 reader time),
    # which is after both the registration's UTC time (Nov 11 18:30) and
    # its reader-time (Nov 12 00:00), so both dates fall inside the heatmap.
    fixed = datetime(2026, 11, 12, 1, 0, 0, tzinfo=timezone.utc)

    class FrozenDateTime(dt_module.datetime):
        @classmethod
        def now(cls, tz=None):
            result = fixed
            if tz is not None:
                result = result.astimezone(tz)
            return result

    monkeypatch.setattr("app.core.clock.datetime", FrozenDateTime)

    _set_registered_at(
        client,
        creator := user_factory(display_name="Boundary Creator")["headers"],
        "Midnight Event",
        datetime(2026, 11, 11, 18, 30, 0, tzinfo=timezone.utc),
    )

    utc_view = client.get("/api/dashboard/summary", headers=creator).json()
    reader_view = client.get(
        "/api/dashboard/summary?tz_offset=330", headers=creator
    ).json()

    utc_cells = {cell["date"]: cell["total"] for cell in utc_view["charts"]["activity_heatmap"]}
    reader_cells = {cell["date"]: cell["total"] for cell in reader_view["charts"]["activity_heatmap"]}

    assert sum(reader_cells.values()) == sum(utc_cells.values()) == 1
    # Same event, different calendar day in each timezone.
    assert utc_cells["2026-11-11"] == 1
    assert reader_cells["2026-11-12"] == 1
    assert utc_cells.get("2026-11-12", 0) == 0
    assert reader_cells.get("2026-11-11", 0) == 0

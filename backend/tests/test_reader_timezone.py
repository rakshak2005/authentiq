"""The reader's timezone decides which day a record belongs to.

A record registered at 00:35 in India is stored as 19:05 UTC on the previous
day. If the API groups it by the UTC day while the interface renders local
days, the activity lands on yesterday's cell and the workspace reads as stale.
"""

from datetime import datetime, timedelta, timezone

from app.core.clock import offset_label, reader_date, reader_now, reader_stamp, to_reader_time
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


def test_dashboard_heatmap_uses_the_reader_day(client, user_factory):
    creator = user_factory(display_name="Ada Lovelace")
    create_registration(client, creator["headers"], title="Engine")

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

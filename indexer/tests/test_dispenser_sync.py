"""Unit tests for the open dispenser sync (no database or network)."""

from decimal import Decimal
from unittest.mock import MagicMock

from index_core.dispenser_sync import (
    fetch_open_dispensers,
    plan_updates,
    summarize_listings,
    sync_open_dispensers,
)


def dispenser(asset, rate, status=0, remaining=1):
    return {"asset": asset, "satoshirate": rate, "status": status, "give_remaining": remaining}


def pages(*results, total=None):
    """A fake fetch_xcp serving the given result lists as cursor pages."""
    count = total if total is not None else sum(len(r) for r in results)
    responses = []
    for index, result in enumerate(results):
        responses.append(
            {
                "result": result,
                "result_count": count,
                "next_cursor": f"c{index + 1}" if index + 1 < len(results) else None,
            }
        )
    calls = []

    def fetch(endpoint, params):
        calls.append((endpoint, dict(params)))
        return responses[len(calls) - 1]

    fetch.calls = calls
    return fetch


def test_fetch_follows_every_cursor_page():
    fetch = pages([dispenser("A1", 5)], [dispenser("A2", 6)])
    assert [d["asset"] for d in fetch_open_dispensers(fetch)] == ["A1", "A2"]
    assert fetch.calls[0] == ("/dispensers", {"status": 0, "limit": 1000})
    assert fetch.calls[1][1]["cursor"] == "c1"


def test_fetch_refuses_a_missing_page():
    responses = iter([{"result": [dispenser("A1", 5)], "result_count": 2, "next_cursor": "c1"}, None])
    assert fetch_open_dispensers(lambda endpoint, params: next(responses)) is None


def test_fetch_refuses_a_short_list():
    assert fetch_open_dispensers(pages([dispenser("A1", 5)], total=3)) is None


def test_summary_counts_open_dispensers_and_takes_the_lowest_rate():
    listings = summarize_listings(
        [
            dispenser("A1", 500_000),
            dispenser("A1", 369_000),
            dispenser("A1", 100, status=10),
            dispenser("A1", 100, remaining=0),
            dispenser("A2", 0),
        ]
    )
    assert listings["A1"] == (2, Decimal("0.00369"))
    assert listings["A2"] == (1, None)


def test_plan_lists_new_dispensers_and_delists_closed_ones():
    rows = [
        ("NEW", 0, None, None),
        ("SAME", 1, Decimal("0.00369000"), "dispenser"),
        ("CLOSED", 1, Decimal("0.001"), "dispenser"),
        ("OTHER_SOURCE", 0, Decimal("0.2"), "openstamp"),
    ]
    listings = {"NEW": (1, Decimal("0.0005")), "SAME": (1, Decimal("0.00369"))}
    assert plan_updates(rows, listings) == [
        (1, Decimal("0.0005"), "dispenser", "NEW"),
        (0, None, None, "CLOSED"),
    ]


def test_sync_updates_only_changed_rows_without_touching_last_updated():
    db = MagicMock()
    cursor = db.cursor.return_value.__enter__.return_value
    cursor.fetchall.side_effect = [
        [("CLOSED", 1, Decimal("0.001"), "dispenser")],
        [("NEW", 0, None, None)],
    ]
    fetch = pages([dispenser("NEW", 50_000), dispenser("XCP", 7_880)])

    assert sync_open_dispensers(db, fetch) == 2

    sql, params = cursor.executemany.call_args.args
    assert "last_updated = last_updated" in sql
    assert params == [
        (0, None, None, 0, "CLOSED"),
        (1, Decimal("0.0005"), "dispenser", 1, "NEW"),
    ]
    db.commit.assert_called_once()


def test_sync_changes_nothing_when_the_scan_is_incomplete():
    db = MagicMock()
    assert sync_open_dispensers(db, pages([dispenser("A1", 5)], total=2)) is None
    db.cursor.assert_not_called()
    db.commit.assert_not_called()

"""
Keep the listing columns of stamp_market_data in step with Counterparty.

The activity-based market data job refreshes a stamp that has never sold only
once every 7 days, and nothing else writes open_dispensers_count. A dispenser
opened on such a stamp therefore stayed out of every "listed" view (the
Stamps API listings filter, collection listed counts, StampDEX rankings) for
up to a week, and a closed one stayed listed just as long.

This job reads every open dispenser in one paged scan (27 requests for about
26,000 dispensers on mainnet) and corrects only the listing columns of the
stamps whose listings changed. The scan is all or nothing: a partial list
would look like closed dispensers and wipe real listings, so an incomplete
scan changes nothing.
"""

import logging
from decimal import Decimal
from typing import Callable, Dict, Iterable, List, Optional, Tuple

from index_core.fetch_utils import fetch_xcp

logger = logging.getLogger(__name__)

PAGE_LIMIT = 1000
# Far above the ~27 pages mainnet needs; a cursor loop past this is a bug.
MAX_PAGES = 500
LOOKUP_CHUNK = 1000
SATS_PER_BTC = Decimal(100_000_000)

# (open dispenser count, floor price in BTC or None)
Listing = Tuple[int, Optional[Decimal]]


def fetch_open_dispensers(fetch: Callable = fetch_xcp) -> Optional[List[Dict]]:
    """Every open dispenser, or None unless the whole list arrived."""
    dispensers: List[Dict] = []
    cursor = None
    expected = None
    for _ in range(MAX_PAGES):
        params = {"status": 0, "limit": PAGE_LIMIT}
        if cursor:
            params["cursor"] = cursor
        response = fetch("/dispensers", params)
        if not isinstance(response, dict) or not isinstance(response.get("result"), list):
            logger.warning("Open dispenser scan aborted: a page did not arrive")
            return None
        if expected is None:
            expected = response.get("result_count")
        dispensers.extend(response["result"])
        cursor = response.get("next_cursor")
        if not cursor or not response["result"]:
            break
    else:
        logger.warning("Open dispenser scan aborted: cursor did not end")
        return None

    if isinstance(expected, int) and len(dispensers) < expected:
        logger.warning(f"Open dispenser scan aborted: {len(dispensers)} of {expected} dispensers arrived")
        return None
    return dispensers


def summarize_listings(dispensers: Iterable[Dict]) -> Dict[str, Listing]:
    """Open dispenser count and floor per asset, priced like StampWorker."""
    listings: Dict[str, Listing] = {}
    for dispenser in dispensers:
        asset = dispenser.get("asset")
        if not asset or dispenser.get("status") != 0:
            continue
        if (dispenser.get("give_remaining") or 0) <= 0:
            continue
        count, floor = listings.get(asset, (0, None))
        rate = dispenser.get("satoshirate") or 0
        if rate > 0:
            price = Decimal(rate) / SATS_PER_BTC
            floor = price if floor is None else min(floor, price)
        listings[asset] = (count + 1, floor)
    return listings


def _same_price(left, right) -> bool:
    if left is None or right is None:
        return left is None and right is None
    return Decimal(str(left)) == Decimal(str(right))


def plan_updates(rows: Iterable[Tuple], listings: Dict[str, Listing]) -> List[Tuple]:
    """
    Changes for the given stamp_market_data rows (cpid, open count, floor,
    price source). A stamp with open dispensers takes its floor from them; a
    stamp whose last dispenser closed loses a dispenser-sourced floor, while a
    floor from another price source is left alone.
    """
    updates = []
    for cpid, current_count, current_floor, price_source in rows:
        count, floor = listings.get(cpid, (0, None))
        if count > 0:
            new_floor, new_source = floor, "dispenser"
        elif price_source == "dispenser":
            new_floor, new_source = None, None
        else:
            new_floor, new_source = current_floor, price_source
        if (current_count or 0) == count and _same_price(current_floor, new_floor) and price_source == new_source:
            continue
        updates.append((count, new_floor, new_source, cpid))
    return updates


def sync_open_dispensers(db, fetch: Callable = fetch_xcp) -> Optional[int]:
    """Apply the current open dispensers to stamp_market_data; rows changed."""
    dispensers = fetch_open_dispensers(fetch)
    if dispensers is None:
        return None
    listings = summarize_listings(dispensers)

    rows: Dict[str, Tuple] = {}
    with db.cursor() as cursor:
        cursor.execute(
            "SELECT cpid, open_dispensers_count, floor_price_btc, price_source "
            "FROM stamp_market_data WHERE open_dispensers_count > 0"
        )
        for row in cursor.fetchall():
            rows[row[0]] = row
        pending = [cpid for cpid in listings if cpid not in rows]
        for start in range(0, len(pending), LOOKUP_CHUNK):
            chunk = pending[start : start + LOOKUP_CHUNK]
            placeholders = ",".join(["%s"] * len(chunk))
            cursor.execute(
                "SELECT cpid, open_dispensers_count, floor_price_btc, price_source "
                f"FROM stamp_market_data WHERE cpid IN ({placeholders})",
                chunk,
            )
            for row in cursor.fetchall():
                rows[row[0]] = row

        updates = plan_updates(rows.values(), listings)
        if updates:
            # last_updated = last_updated keeps ON UPDATE CURRENT_TIMESTAMP from
            # firing: that column schedules the full market data refresh, which
            # these listing-only corrections must not postpone.
            cursor.executemany(
                "UPDATE stamp_market_data SET open_dispensers_count = %s, "
                "floor_price_btc = %s, price_source = %s, "
                "activity_level = CASE WHEN %s > 0 AND activity_level = 'COLD' "
                "THEN 'DORMANT' ELSE activity_level END, "
                "last_updated = last_updated WHERE cpid = %s",
                [(count, floor, source, count, cpid) for count, floor, source, cpid in updates],
            )
    db.commit()
    logger.info(
        f"Open dispenser sync: {len(dispensers)} dispensers, {len(listings)} listed assets, "
        f"{len(updates)} stamp rows corrected"
    )
    return len(updates)

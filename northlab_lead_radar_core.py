from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from typing import Any

import nc_v6_broad_radar as radar


VERSION = "1.2-recall-first-wide-net"


def is_actionable_buyer(lead: dict[str, Any]) -> bool:
    """Final production gate: only direct North Cyprus property buyers."""
    if str(lead.get("market") or "") != "north_cyprus":
        return False

    if str(lead.get("intent_type") or "").upper() != "BUYER":
        return False

    if str(lead.get("lead_class") or "") not in {"HOT BUYER", "WARM BUYER"}:
        return False

    text = str(lead.get("message") or lead.get("text") or "")
    if radar.RENT_DEMAND_RE.search(text):
        return False
    if radar._hard_reject(text, str(lead.get("author") or "")):
        return False
    if not radar.PROPERTY_RE.search(text):
        return False

    return True


def _mark_notified(db, lead: dict[str, Any], when: datetime) -> None:
    lead_id = str(lead.get("lead_id") or "")
    if not lead_id:
        return
    db.collection(radar.core.COLLECTION).document(lead_id).set(
        {
            "v6_notified_at": when.isoformat(),
            "core_notified_at": when.isoformat(),
            "core_version": VERSION,
        },
        merge=True,
    )


async def scan_once() -> dict[str, Any]:
    # Hard production policy. The old multi-source radar remains frozen/manual;
    # this core only searches public Telegram surfaces for direct buyers.
    os.environ["RADAR_SALES_ONLY"] = "1"
    os.environ.setdefault("RADAR_GLOBAL_TELEGRAM_DAYS", "30")
    os.environ.setdefault("RADAR_PUBLIC_PEER_SCAN_LIMIT", "180")
    os.environ.setdefault("RADAR_LEARNED_TELEGRAM_QUERIES", "40")
    os.environ.setdefault("RADAR_SOURCE_EXPANSION_SEEDS", "16")
    os.environ.setdefault("RADAR_SOURCE_EXPANSION_CANDIDATES", "48")

    started = datetime.now(timezone.utc)
    db = radar.core.db()

    result = await radar.broad_telegram_scan(db, started)
    raw = list(result.get("new_leads") or [])
    buyers = [lead for lead in raw if is_actionable_buyer(lead)]

    notified = 0
    for lead in buyers:
        if radar.notify_lead(lead, "NEW"):
            _mark_notified(db, lead, started)
            notified += 1

    summary = {
        "version": VERSION,
        "status": result.get("status", "unknown"),
        "groups": result.get("groups", 0),
        "messages": result.get("messages", 0),
        "raw_new": len(raw),
        "buyers": len(buyers),
        "notified": notified,
        "group_discovery_joined": result.get("group_discovery_joined", 0),
        "group_discovery_joined_samples": result.get("group_discovery_joined_samples", []),
        "group_discovery_found": result.get("group_discovery_found", 0),
        "errors": result.get("errors", 0),
        "joined_groups_total": result.get("candidate_first_total_groups", 0),
        "joined_groups_count": radar.DEBUG.get("joined_groups_count", 0),
        "joined_channels_count": radar.DEBUG.get("joined_channels_count", 0),
        "joined_hours": radar.DEBUG.get("joined_scan_hours", 0),
        "joined_primary_signal_pass": radar.DEBUG.get("signal_pass", 0),
        "joined_rejections": dict(radar.DEBUG.get("reject_reasons") or {}),
        "buyer_reject_public_links": dict(radar.DEBUG.get("buyer_reject_public_links") or {}),
        "joined_extra_messages": radar.DEBUG.get("strict_extra_messages_scanned", 0),
        "global_search_raw": radar.DEBUG.get("global_search_raw", 0),
        "global_search_signal_pass": radar.DEBUG.get("global_search_signal_pass", 0),
        "global_search_accepted": radar.DEBUG.get("global_search_accepted", 0),
        "global_search_rejections": dict(radar.DEBUG.get("global_search_reject_reasons") or {}),
        "review_qualified": radar.DEBUG.get("review_qualified", 0),
        "started_at": started.isoformat(),
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }

    # Logs only. No zero-result/debug Telegram messages.
    print("PRIME_KIBRIS_BUYER_RADAR", summary)
    return summary


def main() -> None:
    asyncio.run(scan_once())


if __name__ == "__main__":
    main()

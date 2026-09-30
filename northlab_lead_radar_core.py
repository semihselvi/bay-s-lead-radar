from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from typing import Any

import nc_v6_broad_radar as radar


VERSION = "1.1-property-object-firewall"


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
    os.environ.setdefault("RADAR_GLOBAL_TELEGRAM_DAYS", "7")
    os.environ.setdefault("RADAR_PUBLIC_PEER_SCAN_LIMIT", "90")
    os.environ.setdefault("RADAR_LEARNED_TELEGRAM_QUERIES", "20")
    os.environ.setdefault("RADAR_SOURCE_EXPANSION_SEEDS", "8")
    os.environ.setdefault("RADAR_SOURCE_EXPANSION_CANDIDATES", "24")

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
        "errors": result.get("errors", 0),
        "started_at": started.isoformat(),
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }

    # Logs only. No zero-result/debug Telegram messages.
    print("NORTHLAB_LEAD_RADAR_CORE", summary)
    return summary


def main() -> None:
    asyncio.run(scan_once())


if __name__ == "__main__":
    main()

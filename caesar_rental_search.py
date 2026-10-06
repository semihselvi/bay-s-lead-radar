"""Read-only search of Caesar Resort rental *offers* in joined Telegram groups.

Does not write to Firestore or notify the buyer radar. Reports only verified
message links from the Telegram account already used by Prime Buyer Radar.
"""
import asyncio
import json
import os
import re
from datetime import datetime, timedelta, timezone
from telethon import TelegramClient
from telethon.tl.types import PeerChannel

PROJECT = re.compile(r"(?:caesar|cesar|sezar|цезар|сизар|сезар)\s*(?:resort|ресорт|резорт|resort\s*(?:&|and)\s*spa|spa|спа)", re.I)
ONE_BED = re.compile(r"(?<!\d)1\s*[+＋]\s*1(?!\d)|one[ -]?bed(?:room)?|однокомнатн\w*|1\s*спальн\w*", re.I)
STUDIO = re.compile(r"st[uü]dyo|studio|студи\w*", re.I)
NICHE = re.compile(r"ниш\w*|nişli|nisli|niche|alcove", re.I)
RENT = re.compile(r"kiral\w*|kiraya|rent(?:al|ed|ing)?|to\s*let|аренд\w*|сда(?:м|ется|ётся|ю|ют|ётся)|сдаётся|сдается|сдача|long[ -]?term", re.I)
SUPPLY = re.compile(r"kiralık|kiraya\s*ver\w*|kiralığa|for\s*rent|for\s*lease|available\s*(?:to\s*rent|for\s*rent)|сда(?:м|ётся|ется|ю|ют)|сдаётся|сдается|сдаю|в\s*аренду|аренда\s*(?:квартир|студи)|rent\s*out", re.I)
DEMAND = re.compile(r"arıyorum|aranıyor|ihtiyacım|kiralamak\s*istiyorum|looking\s*(?:for|to\s*rent)|want\s*to\s*rent|need\s*(?:a|an)\s*(?:apartment|flat|studio)|ищу|сниму|хочу\s*снять|нужн\w*\s*(?:квартир|студи)", re.I)
PRICE = re.compile(r"(?:[£€$]\s*\d[\d\s,.]*|\d[\d\s,.]*\s*(?:gbp|eur|usd|sterlin|pounds?|фунт\w*))", re.I)


def classify(text: str, *, group: str = "") -> str | None:
    """Fail closed on tenant requests, generic adverts and property sales."""
    blob = str(text or "")
    if not RENT.search(blob) or not SUPPLY.search(blob) or DEMAND.search(blob):
        return None
    if not PROJECT.search(blob) and not PROJECT.search(group):
        return None
    if STUDIO.search(blob) and NICHE.search(blob):
        return "niche_studio"
    if ONE_BED.search(blob):
        return "1+1"
    return None


def link_for(entity, msg) -> str:
    username = str(getattr(entity, "username", "") or "").strip()
    if username:
        return f"https://t.me/{username}/{msg.id}"
    # t.me/c IDs work for supergroups and channels; not basic groups.
    if isinstance(getattr(msg, "peer_id", None), PeerChannel):
        channel_id = int(getattr(entity, "id", 0) or 0)
        if channel_id:
            return f"https://t.me/c/{channel_id}/{msg.id}"
    return ""


async def scan():
    session = os.getenv("TELEGRAM_SESSION_PATH", "telegram_radar_session/radar_session.session")
    api_id = int(os.environ["TELEGRAM_API_ID"])
    api_hash = os.environ["TELEGRAM_API_HASH"]
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    stats = {"groups": 0, "messages": 0, "matches": 0, "unlinked": 0, "errors": 0, "offers": []}
    seen = set()
    client = TelegramClient(session, api_id, api_hash)
    try:
        await client.connect()
        if not await client.is_user_authorized():
            raise RuntimeError("Telegram session not authorized")
        async for dialog in client.iter_dialogs():
            if not (dialog.is_group or dialog.is_channel):
                continue
            stats["groups"] += 1
            try:
                async for msg in client.iter_messages(dialog.entity, limit=400):
                    if not msg.date:
                        continue
                    date = msg.date.replace(tzinfo=timezone.utc) if msg.date.tzinfo is None else msg.date
                    if date < cutoff:
                        break
                    stats["messages"] += 1
                    original = str(msg.message or "")
                    kind = classify(original, group=dialog.name or "")
                    if not kind:
                        continue
                    url = link_for(dialog.entity, msg)
                    if not url:
                        stats["unlinked"] += 1
                        continue
                    if url in seen:
                        continue
                    seen.add(url)
                    prices = PRICE.findall(original)
                    stats["offers"].append({
                        "kind": kind, "date": date.isoformat(),
                        "group": dialog.name, "url": url,
                        "price_mentions": prices[:3],
                        "text": original[:1500],
                    })
            except Exception as exc:
                stats["errors"] += 1
                print("CAESAR_RENTAL_GROUP_ERROR", type(exc).__name__, str(exc)[:160])
    finally:
        await client.disconnect()
    stats["offers"].sort(key=lambda x: x["date"], reverse=True)
    stats["matches"] = len(stats["offers"])
    public_links = [
        {"kind": item["kind"], "date": item["date"], "url": item["url"],
         "price_mentions": item["price_mentions"]}
        for item in stats["offers"]
        if re.fullmatch(r"https://t\\.me/[A-Za-z0-9_]+/\\d+", item["url"])
        and not item["url"].startswith("https://t.me/c/")
    ]
    summary = {
        "status": "completed",
        "scanned_at": datetime.now(timezone.utc).isoformat(),
        "groups": stats["groups"], "messages": stats["messages"],
        "matches": stats["matches"],
        "niche_studio": sum(i["kind"] == "niche_studio" for i in stats["offers"]),
        "one_bed": sum(i["kind"] == "1+1" for i in stats["offers"]),
        "unlinked": stats["unlinked"], "errors": stats["errors"],
        "public_offers": public_links[:30],
        "private_or_unpublished_matches": stats["matches"] - len(public_links),
    }
    # Repository is public: never expose private Telegram group messages or members.
    report_path = os.getenv("CAESAR_REPORT_PATH", "").strip()
    if report_path:
        from pathlib import Path
        target = Path(report_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("CAESAR_RENTAL_SUPPLY_SUMMARY", json.dumps(summary, ensure_ascii=False))
    return stats


if __name__ == "__main__":
    asyncio.run(scan())

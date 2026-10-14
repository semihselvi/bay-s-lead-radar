"""Read-only daily comparison of HOT SALE Telegram channel and every Prime Kıbrıs resale page."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from telethon import TelegramClient
from telethon.sessions import StringSession

SITE = "https://primekibris.com/tr/ikinci-el"
CHANNEL = "h0t_real_estate"
STATE_PATH = Path(os.getenv("RESALE_WATCH_STATE", "resale_watch_state.json"))
OUT_PATH = Path(os.getenv("RESALE_WATCH_REPORT", "resale-watch-report/report.json"))
REF = re.compile(r"PK-2E-\d{6}", re.I)
MONEY = re.compile(r"(?:£\s*([\d., ]{4,})|([\d., ]{4,})\s*(?:£|GBP))", re.I)
BEDS = re.compile(r"(?<!\d)([0-5])\s*[+＋]\s*1(?!\d)")
AREA = re.compile(r"(\d{2,4})\s*(?:m²|m2|metrekare|кв\s*м)", re.I)
FLOOR = re.compile(r"(?:\b(\d{1,2})\s*(?:\.?\s*kat(?:ta)?|(?:st|nd|rd|th)\s+floor|этаж(?:е)?)\b)", re.I)
OFFER = re.compile(r"(\d\s*[+＋]\s*1|stüdyo|studio|студи|вилла|villa|townhouse|таунхаус|daire|квартир|penthouse|dubleks|duplex|arsa)", re.I)


def normalized(value):
    s = unicodedata.normalize("NFKD", str(value).lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def gbp(text):
    m = MONEY.search(str(text))
    if not m:
        return None
    raw = (m.group(1) or m.group(2)).strip().replace(" ", "")
    # A single separator followed by three digits is a thousands separator.
    raw = re.sub(r"[.,](?=\d{3}(?:\D|$))", "", raw)
    raw = raw.replace(",", "").replace(".", "")
    return int(raw) if raw.isdecimal() else None


def description(text):
    b = BEDS.search(text)
    a = AREA.search(text)
    f = FLOOR.search(text)
    return {
        "beds": int(b.group(1)) if b else (0 if re.search(r"stüdyo|studio|студи", text, re.I) else None),
        "area_m2": int(a.group(1)) if a else None,
        "floor": int(f.group(1)) if f else None,
    }


def parse_site(html):
    soup = BeautifulSoup(html, "html.parser")
    items = {}
    for h in soup.find_all(["h2", "h3"]):
        title = h.get_text(" ", strip=True)
        if not title or len(title) < 12:
            continue
        node = h
        card = None
        for _ in range(8):
            node = node.parent
            if node is None:
                break
            text = node.get_text(" ", strip=True)
            refs = set(REF.findall(text))
            if len(refs) == 1 and MONEY.search(text):
                card = (node, text, refs.pop().upper())
                break
            if len(refs) > 1:
                break
        if not card:
            continue
        node, text, ref = card
        link = h.find("a", href=True) or h.find_parent("a", href=True)
        if link is None:
            link = next((a for a in node.find_all("a", href=True)
                         if "ikinci-el/" in a["href"]), None)
        href = urljoin(SITE, link["href"]) if link else None
        fields = description(title)
        items[ref] = {"ref": ref, "title": title, "price_gbp": gbp(text),
                      "url": href, **fields}
    return items, "Sonuç bulunamadı" in soup.get_text(" ", strip=True)


def scan_site():
    session = requests.Session()
    session.headers.update({"User-Agent": "PrimeKibrisResaleWatch/1.0",
                            "Cache-Control": "no-cache"})
    all_items = {}
    pages = []
    for page in range(1, 21):
        url = SITE if page == 1 else SITE + "?page=" + str(page)
        response = session.get(url, timeout=25)
        response.raise_for_status()
        found, empty = parse_site(response.text)
        if page == 1 and not found:
            raise RuntimeError("First resale page returned no parseable listings; baseline unchanged")
        if not found:
            if not empty:
                raise RuntimeError("Page " + str(page) + " could not be verified; baseline unchanged")
            break
        if set(found).issubset(all_items):
            raise RuntimeError("Repeated pagination detected on page " + str(page))
        overlap = set(found).intersection(all_items)
        if overlap:
            raise RuntimeError("Duplicate references across pages: " + ", ".join(sorted(overlap)))
        all_items.update(found)
        pages.append({"page": page, "count": len(found)})
    else:
        raise RuntimeError("20-page scan cap reached; site scan incomplete")
    return all_items, pages


def sale_message(text):
    return bool(MONEY.search(text) and OFFER.search(text))


async def scan_telegram():
    session = os.getenv("TELEGRAM_STRING_SESSION_PRIME", "").strip()
    api_id = os.getenv("TELEGRAM_API_ID", "").strip()
    api_hash = os.getenv("TELEGRAM_API_HASH", "").strip()
    if not (session and api_id and api_hash):
        raise RuntimeError("Prime Telegram session/API secrets are unavailable")
    client = TelegramClient(StringSession(session), int(api_id), api_hash)
    records = {}
    try:
        await client.connect()
        if not await client.is_user_authorized():
            raise RuntimeError("Prime Telegram session is not authorized; refresh session")
        entity = await client.get_entity(CHANNEL)
        async for message in client.iter_messages(entity, limit=5000):
            text = (message.message or "").strip()
            if not text or not sale_message(text):
                continue
            mid = str(message.id)
            records[mid] = {
                "id": message.id,
                "link": "https://t.me/" + CHANNEL + "/" + mid,
                "published": message.date.isoformat() if message.date else None,
                "price_gbp": gbp(text),
                "hash": hashlib.sha256(text.encode("utf-8")).hexdigest()[:20],
                "excerpt": re.sub(r"\s+", " ", text)[:160],
                **description(text),
            }
        if not records:
            raise RuntimeError("No priced real-estate messages readable; baseline unchanged")
        return records, client, entity
    except Exception:
        await client.disconnect()
        raise


def project_terms(title):
    part = re.split(r"\b\d\s*[+＋]\s*1\b|stüdyo|studio|villa|penthouse|dubleks|daire|\|", title, 1, flags=re.I)[0]
    tokens = normalized(part).split()
    # Generic geography and category words alone cannot prove a unit match.
    generic = {"long", "beach", "satilik", "sat", "esentepe", "ma", "usa", "iskele", "kibris"}
    return [t for t in tokens if t not in generic and len(t) >= 2]


def possible_site_matches(message, sites):
    text = normalized(message["excerpt"])
    matches = []
    for entry in sites.values():
        terms = project_terms(entry["title"])
        if len(terms) < 1 or not all(term in text.split() for term in terms):
            continue
        if entry["beds"] is not None and message["beds"] is not None and entry["beds"] != message["beds"]:
            continue
        if entry["area_m2"] and message["area_m2"] and abs(entry["area_m2"] - message["area_m2"]) > 3:
            continue
        if entry["floor"] is not None and message["floor"] is not None and entry["floor"] != message["floor"]:
            continue
        matches.append(entry["ref"])
    return matches


async def compare(previous, sites, current, client, entity):
    first = "checked_at" not in previous
    before = previous.get("telegram", {})
    removed = []
    edited_to_other = []
    if not first:
        missing = [int(key) for key in before if key not in current]
        for start in range(0, len(missing), 100):
            ids = missing[start:start + 100]
            messages = await client.get_messages(entity, ids=ids)
            if not isinstance(messages, list):
                messages = [messages]
            if len(messages) != len(ids):
                raise RuntimeError("Deletion verification returned incomplete Telegram results")
            for mid, item in zip(ids, messages):
                if item is None or getattr(item, "empty", False) or type(item).__name__ == "MessageEmpty":
                    removed.append(before[str(mid)])
                elif not sale_message(getattr(item, "message", "") or ""):
                    edited_to_other.append(before[str(mid)])
                # A valid message still exists: do not mark it deleted.
    old_sites = previous.get("site", {})
    new = [v for k, v in current.items() if k not in before] if not first else []
    edited = [{"previous": before[k], "current": v} for k, v in current.items()
              if k in before and before[k]["hash"] != v["hash"]]
    site_new = [v for k, v in sites.items() if k not in old_sites] if not first else []
    site_missing = [v for k, v in old_sites.items() if k not in sites] if not first else []
    site_price = [{"previous": old_sites[k], "current": v} for k, v in sites.items()
                  if k in old_sites and old_sites[k]["price_gbp"] != v["price_gbp"]]
    for rec in current.values():
        rec["site_candidates"] = possible_site_matches(rec, sites)
    # Deletion is factual only after a Telegram message-ID lookup.
    for rec in removed:
        rec["site_candidates"] = possible_site_matches(rec, sites)
    price_review = []
    for rec in current.values():
        for ref in rec["site_candidates"]:
            site = sites[ref]
            if site["price_gbp"] is None or rec["price_gbp"] is None:
                continue
            ratio = site["price_gbp"] / rec["price_gbp"]
            if ratio < 1 or ratio > 1.10:
                price_review.append({"telegram": rec["link"], "ref": ref, "source": rec["price_gbp"],
                                     "site": site["price_gbp"], "ratio": round(ratio, 4),
                                     "status": "review_only_not_proven_same_unit"})
    return {"first_run_baseline": first, "telegram_count": len(current), "site_count": len(sites),
            "telegram_new": new, "telegram_deleted_verified": removed,
            "telegram_edited": edited, "telegram_edited_non_offer": edited_to_other,
            "site_new": site_new, "site_missing": site_missing,
            "site_price_changes": site_price, "price_review_candidates": price_review}


def send_telegram(report):
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat = os.getenv("TELEGRAM_CHAT_ID", "")
    if not token or not chat:
        print("Bot delivery unavailable: report saved as artifact")
        return
    lines = ["PRIME KIBRIS | IKINCI EL GUNLUK TAKIP",
             "Site: " + str(report["site_count"]) + " ilan, Telegram: "
             + str(report["telegram_count"]) + " fiyatli gayrimenkul mesaji"]
    if report["first_run_baseline"]:
        lines.append("Ilk calisma: referans alindi; eski mesajlar yeni olarak sayilmadi.")
    for key, caption in (
        ("telegram_new", "Telegram yeni"),
        ("telegram_deleted_verified", "Telegram SILINDI (ID dogrulandi)"),
        ("telegram_edited", "Telegram duzenlendi"),
        ("telegram_edited_non_offer", "Telegram satilik olmaktan cikarildi"),
        ("site_new", "Site yeni"),
        ("site_missing", "Site kaldirildi"),
        ("site_price_changes", "Site fiyat degisikligi"),
        ("price_review_candidates", "Fiyat farki >%10 / negatif (aday)"),
    ):
        entries = report[key]
        lines.append(caption + ": " + str(len(entries)))
        for entry in entries[:5]:
            raw = entry.get("current", entry)
            lines.append(" - " + str(raw.get("ref") or raw.get("link") or
                                   raw.get("telegram") or "")[:135])
    lines.append("Site ve Telegram ayni daire eslesmesi adaydir; ilanlari otomatik degistirmeyin.")
    data = "\n".join(lines)[:3900]
    r = requests.post("https://api.telegram.org/bot" + token + "/sendMessage",
                      data={"chat_id": chat, "text": data, "disable_web_page_preview": "true"}, timeout=20)
    r.raise_for_status()


async def main():
    previous = json.loads(STATE_PATH.read_text(encoding="utf-8")) if STATE_PATH.exists() else {}
    sites, pages = scan_site()
    current, client, entity = await scan_telegram()
    try:
        report = await compare(previous, sites, current, client, entity)
    finally:
        await client.disconnect()
    report["checked_at"] = datetime.now(timezone.utc).isoformat()
    report["pages"] = pages
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    STATE_PATH.write_text(json.dumps({"checked_at": report["checked_at"], "site": sites,
                                     "telegram": current}, ensure_ascii=False) + "\n", encoding="utf-8")
    print("RESALE_WATCH", json.dumps({k: len(v) if isinstance(v, list) else v
          for k, v in report.items() if k not in ("checked_at", "pages")}, ensure_ascii=False))
    try:
        send_telegram(report)
    except requests.RequestException as exc:
        print("Telegram bot delivery error; snapshot still saved:", type(exc).__name__)


if __name__ == "__main__":
    asyncio.run(main())

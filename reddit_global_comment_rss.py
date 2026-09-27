from __future__ import annotations

import hashlib
import json
import os
import re
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from google.cloud import firestore
from google.oauth2 import service_account

VERSION = "1.0-global-comment-rss"
LOOKBACK_DAYS = int(os.getenv("GLOBAL_REDDIT_COMMENT_LOOKBACK_DAYS", "14"))
NOTIFIED_COLLECTION = "bay_s_global_reddit_comment_notified"
SCAN_COLLECTION = "bay_s_global_reddit_comment_scans"

FEEDS = [
    ("expats comments", "https://www.reddit.com/r/expats/comments/.rss"),
    ("realestateinvesting comments", "https://www.reddit.com/r/realestateinvesting/comments/.rss"),
    ("retirement comments", "https://www.reddit.com/r/retirement/comments/.rss"),
    ("digitalnomad comments", "https://www.reddit.com/r/digitalnomad/comments/.rss"),
    ("ExpatFIRE comments", "https://www.reddit.com/r/ExpatFIRE/comments/.rss"),
    ("financialindependence comments", "https://www.reddit.com/r/financialindependence/comments/.rss"),
]

PROPERTY_RE = re.compile(
    r"(?:property|real estate|apartment|flat|house|home|villa|condo|second home|holiday home|"
    r"immobilie|wohnung|haus|nieruchomość|mieszkanie|bostad|lägenhet|casa|immobile|vivienda|inmueble|"
    r"imóvel|apartamento|bolig|lejlighed|asunto|talo|nemovitost|byt|kinnisvara|korter|عقار|شقة|منزل)",
    re.I,
)

BUY_RE = re.compile(
    r"(?:"
    r"\b(?:i|we)\b.{0,90}\b(?:want|looking|planning|considering|ready|need|seeking|interested|researching)\b.{0,110}\b(?:buy|purchase|invest|property|apartment|house|villa|home)\b|"
    r"\b(?:looking|planning|want|ready|trying)\s+to\s+(?:buy|purchase|invest)\b|"
    r"\b(?:second home|holiday home)\b.{0,90}\b(?:buy|purchase|budget|mortgage|deposit)\b|"
    r"\b(?:retire|retirement)\b.{0,120}\b(?:buy|purchase|property|home|house|apartment)\b|"
    r"\b(?:budget|deposit|payment plan|mortgage|cash buyer)\b.{0,120}\b(?:property|apartment|house|villa|home)\b|"
    r"\b(?:ich|wir)\b.{0,80}\b(?:möchte|moechte|wollen|will|suche|suchen|plane|planen|überlege|ueberlege)\b.{0,110}\b(?:kaufen|erwerben|immobilie|wohnung|haus)\b|"
    r"\b(?:chcę|chcemy|szukam|szukamy|planuję|planujemy)\b.{0,110}\b(?:kupić|nieruchomość|mieszkanie|dom)\b|"
    r"\b(?:jag|vi)\b.{0,80}\b(?:vill|planerar|överväger|söker)\b.{0,110}\b(?:köpa|bostad|lägenhet|hus|fastighet)\b|"
    r"\b(?:io|noi)\b.{0,80}\b(?:voglio|vogliamo|cerco|cerchiamo|penso|pensiamo)\b.{0,110}\b(?:comprare|acquistare|casa|immobile|appartamento)\b|"
    r"\b(?:yo|nosotros)\b.{0,80}\b(?:quiero|queremos|busco|buscamos|pienso|pensamos)\b.{0,110}\b(?:comprar|vivienda|casa|apartamento|inmueble)\b|"
    r"\b(?:eu|nós|nos)\b.{0,80}\b(?:quero|queremos|procuro|procuramos|planejo|planejamos)\b.{0,110}\b(?:comprar|casa|apartamento|imóvel)\b|"
    r"(?:أريد|نريد|أبحث|نبحث|أخطط|نخطط).{0,110}(?:شراء|عقار|شقة|منزل)"
    r")",
    re.I | re.S,
)

CONCRETE_RE = re.compile(
    r"(?:[£€$]\s*\d[\d\s.,]*(?:k|m)?|\b\d{2,4}\s*k\b|\bbudget\b|\bdeposit\b|"
    r"\bmortgage\b|\bpayment plan\b|\binstallments?\b|\bcash buyer\b|\bthis year\b|\bnext year\b)",
    re.I,
)

RENT_RE = re.compile(
    r"(?:\blooking to rent\b|\bfor rent\b|\brenting\b|\brental only\b|\bmonthly rent\b|\bper month\b|"
    r"\bаренд\w*\b|\bснять\b|\bсниму\b|\bkiralık\b|\bzu mieten\b)",
    re.I,
)

SELLER_RE = re.compile(
    r"(?:\bfor sale\b|\breal estate agent\b|\bestate agent\b|\brealtor\b|\bbroker\b|"
    r"\bdeveloper\b|\bcontact me\b|\bdm me\b|\bwhatsapp\b|\bour project\b|\bour properties\b|"
    r"\bavailable units?\b|\bprice from\b)",
    re.I,
)

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (compatible; BAY-S-Global-Reddit-Comments/1.0)",
    "Accept-Language": "en-US,en;q=0.9",
})


def now_utc():
    return datetime.now(timezone.utc)


def clean(v: str) -> str:
    return " ".join(str(v or "").split())


def parse_dt(raw: str):
    raw = clean(raw)
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def fetch_feed(label: str, url: str) -> list[dict]:
    try:
        r = SESSION.get(url, timeout=25)
        print("GLOBAL_COMMENT_RSS_HTTP", label, r.status_code)
        if r.status_code != 200:
            return []
        root = ET.fromstring(r.content)
        ns = {"a": "http://www.w3.org/2005/Atom"}
        rows = []
        cutoff = now_utc() - timedelta(days=LOOKBACK_DAYS)
        for entry in root.findall(".//a:entry", ns):
            title = clean(entry.findtext("a:title", default="", namespaces=ns))
            published = clean(
                entry.findtext("a:published", default="", namespaces=ns)
                or entry.findtext("a:updated", default="", namespaces=ns)
            )
            dt = parse_dt(published)
            if dt and dt < cutoff:
                continue
            link = ""
            for node in entry.findall("a:link", ns):
                href = str(node.attrib.get("href") or "")
                if href:
                    link = href
                    break
            html = entry.findtext("a:content", default="", namespaces=ns) or ""
            text = clean(BeautifulSoup(html, "html.parser").get_text(" ", strip=True))
            author = clean(entry.findtext("a:author/a:name", default="", namespaces=ns))
            rows.append({
                "source": "Reddit Comment RSS",
                "feed": label,
                "title": title,
                "text": text,
                "url": link,
                "author": author,
                "published": published,
            })
        print("GLOBAL_COMMENT_RSS_OK", label, len(rows))
        return rows
    except Exception as exc:
        print("GLOBAL_COMMENT_RSS_ERROR", label, type(exc).__name__, exc)
        return []


def classify(row: dict):
    text = clean(f"{row.get('title','')} {row.get('text','')}")
    if not text:
        return None, "empty"
    if SELLER_RE.search(text):
        return None, "seller_or_agent"
    if RENT_RE.search(text) and not BUY_RE.search(text):
        return None, "rental"
    if not PROPERTY_RE.search(text):
        return None, "no_property"
    if not BUY_RE.search(text):
        return None, "no_explicit_purchase_intent"
    concrete = bool(CONCRETE_RE.search(text))
    return {
        **row,
        "classification": "HOT" if concrete else "WARM",
        "intent_score": 95 if concrete else 85,
        "credibility_score": 88,
        "buyer_stage": "DIRECT",
        "buyer_signal": "reddit_global_comment_purchase",
        "market": "global_abroad",
        "route_to": "Prime Kıbrıs",
        "scanned_at": now_utc().isoformat(),
    }, "accepted"


def db_client():
    raw = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON", "").strip()
    if not raw:
        return None
    creds = service_account.Credentials.from_service_account_info(json.loads(raw))
    return firestore.Client(credentials=creds)


def notify(text: str):
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat:
        return
    requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat, "text": text, "disable_web_page_preview": False},
        timeout=20,
    ).raise_for_status()


def key_for(row: dict) -> str:
    basis = clean(row.get("url", "")) or clean(row.get("text", ""))[:500]
    return hashlib.sha256(f"reddit-global-comment|{basis}".encode()).hexdigest()


def run():
    started = now_utc()
    raw = []
    for label, url in FEEDS:
        raw.extend(fetch_feed(label, url))

    reasons = Counter()
    qualified = []
    seen = set()
    for row in raw:
        sig = clean(row.get("url", "")) or clean(row.get("text", ""))[:500]
        if not sig or sig in seen:
            continue
        seen.add(sig)
        lead, reason = classify(row)
        reasons[reason] += 1
        if lead:
            qualified.append(lead)

    db = db_client()
    new = []
    for lead in qualified:
        key = key_for(lead)
        if db:
            ref = db.collection(NOTIFIED_COLLECTION).document(key)
            try:
                if ref.get().exists:
                    continue
            except Exception as exc:
                print("GLOBAL_COMMENT_DEDUPE_READ_ERROR", type(exc).__name__, exc)
            try:
                ref.set({
                    "url": lead.get("url", ""),
                    "author": lead.get("author", ""),
                    "classification": lead.get("classification", ""),
                    "notified_at": started.isoformat(),
                }, merge=True)
            except Exception as exc:
                print("GLOBAL_COMMENT_DEDUPE_WRITE_ERROR", type(exc).__name__, exc)
        new.append(lead)

    if db:
        try:
            db.collection(SCAN_COLLECTION).document(started.strftime("%Y%m%d%H%M%S")).set({
                "version": VERSION,
                "raw": len(raw),
                "unique": len(seen),
                "qualified": len(qualified),
                "new": len(new),
                "reject_reasons": dict(reasons),
                "scanned_at": started.isoformat(),
            }, merge=True)
        except Exception as exc:
            print("GLOBAL_COMMENT_SCAN_WRITE_ERROR", type(exc).__name__, exc)

    print("GLOBAL_REDDIT_COMMENT_COMPLETE", json.dumps({
        "version": VERSION,
        "raw": len(raw),
        "unique": len(seen),
        "qualified": len(qualified),
        "new": len(new),
        "reject_reasons": dict(reasons),
    }, ensure_ascii=False))

    if new:
        lines = [f"💬 BAY-S GLOBAL REDDIT BUYER | {len(new)} YENİ BUYER"]
        for lead in new[:10]:
            lines.append(
                f"\n{lead['classification']} | @{lead.get('author','')} | I{lead['intent_score']}"
                f"\n{clean(lead.get('text',''))[:420]}"
                f"\n{lead.get('url','')}"
            )
        notify("\n".join(lines))
    return new


if __name__ == "__main__":
    run()

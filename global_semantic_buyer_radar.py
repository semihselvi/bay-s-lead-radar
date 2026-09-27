from __future__ import annotations

import hashlib
import json
import os
import re
from collections import Counter
from datetime import datetime, timedelta, timezone

import requests
from google.cloud import firestore
from google.oauth2 import service_account

VERSION = "1.0-global-semantic-intent"
LOOKBACK_DAYS = int(os.getenv("SEMANTIC_BUYER_LOOKBACK_DAYS", "30"))
MAX_RESULTS = int(os.getenv("SEMANTIC_BUYER_MAX_RESULTS", "20"))
NOTIFIED_COLLECTION = "bay_s_semantic_buyer_notified"
SCAN_COLLECTION = "bay_s_semantic_buyer_scans"

EXA_QUERIES = [
    "A person actively looking to buy property abroad, preferably a second home or investment property, with a real budget or timeline",
    "A person comparing countries to buy an apartment or house overseas for retirement, lifestyle, or investment",
    "A buyer asking where they can purchase Mediterranean property within a specific budget",
    "A person seeking an off-plan apartment abroad with installments or a payment plan",
    "A person asking for a second home overseas near the sea and discussing purchase price, deposit, mortgage, or financing",
    "A person planning to retire abroad and buy a home, apartment, or villa",
    "A person evaluating overseas real estate investment and asking about yield, purchase process, or location",
    "A person saying they want to buy property outside their home country but have not chosen the destination yet",
]

USER_DOMAINS = {
    "reddit.com", "old.reddit.com", "expat.com", "expatforum.com",
    "internations.org", "nomadgate.com", "bogleheads.org",
    "moneysavingexpert.com", "city-data.com",
}

PROPERTY_RE = re.compile(
    r"(?:property|real estate|apartment|flat|house|home|villa|condo|land|second home|holiday home|"
    r"immobilie|wohnung|haus|nieruchomość|mieszkanie|bostad|lägenhet|casa|immobile|vivienda|inmueble|"
    r"imóvel|apartamento|bolig|lejlighed|asunto|talo|nemovitost|byt|kinnisvara|korter|عقار|شقة|منزل)",
    re.I,
)

BUY_INTENT_RE = re.compile(
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
    r"(?:\blooking to rent\b|\bfor rent\b|\brenting\b|\brental only\b|\bmonthly rent\b|"
    r"\bper month\b|\bаренд\w*\b|\bснять\b|\bсниму\b|\bkiralık\b|\bzu mieten\b)",
    re.I,
)

SELLER_RE = re.compile(
    r"(?:\bfor sale\b|\breal estate agent\b|\bestate agent\b|\brealtor\b|\bbroker\b|"
    r"\bdeveloper\b|\bcontact me\b|\bdm me\b|\bwhatsapp\b|\bour project\b|\bour properties\b|"
    r"\bavailable units?\b|\bprice from\b)",
    re.I,
)

PAST_RE = re.compile(
    r"(?:\bi already bought\b|\bwe already bought\b|\bi purchased\b|\bwe purchased\b|"
    r"\bi own (?:a|an)\b|\balready purchased\b|\bno longer looking\b)",
    re.I,
)


def now_utc():
    return datetime.now(timezone.utc)


def clean(v: str) -> str:
    return " ".join(str(v or "").split())


def domain_of(url: str) -> str:
    try:
        from urllib.parse import urlparse
        return urlparse(url).netloc.lower().replace("www.", "")
    except Exception:
        return ""


def user_source(url: str) -> bool:
    d = domain_of(url)
    return any(d == x or d.endswith("." + x) for x in USER_DOMAINS)


def exa_search(query: str) -> list[dict]:
    key = os.getenv("EXA_API_KEY", "").strip()
    if not key:
        print("SEMANTIC_EXA_DISABLED missing EXA_API_KEY")
        return []
    cutoff = now_utc() - timedelta(days=LOOKBACK_DAYS)
    payload = {
        "query": query,
        "type": "auto",
        "numResults": max(1, min(MAX_RESULTS, 100)),
        "startPublishedDate": cutoff.strftime("%Y-%m-%dT00:00:00.000Z"),
        "includeDomains": sorted(USER_DOMAINS),
        "contents": {"text": {"maxCharacters": 4000}},
    }
    try:
        r = requests.post(
            "https://api.exa.ai/search",
            headers={"x-api-key": key, "Content-Type": "application/json"},
            json=payload,
            timeout=35,
        )
        if r.status_code != 200:
            print("SEMANTIC_EXA_ERROR", r.status_code, r.text[:220])
            return []
        out = []
        for item in r.json().get("results", []) or []:
            out.append({
                "source": "Exa Semantic",
                "url": item.get("url", ""),
                "title": item.get("title", ""),
                "text": item.get("text", ""),
                "published": item.get("publishedDate", ""),
                "author": item.get("author", "") or "",
                "semantic_query": query,
            })
        print("SEMANTIC_EXA_OK", len(out), query[:80])
        return out
    except Exception as exc:
        print("SEMANTIC_EXA_EXCEPTION", type(exc).__name__, exc)
        return []


def classify(item: dict):
    url = clean(item.get("url", ""))
    if not url or not user_source(url):
        return None, "non_user_source"
    text = clean(f"{item.get('title','')} {item.get('text','')}")
    if not text:
        return None, "empty"
    if SELLER_RE.search(text):
        return None, "seller_or_agent"
    if RENT_RE.search(text) and not BUY_INTENT_RE.search(text):
        return None, "rental"
    if PAST_RE.search(text) and not BUY_INTENT_RE.search(text):
        return None, "past_purchase"
    if not PROPERTY_RE.search(text):
        return None, "no_property"
    if not BUY_INTENT_RE.search(text):
        return None, "no_explicit_purchase_intent"

    concrete = bool(CONCRETE_RE.search(text))
    classification = "HOT" if concrete else "WARM"
    return {
        **item,
        "classification": classification,
        "intent_score": 94 if concrete else 84,
        "credibility_score": 82,
        "buyer_stage": "DIRECT",
        "buyer_signal": "semantic_global_purchase",
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


def lead_key(lead: dict) -> str:
    url = clean(lead.get("url", "")).split("?", 1)[0].rstrip("/")
    basis = url or clean(lead.get("text", ""))[:500]
    return hashlib.sha256(f"semantic|{basis}".encode()).hexdigest()


def run():
    started = now_utc()
    raw = []
    for q in EXA_QUERIES:
        raw.extend(exa_search(q))

    unique = {}
    for row in raw:
        url = clean(row.get("url", "")).split("?", 1)[0].rstrip("/")
        if url:
            unique[url] = row

    reasons = Counter()
    qualified = []
    for row in unique.values():
        lead, reason = classify(row)
        reasons[reason] += 1
        if lead:
            qualified.append(lead)

    db = db_client()
    new = []
    for lead in qualified:
        key = lead_key(lead)
        if db:
            ref = db.collection(NOTIFIED_COLLECTION).document(key)
            try:
                if ref.get().exists:
                    continue
            except Exception as exc:
                print("SEMANTIC_DEDUPE_READ_ERROR", type(exc).__name__, exc)
            try:
                ref.set({
                    "url": lead.get("url", ""),
                    "classification": lead.get("classification", ""),
                    "notified_at": started.isoformat(),
                }, merge=True)
            except Exception as exc:
                print("SEMANTIC_DEDUPE_WRITE_ERROR", type(exc).__name__, exc)
        new.append(lead)

    if db:
        try:
            db.collection(SCAN_COLLECTION).document(started.strftime("%Y%m%d%H%M%S")).set({
                "version": VERSION,
                "raw": len(raw),
                "unique": len(unique),
                "qualified": len(qualified),
                "new": len(new),
                "reject_reasons": dict(reasons),
                "scanned_at": started.isoformat(),
            }, merge=True)
        except Exception as exc:
            print("SEMANTIC_SCAN_WRITE_ERROR", type(exc).__name__, exc)

    print("SEMANTIC_BUYER_COMPLETE", json.dumps({
        "version": VERSION,
        "raw": len(raw),
        "unique": len(unique),
        "qualified": len(qualified),
        "new": len(new),
        "reject_reasons": dict(reasons),
    }, ensure_ascii=False))

    if new:
        lines = [f"🌊 BAY-S SEMANTIC BUYER | {len(new)} YENİ BUYER"]
        for lead in new[:10]:
            lines.append(
                f"\n{lead['classification']} | I{lead['intent_score']} C{lead['credibility_score']}"
                f"\n{clean(lead.get('title',''))[:130]}"
                f"\n{clean(lead.get('text',''))[:360]}"
                f"\n{lead.get('url','')}"
            )
        notify("\n".join(lines))
    return new


if __name__ == "__main__":
    run()

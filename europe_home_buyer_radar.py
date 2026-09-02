from __future__ import annotations

import hashlib
import json
import os
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import requests

import main

VERSION = "1.1-source-verified"
PROFILE = os.getenv("HOME_RADAR_PROFILE", "germany_home").strip().lower()
LOOKBACK_DAYS = int(os.getenv("HOME_RADAR_LOOKBACK_DAYS", "7"))
QUERY_LIMIT = int(os.getenv("HOME_RADAR_QUERY_LIMIT", "10"))
NOTIFIED_COLLECTION = "bay_s_europe_home_notified"
SCAN_COLLECTION = "bay_s_europe_home_scans"

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (compatible; BAY-S-Home-Buyer-Radar/1.1; +https://github.com/semihselvi/bay-s-lead-radar)",
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "en-US,en;q=0.9",
})

USER_DOMAINS = {
    "reddit.com", "old.reddit.com", "expat.com", "expatforum.com",
    "gutefrage.net", "finanztip.de", "hausbau-forum.de", "wertpapier-forum.de", "wiwi-treff.de",
    "tweakers.net", "forum.fok.nl", "investeerders.nl",
    "pim.be", "bouwinfo.be", "englishforum.ch", "beobachter.ch",
}

PROFILES = {
    "germany_home": {
        "icon": "🇩🇪", "title": "GERMANY HOME BUYER RADAR", "target": "germany", "hl": "de", "gl": "de",
        "target_re": re.compile(r"\b(?:germany|deutschland|berlin|m[üu]nchen|munich|hamburg|frankfurt|k[öo]ln|cologne|d[üu]sseldorf|stuttgart|leipzig|n[üu]rnberg)\b", re.I),
        "queries": [
            'site:reddit.com/r/germany ("buy apartment" OR "buy house" OR "buying a home") Germany',
            'site:reddit.com/r/berlin ("buy apartment" OR "buy flat")',
            'site:reddit.com/r/Munich ("buy apartment" OR "buy house")',
            'site:finanztip.de/community ("Wohnung kaufen" OR "Haus kaufen") Eigenkapital',
            'site:gutefrage.net "Wohnung kaufen" "ich suche"',
            'site:hausbau-forum.de "Haus kaufen" gesucht',
            'site:wertpapier-forum.de Immobilie kaufen Eigennutzung',
            'site:wiwi-treff.de Wohnung kaufen Finanzierung',
            'site:expat.com Germany "buy apartment" forum',
            'site:expatforum.com Germany "buy house"',
            'Deutschland "suche Wohnung zum Kauf" Budget',
            'Deutschland "Haus zum Kauf gesucht" Eigenkapital',
        ],
    },
    "netherlands_home": {
        "icon": "🇳🇱", "title": "NETHERLANDS HOME BUYER RADAR", "target": "netherlands", "hl": "nl", "gl": "nl",
        "target_re": re.compile(r"\b(?:netherlands|nederland|amsterdam|rotterdam|den\s+haag|the\s+hague|utrecht|eindhoven|haarlem|almere|groningen)\b", re.I),
        "queries": [
            'site:reddit.com/r/NetherlandsHousing ("buy house" OR "buy apartment")',
            'site:reddit.com/r/Netherlands "buy house" Netherlands',
            'site:reddit.com/r/Amsterdam "buy apartment"',
            'site:tweakers.net woning kopen hypotheek',
            'site:forum.fok.nl huis kopen "ik zoek"',
            'site:investeerders.nl woning kopen',
            'site:expat.com Netherlands "buy house" forum',
            'site:expatforum.com Netherlands "buy apartment"',
            'Nederland "koopwoning gezocht" budget',
            'Nederland "ik zoek een huis om te kopen" hypotheek',
            'Amsterdam "koopwoning gezocht"',
            'Utrecht "huis om te kopen" gezocht',
        ],
    },
    "belgium_home": {
        "icon": "🇧🇪", "title": "BELGIUM HOME BUYER RADAR", "target": "belgium", "hl": "nl", "gl": "be",
        "target_re": re.compile(r"\b(?:belgium|belgi[ëe]|belgique|brussels|brussel|bruxelles|antwerp|antwerpen|gent|ghent|leuven|brugge|li[eè]ge|charleroi)\b", re.I),
        "queries": [
            'site:reddit.com/r/belgium ("buy house" OR "buy apartment")',
            'site:reddit.com/r/brussels "buy apartment"',
            'site:pim.be ("appartement acheter" OR "woning kopen")',
            'site:bouwinfo.be woning kopen gezocht',
            'site:expat.com Belgium "buy apartment" forum',
            'site:expatforum.com Belgium "buy house"',
            'België "koopwoning gezocht" budget',
            'België "ik zoek een huis om te kopen"',
            'Belgique "recherche appartement à acheter" budget',
            'Bruxelles "cherche appartement à acheter"',
            'Antwerpen "woning kopen" "ik zoek"',
            'Leuven "appartement kopen" gezocht',
        ],
    },
    "switzerland_home": {
        "icon": "🇨🇭", "title": "SWITZERLAND HOME BUYER RADAR", "target": "switzerland", "hl": "de", "gl": "ch",
        "target_re": re.compile(r"\b(?:switzerland|schweiz|suisse|svizzera|z[üu]rich|zurich|geneva|gen[èe]ve|lausanne|basel|bern|luzern|lucerne|zug)\b", re.I),
        "queries": [
            'site:reddit.com/r/SwissPersonalFinance ("buy apartment" OR "buy house")',
            'site:reddit.com/r/Switzerland "buy apartment" Switzerland',
            'site:reddit.com/r/askswitzerland "buy house"',
            'site:englishforum.ch "buy apartment" Switzerland',
            'site:englishforum.ch "buy house" mortgage',
            'site:beobachter.ch Wohnung kaufen Hypothek',
            'site:expat.com Switzerland "buy house" forum',
            'site:expatforum.com Switzerland "buy apartment"',
            'Schweiz "Wohnung zum Kauf gesucht" Eigenkapital',
            'Schweiz "Haus zum Kauf gesucht" Hypothek',
            'Suisse "recherche appartement à acheter" budget',
            'Zürich "Wohnung kaufen" "ich suche"',
        ],
    },
}

PROPERTY_RE = re.compile(r"(?:property|real estate|apartment|flat|house|home|villa|condo|land|immobilie|wohnung|haus|eigentumswohnung|grundst[üu]ck|woning|huis|appartement|vastgoed|koopwoning|immobilier|maison|logement|terrain)", re.I)
BUYER_RE = re.compile(
    r"(?:\b(?:i|we)\b.{0,60}\b(?:want|looking|planning|trying|ready|considering|need)\b.{0,80}\b(?:buy|purchase|apartment|house|home|property)\b|"
    r"\blooking\s+for.{0,60}\b(?:to\s+buy|for\s+purchase)\b|"
    r"\b(?:ich|wir)\b.{0,60}\b(?:suche|suchen|möchte|moechte|möchten|moechten|will|wollen|plane|planen)\b.{0,80}\b(?:kaufen|kauf|wohnung|haus|immobilie)\b|"
    r"\b(?:wohnung|haus|immobilie)\s+zum\s+kauf\s+gesucht\b|"
    r"\b(?:ik|wij|we)\b.{0,60}\b(?:zoek|zoeken|wil|willen|plan|plannen)\b.{0,80}\b(?:kopen|woning|huis|appartement|vastgoed)\b|"
    r"\b(?:koopwoning|woning|huis|appartement)\s+gezocht\b|"
    r"\b(?:je|nous)\b.{0,60}\b(?:cherche|cherchons|veux|voulons|souhaite|souhaitons)\b.{0,80}\b(?:acheter|appartement|maison|immobilier|logement)\b|"
    r"\brecherche.{0,60}\b(?:appartement|maison|logement).{0,40}\b(?:acheter|achat)\b)", re.I | re.S)
RENT_RE = re.compile(r"(?:for rent|looking to rent|rental|renting|per month|monthly rent|mieten|mietwohnung|zur miete|monatsmiete|huren|huurwoning|te huur|maandhuur|louer|location|à louer|a louer|loyer)", re.I)
SELLER_RE = re.compile(r"(?:i am selling|we are selling|for sale|owner selling|contact us|whatsapp|real estate agent|estate agent|realtor|broker|developer|listing id|property id|ich verkaufe|wir verkaufen|zu verkaufen|immobilienmakler|makelaar|te koop aangeboden|je vends|nous vendons|à vendre|agence immobili)", re.I)
FOREIGN_RE = re.compile(r"\b(?:spain|spanien|spanje|espagne|portugal|italy|italien|italië|france|frankreich|greece|griechenland|cyprus|zypern|turkey|türkei|dubai|uae|montenegro|croatia|kroatien|austria|österreich|poland|polen)\b", re.I)
READY_RE = re.compile(r"(?:pre[- ]?approved|mortgage approved|cash buyer|ready to buy|make an offer|finanzierungsbestätigung|finanzierung.{0,40}(?:steht|bestätigt|genehmigt)|eigenkapital.{0,50}(?:vorhanden|verfügbar)|hypotheek.{0,40}(?:akkoord|rond|goedgekeurd)|financiering.{0,40}(?:goedgekeurd|rond)|apport.{0,50}(?:disponible|prêt)|financement.{0,40}(?:approuvé|accordé)|hypothek.{0,40}(?:bestätigt|genehmigt))", re.I | re.S)
BUDGET_RE = re.compile(r"(?:CHF|EUR|€|£|\$)\s*\d[\d\s.,]*(?:\s*[kKmM])?", re.I)
FINANCE_RE = re.compile(r"(?:mortgage|deposit|down payment|pre[- ]?approval|hypothek|eigenkapital|finanzierung|hypotheek|financiering|prêt hypothécaire|pret hypothecaire|apport|financement|cash buyer)", re.I)

CITY_PATTERNS = {
    "germany_home": ["Berlin", "München", "Munich", "Hamburg", "Frankfurt", "Düsseldorf", "Dusseldorf", "Köln", "Cologne", "Stuttgart", "Leipzig", "Nürnberg", "Nurnberg"],
    "netherlands_home": ["Amsterdam", "Rotterdam", "Den Haag", "The Hague", "Utrecht", "Eindhoven", "Haarlem", "Almere", "Groningen"],
    "belgium_home": ["Brussels", "Brussel", "Bruxelles", "Antwerp", "Antwerpen", "Gent", "Ghent", "Leuven", "Brugge", "Liège", "Liege", "Charleroi"],
    "switzerland_home": ["Zürich", "Zurich", "Geneva", "Genève", "Geneve", "Lausanne", "Basel", "Bern", "Luzern", "Lucerne", "Zug"],
}

_REDDIT_POST_RE = re.compile(r"/comments/([a-z0-9]+)/", re.I)


def now_utc():
    return datetime.now(timezone.utc)


def domain_of(url: str) -> str:
    try:
        return urlparse(url).netloc.lower().replace("www.", "")
    except Exception:
        return ""


def user_source(url: str) -> bool:
    d = domain_of(url)
    return any(d == x or d.endswith("." + x) for x in USER_DOMAINS)


def clean(text: str) -> str:
    return " ".join(str(text or "").split())


def query_targets_profile(profile: str, query: str) -> bool:
    spec = PROFILES[profile]
    return bool(spec["target_re"].search(query))


def reddit_post_id(url: str) -> str:
    match = _REDDIT_POST_RE.search(str(url or ""))
    return match.group(1).lower() if match else ""


def is_reddit_post(url: str) -> bool:
    try:
        domain = urlparse(str(url or "")).netloc.lower().removeprefix("www.")
    except Exception:
        return False
    return (domain == "reddit.com" or domain.endswith(".reddit.com")) and bool(reddit_post_id(url))


def parse_reddit_payload(original: dict, payload) -> dict | None:
    try:
        post = payload[0]["data"]["children"][0]["data"]
    except (KeyError, IndexError, TypeError):
        return None

    expected_id = reddit_post_id(str(original.get("url") or ""))
    actual_id = str(post.get("id") or "").lower()
    if not expected_id or actual_id != expected_id:
        return None

    title = clean(post.get("title", ""))
    body = clean(post.get("selftext", ""))
    if body.lower() in {"[deleted]", "[removed]"}:
        body = ""
    if not title and not body:
        return None

    published = ""
    try:
        published = datetime.fromtimestamp(float(post.get("created_utc")), timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        pass

    permalink = str(post.get("permalink") or "").strip()
    canonical = f"https://www.reddit.com{permalink}" if permalink.startswith("/") else str(original.get("url") or "")

    return {
        **original,
        "source": "Reddit direct",
        "url": canonical,
        "title": title,
        "text": body,
        "published": published,
        "author": str(post.get("author") or ""),
        "source_verified": True,
        "search_title": clean(original.get("title", "")),
        "search_snippet": clean(original.get("text", "")),
    }


def _reddit_json_urls(url: str) -> list[str]:
    post_id = reddit_post_id(url)
    clean_url = str(url or "").split("?", 1)[0].rstrip("/")
    return [
        f"{clean_url}.json?raw_json=1",
        f"https://www.reddit.com/comments/{post_id}.json?raw_json=1&limit=1",
    ]


def fetch_reddit_post(original: dict) -> tuple[dict | None, str]:
    url = str(original.get("url") or "")
    if not is_reddit_post(url):
        return original, "not_reddit"

    last_reason = "fetch_failed"
    for endpoint in _reddit_json_urls(url):
        try:
            response = SESSION.get(endpoint, timeout=6, allow_redirects=True)
        except Exception as exc:
            last_reason = f"exception:{type(exc).__name__}"
            continue
        if response.status_code != 200:
            last_reason = f"http_{response.status_code}"
            continue
        try:
            payload = response.json()
        except Exception:
            last_reason = "invalid_json"
            continue
        verified = parse_reddit_payload(original, payload)
        if verified is None:
            last_reason = "payload_mismatch"
            continue

        published = str(verified.get("published") or "")
        if published:
            try:
                dt = datetime.fromisoformat(published.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                if dt < now_utc() - timedelta(days=LOOKBACK_DAYS):
                    return None, "stale_reddit_post"
            except Exception:
                pass
        return verified, "verified"

    return None, last_reason


def serper_search(profile: str, query: str) -> list[dict]:
    key = os.getenv("SERPER_API_KEY", "").strip()
    if not key:
        raise RuntimeError("SERPER_API_KEY missing: this production radar does not silently fall back to blocked search engines")
    spec = PROFILES[profile]
    cutoff = (now_utc() - timedelta(days=LOOKBACK_DAYS)).date().isoformat()
    r = requests.post(
        "https://google.serper.dev/search",
        headers={"X-API-KEY": key, "Content-Type": "application/json"},
        json={"q": f"{query} after:{cutoff}", "num": 10, "hl": spec["hl"], "gl": spec["gl"], "tbs": "qdr:w"},
        timeout=25,
    )
    if r.status_code != 200:
        raise RuntimeError(f"Serper HTTP {r.status_code}: {r.text[:180]}")

    out = []
    verified_count = 0
    dropped_count = 0
    for row in r.json().get("organic", []) or []:
        item = {
            "source": "Serper",
            "url": row.get("link", ""),
            "title": row.get("title", ""),
            "text": row.get("snippet", ""),
            "published": row.get("date", ""),
            "author": "",
            "discovery_query": query,
        }
        if is_reddit_post(str(item.get("url") or "")):
            verified, reason = fetch_reddit_post(item)
            if verified is None:
                dropped_count += 1
                print(
                    "HOME_REDDIT_VERIFY_DROP",
                    f"profile={profile}",
                    f"reason={reason}",
                    f"url={item.get('url','')}",
                )
                continue
            item = verified
            verified_count += 1
        out.append(item)

    print(f"HOME_SERPER_OK profile={profile} results={len(out)} query={query!r}")
    if verified_count or dropped_count:
        print(
            "HOME_REDDIT_VERIFY_SUMMARY",
            f"profile={profile}",
            f"verified={verified_count}",
            f"dropped={dropped_count}",
            f"query={query!r}",
        )
    return out


def _foreign_destination(profile: str, text: str) -> bool:
    spec = PROFILES[profile]
    if not FOREIGN_RE.search(text):
        return False
    buy_positions = [m.start() for m in re.finditer(r"buy|purchase|kaufen|kauf|kopen|acheter|achat", text, re.I)]
    if not buy_positions:
        return False
    foreign_positions = [m.start() for m in FOREIGN_RE.finditer(text)]
    target_positions = [m.start() for m in spec["target_re"].finditer(text)]
    if not foreign_positions:
        return False
    fd = min(abs(a-b) for a in buy_positions for b in foreign_positions)
    td = min((abs(a-b) for a in buy_positions for b in target_positions), default=9999)
    return fd + 5 < td


def classify(profile: str, item: dict) -> tuple[dict | None, str]:
    spec = PROFILES[profile]
    url = str(item.get("url") or "")
    if not url or not user_source(url):
        return None, "non_user_source"
    text = clean(f"{item.get('title','')} {item.get('text','')}")
    if not text:
        return None, "empty"
    if RENT_RE.search(text):
        return None, "rental"
    if SELLER_RE.search(text):
        return None, "seller"
    if not PROPERTY_RE.search(text):
        return None, "no_property"
    if not BUYER_RE.search(text):
        return None, "no_buyer_voice"
    target_in_text = bool(spec["target_re"].search(text))
    bridged = False
    if not target_in_text:
        if query_targets_profile(profile, str(item.get("discovery_query") or "")) and not FOREIGN_RE.search(text):
            bridged = True
        else:
            return None, "target_mismatch"
    if _foreign_destination(profile, text):
        return None, "foreign_destination"

    budget = BUDGET_RE.search(text)
    finance = bool(FINANCE_RE.search(text))
    ready = bool(READY_RE.search(text))
    city = next((c for c in CITY_PATTERNS[profile] if re.search(rf"\b{re.escape(c)}\b", text, re.I)), "")
    concrete = sum(bool(x) for x in (budget, finance, city))
    if ready:
        stage = "READY"
    elif concrete >= 2:
        stage = "ACTIVE"
    else:
        stage = "RESEARCH"
    classification = "HOT" if ready else "WARM"
    intent = 78 + (8 if budget else 0) + (6 if finance else 0) + (4 if city else 0) + (4 if ready else 0)
    if bridged:
        intent -= 6
    lead = {
        **item,
        "profile": profile,
        "target_market": spec["target"],
        "classification": classification,
        "buyer_stage": stage,
        "intent_score": min(100, intent),
        "credibility_score": 90 if item.get("source_verified") else (82 if not bridged else 74),
        "requirements": {
            "budget": clean(budget.group(0)) if budget else "",
            "city": city,
            "financing": "mentioned" if finance else "",
        },
        "target_context_bridge": bridged,
        "radar_version": VERSION,
        "scanned_at": now_utc().isoformat(),
    }
    return lead, "accepted"


def semantic_key(profile: str, lead: dict) -> str:
    text = clean(f"{lead.get('title','')} {lead.get('text','')}").casefold()[:420]
    return hashlib.sha256(f"{profile}|{text}".encode()).hexdigest()


def run() -> list[dict]:
    if PROFILE not in PROFILES:
        raise SystemExit(f"Unknown HOME_RADAR_PROFILE={PROFILE}")
    if not os.getenv("SERPER_API_KEY", "").strip():
        raise SystemExit("SERPER_API_KEY missing: run this radar in bay-s-lead-radar where Serper is configured")

    spec = PROFILES[PROFILE]
    raw = []
    queries = spec["queries"][:max(1, min(QUERY_LIMIT, len(spec["queries"])))]
    for q in queries:
        raw.extend(serper_search(PROFILE, q))

    unique = {}
    for item in raw:
        if item.get("url"):
            unique[item["url"]] = item

    reasons = Counter()
    leads = []
    seen = set()
    for item in unique.values():
        lead, reason = classify(PROFILE, item)
        reasons[reason] += 1
        if not lead:
            continue
        key = semantic_key(PROFILE, lead)
        if key in seen:
            continue
        seen.add(key)
        lead["semantic_key"] = key
        leads.append(lead)

    stage_rank = {"READY": 3, "ACTIVE": 2, "RESEARCH": 1}
    leads.sort(key=lambda x: (x["classification"] == "HOT", stage_rank.get(x["buyer_stage"], 0), x["intent_score"]), reverse=True)

    db = main.db()
    new = []
    cutoff = now_utc() - timedelta(days=14)
    for lead in leads:
        key = lead["semantic_key"]
        ref = db.collection(NOTIFIED_COLLECTION).document(key)
        snap = ref.get()
        already = False
        if snap.exists:
            value = (snap.to_dict() or {}).get("notified_at", "")
            try:
                dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                already = dt >= cutoff
            except Exception:
                already = False
        if already:
            continue
        new.append(lead)
        ref.set({"profile": PROFILE, "url": lead.get("url", ""), "classification": lead["classification"], "notified_at": now_utc().isoformat()}, merge=True)

    scan_id = f"{now_utc().strftime('%Y%m%d%H%M%S')}_{PROFILE}"
    db.collection(SCAN_COLLECTION).document(scan_id).set({
        "profile": PROFILE, "version": VERSION, "raw": len(raw), "unique": len(unique),
        "qualified": len(leads), "new": len(new), "reject_reasons": dict(reasons),
        "queries": len(queries), "scanned_at": now_utc().isoformat(),
    }, merge=True)

    print("EUROPE_HOME_RADAR_COMPLETE", json.dumps({
        "profile": PROFILE, "version": VERSION, "raw": len(raw), "unique": len(unique),
        "qualified": len(leads), "new": len(new), "reject_reasons": dict(reasons)
    }, ensure_ascii=False))

    if not new:
        return []

    lines = [f"{spec['icon']} BAY-S {spec['title']} | {len(new)} YENİ LEAD"]
    for lead in new[:10]:
        req = lead.get("requirements") or {}
        detail = " | ".join(x for x in [req.get("city", ""), req.get("budget", ""), "finansman" if req.get("financing") else ""] if x)
        lines.append(
            f"\n{lead['classification']} | {lead['buyer_stage']} | I{lead['intent_score']} C{lead['credibility_score']}"
            + (f"\n{detail}" if detail else "")
            + f"\n{clean(lead.get('title',''))[:120]}\n{clean(lead.get('text',''))[:300]}\n{lead.get('url','')}"
        )
    main.telegram("\n".join(lines))
    return new


if __name__ == "__main__":
    run()

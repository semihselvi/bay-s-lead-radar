from __future__ import annotations

import hashlib
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from html import unescape
from typing import Any
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

import main as core


VERSION = "1.1-serper-places-small-business"
COLLECTION = "bay_s_small_business_web_prospects"
SCAN_COLLECTION = "bay_s_small_business_web_scans"
QUERY_LIMIT = int(os.getenv("SMALL_BIZ_QUERY_LIMIT", "16"))
SITE_LIMIT = int(os.getenv("SMALL_BIZ_SITE_LIMIT", "60"))
MIN_SCORE = int(os.getenv("SMALL_BIZ_MIN_SCORE", "38"))
MAX_ALERTS = int(os.getenv("SMALL_BIZ_MAX_ALERTS", "12"))
REQUEST_TIMEOUT = int(os.getenv("SMALL_BIZ_REQUEST_TIMEOUT", "12"))
MAX_WORKERS = int(os.getenv("SMALL_BIZ_MAX_WORKERS", "6"))

UA = (
    "Mozilla/5.0 (compatible; BAY-S-SmallBusinessWebRadar/1.1; "
    "+https://bay-s.com)"
)

# We deliberately target businesses whose websites are usually brochure/service
# sites. Retail/e-commerce, large resorts, developers and corporate sites are not
# target customers for this radar.
LOCATIONS = [
    ("Girne", "Girne"),
    ("Gazimağusa", "Gazimagusa"),
    ("İskele", "Iskele"),
    ("Lefkoşa", "Lefkosa"),
    ("Lapta", "Lapta"),
    ("Alsancak", "Alsancak"),
    ("Çatalköy", "Catalkoy"),
    ("Gönyeli", "Gonyeli"),
]

CATEGORIES = [
    ("restaurant", "restaurant"),
    ("cafe", "cafe"),
    ("hair_salon", "hair salon"),
    ("barber", "barber"),
    ("beauty_salon", "beauty salon"),
    ("dental", "dental clinic"),
    ("physiotherapy", "physiotherapy clinic"),
    ("car_rental", "car rental"),
    ("aircon", "air conditioning service"),
    ("plumber", "plumber"),
    ("electrician", "electrician"),
    ("pool_maintenance", "pool maintenance"),
    ("cleaning", "cleaning service"),
    ("lawyer", "lawyer"),
    ("accountant", "accountant"),
    ("translation", "translation service"),
    ("interior_design", "interior design studio"),
    ("veterinary", "veterinary clinic"),
    ("car_service", "car service garage"),
    ("fitness", "gym pilates studio"),
]

BLOCKED_HOST_TOKENS = (
    "facebook.com", "instagram.com", "tripadvisor.", "booking.com", "airbnb.",
    "wolt.com", "yelp.", "foursquare.com", "google.com", "goo.gl", "maps.app",
    "linkedin.com", "tiktok.com", "youtube.com", "x.com", "twitter.com",
    "restaurantguru.", "cybo.com", "findglocal.com", "yellowpages", "waze.com",
    "pinterest.", "expedia.", "hotels.com", "agoda.", "just-eat", "foodora",
)

NORTH_CYPRUS_RE = re.compile(
    r"(?:north(?:ern)?\s+cyprus|trnc|kktc|kuzey\s+k[ıi]br[ıi]s|"
    r"girne|kyrenia|gazima[gğ]usa|famagusta|iskele|İskele|long\s+beach|"
    r"lefko[sş]a|lapta|alsancak|[cç]atalk[oö]y|g[oö]nyeli|esentepe|"
    r"tatl[ıi]su|bafra|yenibo[gğ]azi[cç]i|karao[gğ]lano[gğ]lu|gaziveren|lefke)",
    re.I,
)
SOUTH_ONLY_RE = re.compile(r"\b(?:limassol|larnaca|paphos|ayia\s+napa|protaras)\b", re.I)

HARD_BIG_BUSINESS_RE = re.compile(
    r"(?:\bbank\b|\buniversity\b|\bcollege\b|\bhospital\b|\bcasino\b|\bresort\b|"
    r"\bshopping\s+mall\b|\bsupermarket\b|\bhypermarket\b|\btelecom\b|\bairline\b|"
    r"\bgovernment\b|\bmunicipality\b|\bministry\b|\bholding\b|"
    r"\bproperty\s+developer\b|\breal\s+estate\s+developer\b|\bconstruction\s+group\b)",
    re.I,
)
CHAIN_RE = re.compile(
    r"(?:\bchain\b|\bfranchise\b|group\s+of\s+companies|branches\s+across|"
    r"nationwide|international\s+offices|multiple\s+locations|corporate\s+group)",
    re.I,
)

ECOMMERCE_STRONG_RE = re.compile(
    r"(?:shopify|woocommerce|/cart\b|/checkout\b|add\s+to\s+cart|view\s+cart|shopping\s+cart)",
    re.I,
)
ECOMMERCE_SOFT_RE = re.compile(
    r"(?:shop\s+now|my\s+account|product\s+catalog|online\s+store|online\s+shop|"
    r"secure\s+checkout|payment\s+gateway|paypal|stripe)",
    re.I,
)

LEGACY_RE = re.compile(
    r"(?:<frameset\b|<frame\b|<font\b|\bbgcolor\s*=|document\.write\s*\(|"
    r"jquery[-.]1\.[0-9]|jquery[-.]2\.0|bootstrap(?:\.min)?\.css[^\n]{0,80}(?:3\.\d))",
    re.I,
)
UNDER_CONSTRUCTION_RE = re.compile(
    r"(?:under\s+construction|coming\s+soon|website\s+is\s+being\s+updated|"
    r"site\s+bak[ıi]mda|yak[ıi]nda\s+hizmetinizde)",
    re.I,
)
EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)
COPYRIGHT_RE = re.compile(r"(?:©|copyright(?:\s*©)?)[^\d]{0,24}(20\d{2})", re.I)
GENERIC_TITLE_RE = re.compile(r"^(?:home|homepage|welcome|anasayfa|ana\s+sayfa|index)$", re.I)


@dataclass
class Discovery:
    url: str
    title: str
    category: str
    city: str
    query: str
    address: str = ""
    phone: str = ""
    description: str = ""
    place_type: str = ""
    rating: float = 0.0
    rating_count: int = 0


def _host(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower().removeprefix("www.")
    except Exception:
        return ""


def _root_url(url: str) -> str:
    try:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return ""
        host = parsed.hostname.lower()
        if host in {"localhost", "127.0.0.1", "0.0.0.0", "::1"} or host.endswith(".local"):
            return ""
        port = f":{parsed.port}" if parsed.port else ""
        return f"{parsed.scheme}://{parsed.hostname}{port}/"
    except Exception:
        return ""


def blocked_url(url: str) -> bool:
    host = _host(url)
    return not host or any(token in host for token in BLOCKED_HOST_TOKENS)


def build_queries(now: datetime | None = None) -> list[tuple[str, str, str]]:
    now = now or datetime.now(timezone.utc)
    combos: list[tuple[str, str, str]] = []
    for city, location_query in LOCATIONS:
        for category, category_query in CATEGORIES:
            combos.append((city, category, f"{category_query} in {location_query} North Cyprus"))
    if not combos:
        return []
    limit = min(max(1, QUERY_LIMIT), len(combos))
    start = (now.toordinal() * limit) % len(combos)
    return [combos[(start + i) % len(combos)] for i in range(limit)]


def serper_places(query: str) -> list[dict[str, Any]]:
    key = os.getenv("SERPER_API_KEY", "").strip()
    if not key:
        raise RuntimeError("SERPER_API_KEY missing")
    r = requests.post(
        "https://google.serper.dev/places",
        headers={"X-API-KEY": key, "Content-Type": "application/json"},
        json={"q": query, "num": 20, "hl": "en"},
        timeout=30,
    )
    if r.status_code != 200:
        raise RuntimeError(f"SERPER_PLACES_HTTP_{r.status_code}: {r.text[:250]}")
    return list((r.json().get("places") or [])[:20])


def _place_reject_reason(row: dict[str, Any], city: str, query: str) -> str:
    website = str(row.get("website") or "")
    if not website:
        return "no_website"
    if blocked_url(website):
        return "blocked_platform"
    meta = " ".join([
        str(row.get("title") or ""),
        str(row.get("address") or ""),
        str(row.get("description") or ""),
        str(row.get("type") or row.get("category") or ""),
    ])
    if SOUTH_ONLY_RE.search(meta) and not NORTH_CYPRUS_RE.search(meta):
        return "south_cyprus"
    if HARD_BIG_BUSINESS_RE.search(meta):
        return "large_business"
    if CHAIN_RE.search(meta):
        return "chain"
    try:
        if int(row.get("ratingCount") or 0) >= 5000:
            return "too_large_by_reviews"
    except Exception:
        pass
    # Query itself contains the North-Cyprus locality; place metadata should at
    # least echo the locality or North Cyprus somewhere. This keeps Google Maps
    # spillover from the Republic of Cyprus out of the prospect list.
    if not NORTH_CYPRUS_RE.search(meta) and city.casefold() not in meta.casefold():
        return "location_mismatch"
    return ""


def discover() -> tuple[list[Discovery], int, int, dict[str, int]]:
    found: dict[str, Discovery] = {}
    queries = build_queries()
    raw = 0
    errors = 0
    rejects: dict[str, int] = {}
    for idx, (city, category, query) in enumerate(queries, 1):
        print(f"SMALL_BIZ_QUERY {idx}/{len(queries)} city={city} category={category} query={query!r}")
        try:
            rows = serper_places(query)
            print(f"SMALL_BIZ_PLACES_OK results={len(rows)}")
        except Exception as exc:
            errors += 1
            print(f"SMALL_BIZ_PLACES_ERROR {type(exc).__name__}: {exc}")
            continue
        for row in rows:
            raw += 1
            reason = _place_reject_reason(row, city, query)
            if reason:
                rejects[reason] = rejects.get(reason, 0) + 1
                continue
            root = _root_url(str(row.get("website") or ""))
            if not root:
                rejects["bad_website_url"] = rejects.get("bad_website_url", 0) + 1
                continue
            host = _host(root)
            if host in found:
                continue
            try:
                rating = float(row.get("rating") or 0)
            except Exception:
                rating = 0.0
            try:
                rating_count = int(row.get("ratingCount") or 0)
            except Exception:
                rating_count = 0
            found[host] = Discovery(
                url=root,
                title=str(row.get("title") or host),
                category=category,
                city=city,
                query=query,
                address=str(row.get("address") or ""),
                phone=str(row.get("phoneNumber") or ""),
                description=str(row.get("description") or ""),
                place_type=str(row.get("type") or row.get("category") or ""),
                rating=rating,
                rating_count=rating_count,
            )
    return list(found.values())[:SITE_LIMIT], raw, errors, rejects


def _clean_text(soup: BeautifulSoup) -> str:
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    return " ".join(soup.get_text(" ", strip=True).split())


def _contact_page(soup: BeautifulSoup, base_url: str) -> str:
    for a in soup.find_all("a", href=True):
        label = " ".join(a.get_text(" ", strip=True).lower().split())
        href = str(a.get("href") or "")
        if any(x in label for x in ("contact", "iletişim", "iletisim", "bize ulaş", "bize ulas")):
            url = urljoin(base_url, href)
            if _host(url) == _host(base_url):
                return url
    return ""


def extract_contacts(soup: BeautifulSoup, html: str, base_url: str) -> dict[str, str]:
    email = ""
    phone = ""
    whatsapp = ""
    instagram = ""
    facebook = ""
    for a in soup.find_all("a", href=True):
        href = unescape(str(a.get("href") or "")).strip()
        low = href.lower()
        if low.startswith("mailto:") and not email:
            email = href[7:].split("?")[0].strip()
        elif low.startswith("tel:") and not phone:
            phone = href[4:].strip()
        elif ("wa.me/" in low or "whatsapp.com/send" in low) and not whatsapp:
            whatsapp = href
        elif "instagram.com/" in low and not instagram:
            instagram = href
        elif "facebook.com/" in low and not facebook:
            facebook = href
    if not email:
        match = EMAIL_RE.search(html)
        if match:
            email = match.group(0)
    return {
        "email": email[:180],
        "phone": phone[:120],
        "whatsapp": whatsapp[:300],
        "instagram": instagram[:300],
        "facebook": facebook[:300],
        "contact_page": _contact_page(soup, base_url)[:300],
    }


def _page_reject_reason(html: str, text: str, soup: BeautifulSoup, base_url: str) -> str:
    sample = f"{html[:120000]} {text[:12000]}"
    if ECOMMERCE_STRONG_RE.search(sample):
        return "ecommerce"
    if len(ECOMMERCE_SOFT_RE.findall(sample)) >= 2:
        return "ecommerce"
    if len(CHAIN_RE.findall(text[:8000])) >= 2:
        return "large_business"
    host = _host(base_url)
    internal_links = 0
    for a in soup.find_all("a", href=True):
        target = urljoin(base_url, str(a.get("href") or ""))
        if _host(target) == host:
            internal_links += 1
    if internal_links > 180:
        return "large_site"
    return ""


def score_site(final_url: str, html: str, soup: BeautifulSoup, elapsed: float) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []
    head = soup.head or soup

    if urlparse(final_url).scheme != "https":
        score += 20
        reasons.append("HTTPS yok")

    viewport = head.find("meta", attrs={"name": re.compile(r"^viewport$", re.I)})
    if viewport is None:
        score += 20
        reasons.append("mobil viewport yok")

    description = head.find("meta", attrs={"name": re.compile(r"^description$", re.I)})
    if description is None or len(str(description.get("content") or "").strip()) < 25:
        score += 8
        reasons.append("meta açıklama zayıf/yok")

    if LEGACY_RE.search(html[:160000]):
        score += 24
        reasons.append("eski HTML/JS izleri")

    if UNDER_CONSTRUCTION_RE.search(html[:80000]):
        score += 35
        reasons.append("site yapımda/coming soon")

    years = [int(x) for x in COPYRIGHT_RE.findall(html[:160000])]
    if years:
        newest = max(years)
        if newest <= 2022:
            score += 15
            reasons.append(f"telif yılı eski ({newest})")
        elif newest <= 2023:
            score += 8
            reasons.append(f"telif yılı eski ({newest})")

    title = " ".join((soup.title.get_text(" ", strip=True) if soup.title else "").split())
    if not title or GENERIC_TITLE_RE.fullmatch(title):
        score += 8
        reasons.append("sayfa başlığı zayıf")

    if head.find("meta", attrs={"property": re.compile(r"^og:title$", re.I)}) is None:
        score += 4
        reasons.append("sosyal paylaşım meta verisi yok")

    favicon = head.find("link", rel=lambda v: v and "icon" in " ".join(v if isinstance(v, list) else [str(v)]).lower())
    if favicon is None:
        score += 3
        reasons.append("favicon yok")

    contact_cta = bool(re.search(r"(?:href=[\"']tel:|wa\.me/|whatsapp\.com/send|href=[\"']mailto:)", html, re.I))
    if not contact_cta:
        score += 8
        reasons.append("telefon/WhatsApp/e-posta CTA görünmüyor")

    if urlparse(final_url).scheme == "https" and re.search(r"(?:src|href)=[\"']http://", html[:180000], re.I):
        score += 8
        reasons.append("karışık HTTP içerik")

    if len(html) < 9000:
        score += 6
        reasons.append("ana sayfa çok temel")

    if elapsed >= 4.0:
        score += 8
        reasons.append(f"yavaş yanıt ({elapsed:.1f}s)")

    if soup.find("h1") is None:
        score += 5
        reasons.append("H1 başlık yok")

    if head.find("link", rel=lambda v: v and "canonical" in " ".join(v if isinstance(v, list) else [str(v)]).lower()) is None:
        score += 4
        reasons.append("canonical SEO etiketi yok")

    if soup.find("script", attrs={"type": re.compile(r"application/ld\+json", re.I)}) is None:
        score += 4
        reasons.append("yerel işletme schema verisi yok")

    images = soup.find_all("img")
    if len(images) >= 5:
        missing_alt = sum(not str(img.get("alt") or "").strip() for img in images)
        if missing_alt / len(images) >= 0.6:
            score += 5
            reasons.append("görsellerin çoğunda alt metin yok")

    return min(score, 100), reasons


def inspect_site(discovery: Discovery) -> dict[str, Any] | None:
    started = time.monotonic()
    try:
        r = requests.get(
            discovery.url,
            headers={"User-Agent": UA, "Accept-Language": "en,tr;q=0.9"},
            timeout=REQUEST_TIMEOUT,
            allow_redirects=True,
        )
        elapsed = time.monotonic() - started
        if r.status_code != 200:
            print(f"SMALL_BIZ_SITE_SKIP status={r.status_code} business={discovery.title!r} url={discovery.url}")
            return None
        content_type = str(r.headers.get("content-type") or "").lower()
        if "html" not in content_type and "<html" not in r.text[:1000].lower():
            return None
        html = r.text
        soup = BeautifulSoup(html, "html.parser")
        text = _clean_text(BeautifulSoup(html, "html.parser"))
        reject = _page_reject_reason(html, text, soup, str(r.url))
        if reject:
            print(f"SMALL_BIZ_REJECT reason={reject} business={discovery.title!r} url={discovery.url}")
            return None
        score, reasons = score_site(str(r.url), html, soup, elapsed)
        if score < MIN_SCORE:
            print(f"SMALL_BIZ_LOW_SCORE score={score} business={discovery.title!r} url={discovery.url}")
            return None
        contacts = extract_contacts(soup, html, str(r.url))
        if discovery.phone and not contacts["phone"]:
            contacts["phone"] = discovery.phone[:120]
        if not any(contacts.values()):
            print(f"SMALL_BIZ_NO_CONTACT business={discovery.title!r} url={discovery.url}")
            return None
        return {
            "business_name": discovery.title[:120],
            "website": str(r.url),
            "domain": _host(str(r.url)),
            "city": discovery.city,
            "category": discovery.category,
            "address": discovery.address[:300],
            "place_type": discovery.place_type[:120],
            "rating": discovery.rating,
            "rating_count": discovery.rating_count,
            "redesign_score": score,
            "classification": "HOT" if score >= 60 else "WARM",
            "reasons": reasons[:7],
            "contacts": contacts,
            "response_seconds": round(elapsed, 2),
            "radar_version": VERSION,
        }
    except requests.RequestException as exc:
        print(f"SMALL_BIZ_FETCH_ERROR business={discovery.title!r} url={discovery.url} error={type(exc).__name__}")
        return None
    except Exception as exc:
        print(f"SMALL_BIZ_INSPECT_ERROR business={discovery.title!r} url={discovery.url} error={type(exc).__name__}: {exc}")
        return None


def _lead_id(domain: str) -> str:
    return hashlib.sha256(domain.lower().encode("utf-8")).hexdigest()


def save_new(db_client, lead: dict[str, Any], now: datetime) -> bool:
    lead_id = _lead_id(lead["domain"])
    ref = db_client.collection(COLLECTION).document(lead_id)
    snap = ref.get()
    payload = dict(lead)
    payload["last_seen_at"] = now.isoformat()
    if snap.exists:
        old = snap.to_dict() or {}
        payload["first_seen_at"] = old.get("first_seen_at") or now.isoformat()
        payload["notified_at"] = old.get("notified_at")
        ref.set(payload, merge=True)
        return not bool(old.get("notified_at"))
    payload["first_seen_at"] = now.isoformat()
    ref.set(payload)
    return True


def mark_notified(db_client, lead: dict[str, Any], now: datetime) -> None:
    db_client.collection(COLLECTION).document(_lead_id(lead["domain"])).set(
        {"notified_at": now.isoformat(), "last_seen_at": now.isoformat()},
        merge=True,
    )


def _first_contact(contacts: dict[str, str]) -> str:
    for key in ("phone", "whatsapp", "email", "contact_page", "instagram", "facebook"):
        if contacts.get(key):
            return f"{key}: {contacts[key]}"
    return ""


def notify(lead: dict[str, Any]) -> None:
    emoji = "🔥" if lead["classification"] == "HOT" else "🟡"
    reasons = ", ".join(lead.get("reasons") or [])
    reviews = f" | Google yorum: {lead.get('rating_count', 0)}" if lead.get("rating_count") else ""
    msg = (
        f"{emoji} BAY-S WEB SATIŞ RADARI | {lead['classification']} {lead['redesign_score']}/100\n\n"
        f"İşletme: {lead['business_name']}\n"
        f"Bölge: {lead['city']}\n"
        f"Kategori: {lead['category']}{reviews}\n"
        f"Adres: {lead.get('address','')}\n\n"
        f"Neden aday: {reasons}\n\n"
        f"İletişim: {_first_contact(lead['contacts']) or 'site iletişim kanalı'}\n"
        f"Web: {lead['website']}\n\n"
        "Satış açısı: mevcut siteyi modern, mobil uyumlu, hızlı ve WhatsApp/arama dönüşümü güçlü yeni bir siteyle yenileme."
    )
    core.telegram(msg[:3900])


def main() -> None:
    now = datetime.now(timezone.utc)
    print(f"SMALL_BIZ_WEB_RADAR_START version={VERSION} query_limit={QUERY_LIMIT} site_limit={SITE_LIMIT}")
    db_client = core.db()
    discoveries, raw, search_errors, discovery_rejects = discover()
    print(
        f"SMALL_BIZ_DISCOVERY raw={raw} unique_sites={len(discoveries)} "
        f"search_errors={search_errors} rejects={discovery_rejects}"
    )

    qualified: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max(1, MAX_WORKERS)) as pool:
        futures = {pool.submit(inspect_site, d): d for d in discoveries}
        for future in as_completed(futures):
            lead = future.result()
            if lead is not None:
                qualified.append(lead)

    qualified.sort(key=lambda x: (x["redesign_score"], x.get("rating_count", 0)), reverse=True)
    new_leads: list[dict[str, Any]] = []
    for lead in qualified:
        if save_new(db_client, lead, now):
            new_leads.append(lead)

    for lead in new_leads[:MAX_ALERTS]:
        notify(lead)
        mark_notified(db_client, lead, now)

    scan = {
        "started_at": now.isoformat(),
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "radar_version": VERSION,
        "focus": "north_cyprus_small_business_website_redesign",
        "queries": min(QUERY_LIMIT, len(LOCATIONS) * len(CATEGORIES)),
        "places_raw": raw,
        "unique_sites": len(discoveries),
        "qualified": len(qualified),
        "new": len(new_leads),
        "alerts": min(len(new_leads), MAX_ALERTS),
        "search_errors": search_errors,
        "discovery_rejects": discovery_rejects,
    }
    scan_id = now.strftime("%Y%m%dT%H%M%SZ")
    db_client.collection(SCAN_COLLECTION).document(scan_id).set(scan)
    print(f"SMALL_BIZ_WEB_RADAR_COMPLETE {scan}")
    for lead in qualified[:12]:
        print(
            "SMALL_BIZ_CANDIDATE "
            f"score={lead['redesign_score']} class={lead['classification']} "
            f"business={lead['business_name']!r} city={lead['city']} url={lead['website']} "
            f"contact={_first_contact(lead['contacts'])!r} reasons={lead['reasons']}"
        )


if __name__ == "__main__":
    main()

from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.parse
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timedelta, timezone

import requests
from google.cloud import firestore
from google.oauth2 import service_account

VERSION = "1.3-youtube-local-fresh-ranking"
LOOKBACK_DAYS = int(os.getenv("NC_YOUTUBE_COMMENT_LOOKBACK_DAYS", "45"))
VIDEO_LIMIT = int(os.getenv("NC_YOUTUBE_VIDEO_LIMIT", "10"))
COMMENTS_PER_VIDEO = int(os.getenv("NC_YOUTUBE_COMMENTS_PER_VIDEO", "120"))
NOTIFIED_COLLECTION = "bay_s_nc_youtube_buyer_notified"
SCAN_COLLECTION = "bay_s_nc_youtube_buyer_scans"

DISCOVERY_QUERIES = [
    'site:youtube.com/watch "North Cyprus" property investment',
    'site:youtube.com/watch "North Cyprus" buy apartment villa',
    'site:youtube.com/watch "Northern Cyprus" real estate property',
    'site:youtube.com/watch "North Cyprus" title deed property',
    'site:youtube.com/watch "Северный Кипр" недвижимость купить',
    'site:youtube.com/watch "Северный Кипр" квартира инвестиции',
    'site:youtube.com/watch "Kuzey Kıbrıs" gayrimenkul yatırım',
    'site:youtube.com/watch "Kuzey Kıbrıs" daire satın almak',
    'site:youtube.com/watch "Nordzypern" Immobilie kaufen',
]

YOUTUBE_DIRECT_QUERIES = [
    "North Cyprus property investment",
    "North Cyprus buy apartment",
    "Northern Cyprus real estate",
    "North Cyprus off plan property",
    "North Cyprus title deed property",
    "Северный Кипр недвижимость купить",
    "Северный Кипр квартира инвестиции",
    "Kuzey Kıbrıs gayrimenkul yatırım",
    "Kuzey Kıbrıs daire satın almak",
    "Nordzypern Immobilie kaufen",
]

VIDEO_CONTEXT_RE = re.compile(
    r"(?:north(?:ern)?\s+cyprus|kuzey\s+kıbrıs|северн\w*\s+кипр|nordzypern).{0,180}"
    r"(?:property|real estate|apartment|villa|house|investment|immobil|wohnung|недвижим|квартир|gayrimenkul|daire)"
    r"|(?:property|real estate|apartment|villa|investment|immobil|недвижим|gayrimenkul).{0,180}"
    r"(?:north(?:ern)?\s+cyprus|kuzey\s+kıbrıs|северн\w*\s+кипр|nordzypern)",
    re.I | re.S,
)

HOT_INTENT_RE = re.compile(
    r"(?:"
    r"\b(?:i|we)\s+(?:want|plan|planning|looking|interested|ready)\b.{0,80}\b(?:buy|purchase|invest)\b|"
    r"\b(?:can i|can we|how do i|how can i)\b.{0,80}\b(?:buy|purchase)\b|"
    r"\b(?:payment plan|installments?|deposit|mortgage|title deed|deed|reservation|viewing|book a viewing)\b|"
    r"\b(?:foreigner|foreigners)\b.{0,80}\b(?:buy|purchase|own)\b|"
    r"[£€$]\s*\d[\d,\.]*|\b\d{2,4}\s*k\b|"
    r"\b(?:хочу|хотим|планир\w*|ищу|ищем)\b.{0,90}\b(?:купить|покупк\w*|квартир\w*|недвижимост\w*)\b|"
    r"\b(?:рассрочк\w*|первоначальн\w*\s+взнос|титул\w*|бюджет)\b|"
    r"\b(?:almak istiyorum|satın almak istiyorum|almayı düşünüyorum|ödeme planı|taksit|peşinat|koçan|bütçe)\b|"
    r"\b(?:ich|wir)\b.{0,80}\b(?:kaufen|interessiert|suche|suchen)\b|"
    r"\b(?:ratenzahlung|anzahlung|grundbuch|budget)\b"
    r")",
    re.I | re.S,
)

WARM_INTENT_RE = re.compile(
    r"(?:"
    r"\b(?:price|how much|cost|available|availability|more details|more info|send details|location|where is this|which project)\b|"
    r"\b(?:interested|i'm interested|im interested)\b|"
    r"\b(?:цена|сколько стоит|подробнее|интересно|локация|где находится|какой проект)\b|"
    r"\b(?:fiyat|ne kadar|detay|ilgileniyorum|konum|hangi proje|müsait mi)\b|"
    r"\b(?:preis|wie viel|details|interessiert|wo ist|welches projekt)\b"
    r")",
    re.I,
)

PROVIDER_RE = re.compile(
    r"(?:"
    r"\b(?:contact me|dm me|message me|whatsapp me|our project|our properties|we offer|we have units|"
    r"i am an agent|i'm an agent|real estate agent|realtor|broker|developer)\b|"
    r"\b(?:пишите мне|свяжитесь со мной|наш проект|наши объекты|риэлтор|агент по недвижимости)\b|"
    r"\b(?:bana yazın|iletişime geçin|projemiz|portföyümüzde|emlak danışmanıyım)\b"
    r")",
    re.I,
)

RENT_RE = re.compile(
    r"(?:\brent\b|\brental\b|\bmonthly\b|\bper month\b|\bаренд\w*\b|\bснять\b|\bkiralık\b|\bkiralam\w*\b)",
    re.I,
)

PRAISE_ONLY_RE = re.compile(
    r"^(?:great|nice|amazing|excellent|good|love it|beautiful|thanks?|thank you|wow|super|bravo|"
    r"класс|супер|спасибо|harika|güzel|teşekkürler|toll|danke)"
    r"(?:\s+(?:video|vid|content|property|place|project|work))?[!.\s❤️🔥👏]*$",
    re.I,
)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def clean(value: str) -> str:
    return " ".join(str(value or "").split())


def parse_comment_age(value: str) -> int | None:
    raw = clean(value).casefold()
    if not raw:
        return None
    if raw in {"just now", "today"}:
        return 0
    if raw == "yesterday":
        return 1
    m = re.search(r"\b(\d+)\s+(minute|hour|day|week|month|year)s?\s+ago\b", raw)
    if not m:
        return None
    n = int(m.group(1))
    unit = m.group(2)
    return {
        "minute": 0,
        "hour": 0,
        "day": n,
        "week": n * 7,
        "month": n * 30,
        "year": n * 365,
    }[unit]


def classify_comment(text: str) -> tuple[dict | None, str]:
    body = clean(text)
    if not body:
        return None, "empty"
    if PRAISE_ONLY_RE.match(body):
        return None, "praise_only"
    if PROVIDER_RE.search(body):
        return None, "provider"
    if RENT_RE.search(body) and not re.search(r"\b(?:buy|purchase|invest|купить|satın|almak|kaufen)\b", body, re.I):
        return None, "rental"

    hot = bool(HOT_INTENT_RE.search(body))
    warm = bool(WARM_INTENT_RE.search(body))
    if not hot and not warm:
        return None, "no_buyer_question"

    # Avoid accepting generic one-word "price" noise when the comment contains
    # no question/first-person/contextual request at all.
    if warm and not hot and len(body) < 4:
        return None, "too_short"

    return {
        "classification": "HOT" if hot else "WARM",
        "intent_score": 94 if hot else 82,
        "lead_class": "HOT BUYER" if hot else "WARM BUYER",
        "intent_type": "BUYER",
    }, "accepted"


def bing_rss(query: str, limit: int = 12) -> list[dict]:
    url = "https://www.bing.com/search?format=rss&q=" + urllib.parse.quote_plus(query)
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0 PrimeKibrisRadar/1.0"}, timeout=20)
        if r.status_code != 200:
            return []
        root = ET.fromstring(r.content)
        rows = []
        for item in root.findall(".//item")[:limit]:
            rows.append({
                "title": clean(item.findtext("title") or ""),
                "snippet": clean(item.findtext("description") or ""),
                "url": clean(item.findtext("link") or ""),
            })
        return rows
    except Exception:
        return []


def video_id(url: str) -> str:
    try:
        p = urllib.parse.urlparse(url)
        host = p.netloc.casefold()
        if "youtu.be" in host:
            return p.path.strip("/").split("/", 1)[0]
        if "/shorts/" in p.path:
            return p.path.split("/shorts/", 1)[1].split("/", 1)[0]
        if "/embed/" in p.path:
            return p.path.split("/embed/", 1)[1].split("/", 1)[0]
        return urllib.parse.parse_qs(p.query).get("v", [""])[0]
    except Exception:
        return ""



def _balanced_json_object(text: str, object_start: int) -> str:
    """Return one JSON object starting at object_start using brace balancing."""
    if object_start < 0 or object_start >= len(text) or text[object_start] != "{":
        return ""
    depth = 0
    in_string = False
    escaped = False
    for idx in range(object_start, len(text)):
        ch = text[idx]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[object_start: idx + 1]
    return ""


def _renderer_text(renderer: dict, key: str) -> str:
    value = renderer.get(key) or {}
    if isinstance(value, dict):
        simple = clean(value.get("simpleText") or "")
        if simple:
            return simple
        runs = value.get("runs") or []
        if isinstance(runs, list):
            return clean(" ".join(str(row.get("text") or "") for row in runs if isinstance(row, dict)))
    return ""


def _extract_video_renderers(html: str, query: str, limit: int = 36) -> list[dict]:
    rows = []
    seen = set()
    marker = '"videoRenderer":'
    pos = 0
    while len(rows) < limit:
        hit = html.find(marker, pos)
        if hit < 0:
            break
        object_start = html.find("{", hit + len(marker))
        if object_start < 0:
            break
        raw = _balanced_json_object(html, object_start)
        pos = object_start + max(1, len(raw))
        if not raw:
            continue
        try:
            renderer = json.loads(raw)
        except Exception:
            continue
        vid = clean(renderer.get("videoId") or "")
        if not re.fullmatch(r"[A-Za-z0-9_-]{11}", vid) or vid in seen:
            continue
        seen.add(vid)
        title = _renderer_text(renderer, "title")
        published = _renderer_text(renderer, "publishedTimeText")
        description = _renderer_text(renderer, "descriptionSnippet")
        age_days = parse_comment_age(published)
        rows.append({
            "video_id": vid,
            "url": f"https://www.youtube.com/watch?v={vid}",
            "title": title,
            "context": clean(f"{title} {description}")[:900],
            "query": query,
            "discovery": "youtube_video_renderer",
            "video_published": published,
            "video_age_days": age_days,
        })
    return rows


def youtube_direct_search(query: str, limit: int = 24) -> list[dict]:
    """Discover public YouTube videos and read visible upload age locally.

    YouTube removed/reworked reliable upload-date sorting in 2026, so Radar
    does not trust the old sp= upload-date parameter. Instead it parses
    publishedTimeText from each public search result and ranks videos itself.
    """
    url = "https://www.youtube.com/results?search_query=" + urllib.parse.quote_plus(query)
    try:
        r = requests.get(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; PrimeKibrisRadar/1.3)",
                "Accept-Language": "en-US,en;q=0.9",
            },
            timeout=20,
        )
        if r.status_code != 200:
            print("NC_YOUTUBE_DIRECT_HTTP", r.status_code, query)
            return []

        rows = _extract_video_renderers(r.text, query, limit=limit)
        if not rows:
            # Defensive fallback if YouTube changes the renderer wrapper.
            seen = set()
            for vid in re.findall(r'"videoId":"([A-Za-z0-9_-]{11})"', r.text):
                if vid in seen:
                    continue
                seen.add(vid)
                rows.append({
                    "video_id": vid,
                    "url": f"https://www.youtube.com/watch?v={vid}",
                    "title": "",
                    "context": "",
                    "query": query,
                    "discovery": "youtube_regex_fallback",
                    "video_published": "",
                    "video_age_days": None,
                })
                if len(rows) >= limit:
                    break

        recent = sum(
            1 for row in rows
            if isinstance(row.get("video_age_days"), int) and row["video_age_days"] <= 180
        )
        print("NC_YOUTUBE_DIRECT_OK", len(rows), "recent180", recent, query)
        return rows
    except Exception as exc:
        print("NC_YOUTUBE_DIRECT_ERROR", type(exc).__name__, query, exc)
        return []


def _rank_video_candidates(rows: list[dict], limit: int) -> list[dict]:
    dedup = {}
    for row in rows:
        vid = clean(row.get("video_id") or "") or video_id(row.get("url", ""))
        if not vid:
            continue
        candidate = dict(row)
        candidate["video_id"] = vid
        candidate["url"] = f"https://www.youtube.com/watch?v={vid}"
        age = candidate.get("video_age_days")
        if not isinstance(age, int):
            age = None
            candidate["video_age_days"] = None

        existing = dedup.get(vid)
        if existing is None:
            dedup[vid] = candidate
            continue
        old_age = existing.get("video_age_days")
        # Prefer the observation that carries a usable upload age/title.
        if old_age is None and age is not None:
            dedup[vid] = candidate
        elif not existing.get("title") and candidate.get("title"):
            dedup[vid] = candidate

    def rank(row: dict):
        age = row.get("video_age_days")
        known = isinstance(age, int)
        context = clean(f"{row.get('title','')} {row.get('context','')}")
        market_hint = bool(re.search(
            r"(?:north(?:ern)?\s+cyprus|kuzey\s+kıbrıs|kuzey\s+kibris|северн\w*\s+кипр|nordzypern|"
            r"\biskele\b|\bİskele\b|\bkyrenia\b|\bgirne\b|\bfamagusta\b|\bmağusa\b|\bmagusa\b|"
            r"\blong beach\b|\besentepe\b|\btatl[ıi]su\b|\bbafra\b|\blapta\b|\balsancak\b|"
            r"\bискеле\b|\bкирен\w*\b|\bфамагуст\w*\b|\bлонг бич\b)",
            context,
            re.I,
        ))
        property_hint = bool(re.search(
            r"(?:property|real estate|apartment|flat|villa|house|home|investment|title deed|off[- ]?plan|"
            r"недвижим|квартир|апартамент|вилл|дом|gayrimenkul|daire|ev|villa|immobil|wohnung|haus)",
            context,
            re.I,
        ))
        # Local market/property fit is primary. Within the same fit bucket,
        # prefer recent videos and keep unknown/old videos as fallback only.
        context_penalty = 0 if (market_hint and property_hint) else 1 if market_hint else 2
        if age is None:
            age_bucket = 4
            age_rank = 99999
        elif age <= 45:
            age_bucket = 0
            age_rank = age
        elif age <= 180:
            age_bucket = 1
            age_rank = age
        elif age <= 365:
            age_bucket = 2
            age_rank = age
        else:
            age_bucket = 5
            age_rank = age
        return (context_penalty, age_bucket, age_rank, row.get("title", ""))

    return sorted(dedup.values(), key=rank)[:limit]


def discover_videos() -> list[dict]:
    pool = []
    year = str(now_utc().year)
    month_year = now_utc().strftime("%B %Y")

    # Collect enough candidates to rank by actual visible upload age instead of
    # trusting YouTube's search order.
    direct_queries = list(dict.fromkeys([
        *(f"{q} {month_year}" for q in YOUTUBE_DIRECT_QUERIES[:5]),
        *(f"{q} {year}" for q in YOUTUBE_DIRECT_QUERIES),
        *YOUTUBE_DIRECT_QUERIES,
    ]))

    for q in direct_queries:
        pool.extend(youtube_direct_search(q, limit=24))
        recent_count = sum(
            1 for row in pool
            if isinstance(row.get("video_age_days"), int) and row["video_age_days"] <= 180
        )
        if recent_count >= max(VIDEO_LIMIT * 2, 20):
            break

    direct_count = len({row.get("video_id") for row in pool if row.get("video_id")})

    # Search-engine discovery remains a fallback/secondary source.
    for q in DISCOVERY_QUERIES:
        try:
            search_rows = bing_rss(q)
        except Exception:
            search_rows = []
        for row in search_rows:
            vid = video_id(row.get("url", ""))
            if not vid:
                continue
            context = clean(f"{row.get('title','')} {row.get('snippet','')}")
            if not VIDEO_CONTEXT_RE.search(context):
                continue
            pool.append({
                "video_id": vid,
                "url": f"https://www.youtube.com/watch?v={vid}",
                "title": row.get("title", ""),
                "context": context[:800],
                "query": q,
                "discovery": "bing_rss",
                "video_published": "",
                "video_age_days": None,
            })

    videos = _rank_video_candidates(pool, VIDEO_LIMIT)
    recent45 = sum(
        1 for row in videos
        if isinstance(row.get("video_age_days"), int) and row["video_age_days"] <= 45
    )
    recent180 = sum(
        1 for row in videos
        if isinstance(row.get("video_age_days"), int) and row["video_age_days"] <= 180
    )
    print("NC_YOUTUBE_DISCOVERY", json.dumps({
        "pool": len(pool),
        "direct_unique": direct_count,
        "selected": len(videos),
        "video_recent45": recent45,
        "video_recent180": recent180,
        "samples": [
            {
                "id": row.get("video_id"),
                "age": row.get("video_age_days"),
                "published": row.get("video_published"),
                "title": clean(row.get("title") or "")[:100],
            }
            for row in videos[:8]
        ],
    }, ensure_ascii=False))
    return videos

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


def lead_key(video: dict, row: dict) -> str:
    cid = clean(row.get("cid") or row.get("id") or "")
    basis = cid or f"{video.get('video_id')}|{clean(row.get('author',''))}|{clean(row.get('text',''))[:500]}"
    return hashlib.sha256(f"youtube-nc|{basis}".encode("utf-8")).hexdigest()


def run():
    try:
        from youtube_comment_downloader import YoutubeCommentDownloader, SORT_BY_RECENT
    except Exception as exc:
        print("NC_YOUTUBE_DISABLED", type(exc).__name__, exc)
        return []

    started = now_utc()
    videos = discover_videos()
    downloader = YoutubeCommentDownloader()
    db = db_client()
    rejects = Counter()
    scanned = 0
    qualified = []
    new = []

    for video in videos:
        try:
            count = 0
            for row in downloader.get_comments_from_url(video["url"], sort_by=SORT_BY_RECENT):
                if count >= COMMENTS_PER_VIDEO:
                    break
                count += 1
                scanned += 1
                body = clean(row.get("text") or "")
                age = parse_comment_age(str(row.get("time") or ""))
                if age is not None and age > LOOKBACK_DAYS:
                    rejects["stale"] += 1
                    continue

                signal, reason = classify_comment(body)
                rejects[reason] += 1
                if not signal:
                    continue

                cid = clean(row.get("cid") or row.get("id") or "")
                permalink = video["url"] + (f"&lc={urllib.parse.quote(cid)}" if cid else "")
                lead = {
                    **signal,
                    "source": "YouTube North Cyprus",
                    "platform": "YouTube",
                    "source_type": "north_cyprus_property_video_comment",
                    "author": clean(row.get("author") or ""),
                    "message": body,
                    "text": body,
                    "url": permalink,
                    "video_url": video["url"],
                    "video_title": video.get("title", ""),
                    "message_age_days": age if age is not None else "",
                    "freshness": "0_7d" if age is not None and age <= 7 else "8_45d" if age is not None else "unknown",
                    "market": "north_cyprus",
                    "route_to": "Prime Kıbrıs",
                    "found_at": started.isoformat(),
                    "radar_version": VERSION,
                    "why_selected": "North Cyprus property video + direct buyer question",
                }
                qualified.append(lead)

                key = lead_key(video, row)
                if db:
                    ref = db.collection(NOTIFIED_COLLECTION).document(key)
                    try:
                        if ref.get().exists:
                            rejects["known"] += 1
                            continue
                    except Exception:
                        pass
                    try:
                        ref.set({
                            "author": lead["author"],
                            "url": lead["url"],
                            "classification": lead["classification"],
                            "message": lead["message"][:700],
                            "notified_at": started.isoformat(),
                        }, merge=True)
                    except Exception:
                        pass
                new.append(lead)
        except Exception as exc:
            rejects[f"video_{type(exc).__name__}"] += 1

    if db:
        try:
            db.collection(SCAN_COLLECTION).document(started.strftime("%Y%m%d%H%M%S")).set({
                "version": VERSION,
                "videos": len(videos),
                "comments": scanned,
                "qualified": len(qualified),
                "new": len(new),
                "reject_reasons": dict(rejects),
                "scanned_at": started.isoformat(),
            }, merge=True)
        except Exception:
            pass

    debug = (
        "🎥 PRIME RADAR | YOUTUBE BUYER\n\n"
        f"Video: {len(videos)} | Yorum: {scanned} | Geçerli BUYER: {len(qualified)} | Yeni: {len(new)}\n"
        f"Taze video: <=45g {sum(1 for v in videos if isinstance(v.get('video_age_days'), int) and v['video_age_days'] <= 45)}"
        f" | <=180g {sum(1 for v in videos if isinstance(v.get('video_age_days'), int) and v['video_age_days'] <= 180)}\n"
        f"Eleme: {dict(rejects)}"
    )
    try:
        notify(debug[:3900])
    except Exception:
        pass

    if new:
        lines = [f"🔥 PRIME RADAR | YOUTUBE | {len(new)} YENİ BUYER"]
        for lead in sorted(new, key=lambda x: x["intent_score"], reverse=True)[:10]:
            lines.append(
                f"\n{lead['classification']} | I{lead['intent_score']} | {lead.get('freshness','')}"
                f"\n👤 {lead.get('author') or '-'}"
                f"\n{lead.get('message','')[:420]}"
                f"\n🎬 {lead.get('video_title','')[:130]}"
                f"\n{lead.get('url','')}"
            )
        notify("\n".join(lines)[:3900])

    print("NC_YOUTUBE_BUYER_COMPLETE", json.dumps({
        "version": VERSION,
        "videos": len(videos),
        "comments": scanned,
        "qualified": len(qualified),
        "new": len(new),
        "reject_reasons": dict(rejects),
    }, ensure_ascii=False))
    return new


if __name__ == "__main__":
    run()

from __future__ import annotations

import json
import os
import subprocess
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup

import northlab_sales_radar as radar

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (compatible; NorthlabSalesSourceHub/1.0)",
    "Accept-Language": "en-US,en;q=0.9",
})

LOOKBACK_DAYS = int(os.getenv("NORTHLAB_SOURCE_HUB_LOOKBACK_DAYS", "14"))
YOUTUBE_VIDEO_LIMIT = int(os.getenv("NORTHLAB_YOUTUBE_VIDEO_LIMIT", "10"))
YOUTUBE_COMMENTS_PER_VIDEO = int(os.getenv("NORTHLAB_YOUTUBE_COMMENTS_PER_VIDEO", "100"))
FORUM_URL_LIMIT = int(os.getenv("NORTHLAB_FORUM_URL_LIMIT", "10"))

REDDIT_FEEDS = [
    ("webdev", "https://www.reddit.com/r/webdev/new/.rss"),
    ("smallbusiness", "https://www.reddit.com/r/smallbusiness/new/.rss"),
    ("Entrepreneur", "https://www.reddit.com/r/Entrepreneur/new/.rss"),
    ("startups", "https://www.reddit.com/r/startups/new/.rss"),
    ("freelance_forhire", "https://www.reddit.com/r/forhire/new/.rss"),
]

BLUESKY_QUERIES = [
    "looking for web developer",
    "need a website",
    "website redesign",
    "wordpress developer needed",
    "shopify developer needed",
    "booking system developer",
    "crm setup developer",
    "workflow automation",
    "ai automation developer",
    "custom software developer",
    "api integration developer",
    "mobile app developer",
]

DISCOVERY_QUERIES = [
    '"looking for web developer" forum',
    '"need a website" forum',
    '"website redesign" forum',
    '"booking system" developer forum',
    '"crm setup" developer forum',
    '"workflow automation" forum',
    '"custom software" developer forum',
    '"mobile app" developer forum',
    '"looking for web developer" youtube',
    '"need a website" youtube',
    '"website redesign" youtube',
    '"automation developer" youtube',
]

FORUM_HINTS = ("forum", "community", "discourse", "phpbb", "xenforo", "smf", "invision")


def _clean(v: str) -> str:
    return " ".join(str(v or "").split())


def _parse_dt(raw: str):
    raw = _clean(raw)
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def reddit_adapter() -> list[dict]:
    out = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)
    ns = {"a": "http://www.w3.org/2005/Atom"}
    for label, url in REDDIT_FEEDS:
        try:
            r = SESSION.get(url, timeout=25)
            if r.status_code != 200:
                print("NORTHLAB_REDDIT_HTTP", label, r.status_code)
                continue
            root = ET.fromstring(r.content)
            for entry in root.findall(".//a:entry", ns):
                published = _clean(
                    entry.findtext("a:published", default="", namespaces=ns)
                    or entry.findtext("a:updated", default="", namespaces=ns)
                )
                dt = _parse_dt(published)
                if dt and dt < cutoff:
                    continue
                link = ""
                for node in entry.findall("a:link", ns):
                    href = str(node.attrib.get("href") or "")
                    if href:
                        link = href
                        break
                html = entry.findtext("a:content", default="", namespaces=ns) or ""
                text = _clean(BeautifulSoup(html, "html.parser").get_text(" ", strip=True))
                title = _clean(entry.findtext("a:title", default="", namespaces=ns))
                author = _clean(entry.findtext("a:author/a:name", default="", namespaces=ns))
                out.append({
                    "source": "Reddit",
                    "platform": "Reddit",
                    "group": label,
                    "author": author,
                    "title": title,
                    "text": f"{title}. {text}".strip(),
                    "url": link,
                    "published": published,
                })
        except Exception as exc:
            print("NORTHLAB_REDDIT_ERROR", label, type(exc).__name__, exc)
    print("NORTHLAB_SOURCE reddit", len(out))
    return out


def bluesky_adapter() -> list[dict]:
    out = []
    endpoint = "https://public.api.bsky.app/xrpc/app.bsky.feed.searchPosts"
    for q in BLUESKY_QUERIES:
        try:
            r = SESSION.get(endpoint, params={"q": q, "limit": 50, "sort": "latest"}, timeout=25)
            if r.status_code != 200:
                print("NORTHLAB_BLUESKY_HTTP", r.status_code, q)
                continue
            for row in r.json().get("posts", []) or []:
                record = row.get("record") or {}
                author = row.get("author") or {}
                uri = str(row.get("uri") or "")
                rkey = uri.rsplit("/", 1)[-1] if "/" in uri else ""
                handle = str(author.get("handle") or "")
                out.append({
                    "source": "Bluesky",
                    "platform": "Bluesky",
                    "group": q,
                    "author": handle,
                    "text": _clean(record.get("text") or ""),
                    "url": f"https://bsky.app/profile/{handle}/post/{rkey}" if handle and rkey else "",
                    "published": record.get("createdAt") or row.get("indexedAt") or "",
                })
        except Exception as exc:
            print("NORTHLAB_BLUESKY_ERROR", q, type(exc).__name__, exc)
    print("NORTHLAB_SOURCE bluesky", len(out))
    return out


def bing_rss(query: str) -> list[dict]:
    try:
        url = "https://www.bing.com/search?format=rss&q=" + quote_plus(query)
        r = SESSION.get(url, timeout=20)
        if r.status_code != 200:
            return []
        root = ET.fromstring(r.content)
        out = []
        for item in root.findall(".//item")[:12]:
            out.append({
                "title": _clean(item.findtext("title") or ""),
                "text": _clean(BeautifulSoup(item.findtext("description") or "", "html.parser").get_text(" ", strip=True)),
                "url": _clean(item.findtext("link") or ""),
                "published": _clean(item.findtext("pubDate") or ""),
            })
        return out
    except Exception:
        return []


def discover_surfaces() -> tuple[list[str], list[str]]:
    youtube = []
    forums = []
    seen = set()
    for q in DISCOVERY_QUERIES:
        for row in bing_rss(q):
            url = row.get("url") or ""
            if not url or url in seen:
                continue
            seen.add(url)
            low = url.casefold()
            if "youtube.com/watch" in low or "youtu.be/" in low:
                youtube.append(url)
            elif any(x in low for x in FORUM_HINTS):
                forums.append(url)
    return youtube[:YOUTUBE_VIDEO_LIMIT], forums[:FORUM_URL_LIMIT]


def youtube_adapter(urls: list[str]) -> list[dict]:
    try:
        from youtube_comment_downloader import YoutubeCommentDownloader, SORT_BY_RECENT
    except Exception as exc:
        print("NORTHLAB_YOUTUBE_DISABLED", type(exc).__name__, exc)
        return []
    out = []
    d = YoutubeCommentDownloader()
    for url in urls:
        try:
            count = 0
            for row in d.get_comments_from_url(url, sort_by=SORT_BY_RECENT):
                if count >= YOUTUBE_COMMENTS_PER_VIDEO:
                    break
                text = _clean(row.get("text") or "")
                if not text:
                    continue
                out.append({
                    "source": "YouTube Comment",
                    "platform": "YouTube",
                    "group": url,
                    "author": _clean(row.get("author") or ""),
                    "text": text,
                    "url": url,
                    "published": str(row.get("time_parsed") or row.get("time") or ""),
                })
                count += 1
            print("NORTHLAB_YOUTUBE_OK", count, url)
        except Exception as exc:
            print("NORTHLAB_YOUTUBE_ERROR", type(exc).__name__, url, exc)
    print("NORTHLAB_SOURCE youtube", len(out))
    return out


def forum_adapter(urls: list[str]) -> list[dict]:
    out = []
    timeout = int(os.getenv("NORTHLAB_FORUM_DL_TIMEOUT", "35"))
    for url in urls:
        try:
            p = subprocess.run(
                ["forum-dl", "-q", "--textify", "--no-files", "-f", "jsonl", "-o", "-", url],
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
            if p.returncode != 0:
                print("NORTHLAB_FORUM_ERROR", p.returncode, url, p.stderr[-220:])
                continue
            for line in p.stdout.splitlines():
                line = line.strip()
                if not line.startswith("{"):
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                author = obj.get("author") or obj.get("username") or obj.get("user") or ""
                if isinstance(author, dict):
                    author = author.get("name") or author.get("username") or ""
                text = (
                    obj.get("content") or obj.get("text") or obj.get("body") or
                    obj.get("message") or obj.get("raw") or obj.get("description") or ""
                )
                title = obj.get("title") or obj.get("subject") or obj.get("thread_title") or ""
                out.append({
                    "source": "Forum",
                    "platform": "Forum",
                    "group": url,
                    "author": _clean(author),
                    "title": _clean(title),
                    "text": _clean(f"{title} {text}"),
                    "url": _clean(obj.get("url") or obj.get("permalink") or obj.get("link") or url),
                    "published": _clean(obj.get("date") or obj.get("created_at") or obj.get("published") or ""),
                })
        except Exception as exc:
            print("NORTHLAB_FORUM_EXCEPTION", type(exc).__name__, url, exc)
    print("NORTHLAB_SOURCE forums", len(out))
    return out


def collect_all() -> tuple[list[dict], dict]:
    youtube_urls, forum_urls = discover_surfaces()
    sources = {}
    all_rows = []
    for name, fn in [
        ("reddit", reddit_adapter),
        ("bluesky", bluesky_adapter),
        ("youtube", lambda: youtube_adapter(youtube_urls)),
        ("forums", lambda: forum_adapter(forum_urls)),
    ]:
        try:
            rows = fn()
        except Exception as exc:
            print("NORTHLAB_SOURCE_ADAPTER_ERROR", name, type(exc).__name__, exc)
            rows = []
        sources[name] = len(rows)
        all_rows.extend(rows)
    return all_rows, {
        "source_counts": sources,
        "youtube_urls": len(youtube_urls),
        "forum_urls": len(forum_urls),
    }


def process_rows(db_client, now, rows: list[dict], debug: dict) -> list[dict]:
    out = []
    seen = set()
    for row in rows:
        sig = radar._lead_id(
            str(row.get("source") or ""),
            str(row.get("url") or ""),
            str(row.get("author") or ""),
            str(row.get("text") or ""),
        )
        if sig in seen:
            debug["hub_rejects"]["duplicate"] += 1
            continue
        seen.add(sig)

        signal, reason = radar.classify(str(row.get("text") or ""))
        if signal is None:
            debug["hub_rejects"][reason] += 1
            continue

        lead = {**row, **signal, "radar_version": radar.VERSION}
        debug["hub_accepted"] += 1
        debug["accepted_classes"][signal["lead_class"]] += 1
        debug["project_types"].update(signal["project_types"])
        debug["languages"][signal["language"]] += 1
        if radar._save_new(db_client, lead, now):
            out.append(lead)
    return out

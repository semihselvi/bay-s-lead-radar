from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse
import re

import requests

import europe_abroad_buyer_radar as base

VERSION = "1.1-source-verified"
base.VERSION = VERSION

_ORIGINAL_SERPER = base.serper_search
SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (compatible; BAY-S-Buyer-Radar/1.1; +https://github.com/semihselvi/bay-s-lead-radar)",
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "en-US,en;q=0.9",
})

_REDDIT_POST_RE = re.compile(r"/comments/([a-z0-9]+)/", re.I)


def reddit_post_id(url: str) -> str:
    match = _REDDIT_POST_RE.search(str(url or ""))
    return match.group(1).lower() if match else ""


def is_reddit_post(url: str) -> bool:
    try:
        domain = urlparse(str(url or "")).netloc.lower().removeprefix("www.")
    except Exception:
        return False
    return (domain == "reddit.com" or domain.endswith(".reddit.com")) and bool(reddit_post_id(url))


def _parse_reddit_payload(original: dict, payload) -> dict | None:
    """Build an item only from the actual Reddit post, never from search snippets.

    Google/Serper snippets for Reddit can contain 'more posts you may like' text from a
    different thread. That is unsafe for lead qualification, so the post JSON is the
    source of truth.
    """
    try:
        listing = payload[0]["data"]["children"]
        post = listing[0]["data"]
    except (KeyError, IndexError, TypeError):
        return None

    expected_id = reddit_post_id(str(original.get("url") or ""))
    actual_id = str(post.get("id") or "").lower()
    if not expected_id or actual_id != expected_id:
        return None

    title = base.clean(post.get("title", ""))
    body = base.clean(post.get("selftext", ""))
    if body.lower() in {"[deleted]", "[removed]"}:
        body = ""
    if not title and not body:
        return None

    created = post.get("created_utc")
    published = ""
    try:
        published = datetime.fromtimestamp(float(created), timezone.utc).isoformat()
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
        "search_title": base.clean(original.get("title", "")),
        "search_snippet": base.clean(original.get("text", "")),
    }


def _reddit_json_urls(url: str) -> list[str]:
    post_id = reddit_post_id(url)
    clean_url = str(url or "").split("?", 1)[0].rstrip("/")
    return [
        f"{clean_url}.json?raw_json=1",
        f"https://www.reddit.com/comments/{post_id}.json?raw_json=1&limit=1",
        f"https://old.reddit.com/comments/{post_id}.json?raw_json=1&limit=1",
    ]


def fetch_reddit_post(original: dict) -> tuple[dict | None, str]:
    url = str(original.get("url") or "")
    if not is_reddit_post(url):
        return original, "not_reddit"

    last_status = "fetch_failed"
    for endpoint in _reddit_json_urls(url):
        try:
            response = SESSION.get(endpoint, timeout=15, allow_redirects=True)
        except Exception as exc:
            last_status = f"exception:{type(exc).__name__}"
            continue
        if response.status_code != 200:
            last_status = f"http_{response.status_code}"
            continue
        try:
            payload = response.json()
        except Exception:
            last_status = "invalid_json"
            continue
        verified = _parse_reddit_payload(original, payload)
        if verified is None:
            last_status = "payload_mismatch"
            continue

        published = verified.get("published") or ""
        if published:
            try:
                dt = datetime.fromisoformat(str(published).replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                if dt < base.now_utc() - timedelta(days=base.LOOKBACK_DAYS):
                    return None, "stale_reddit_post"
            except Exception:
                pass
        return verified, "verified"

    return None, last_status


def verified_serper_search(profile: str, query: str) -> list[dict]:
    rows = _ORIGINAL_SERPER(profile, query)
    out: list[dict] = []
    verified_count = 0
    dropped_count = 0
    for item in rows:
        if not is_reddit_post(str(item.get("url") or "")):
            out.append(item)
            continue
        verified, reason = fetch_reddit_post(item)
        if verified is None:
            dropped_count += 1
            print(
                "ABROAD_REDDIT_VERIFY_DROP",
                f"profile={profile}",
                f"reason={reason}",
                f"url={item.get('url','')}",
            )
            continue
        verified_count += 1
        out.append(verified)
    if verified_count or dropped_count:
        print(
            "ABROAD_REDDIT_VERIFY_SUMMARY",
            f"profile={profile}",
            f"verified={verified_count}",
            f"dropped={dropped_count}",
            f"query={query!r}",
        )
    return out


# Production rule: a Reddit search snippet is discovery only. It can never become a
# lead until the exact permalink has been fetched and verified.
base.serper_search = verified_serper_search


def run():
    return base.run()


if __name__ == "__main__":
    run()

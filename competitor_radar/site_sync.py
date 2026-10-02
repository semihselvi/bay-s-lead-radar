"""Discover all published Turkish resale listings from Prime Kıbrıs' own sitemap.
Never infer that a failed sitemap means zero listings: fall back to the approved catalog.
"""
from __future__ import annotations
import re
from urllib.parse import urlparse
from xml.etree import ElementTree as ET
import requests
from bs4 import BeautifulSoup

SITEMAP = "https://primekibris.com/sitemap-tr-resale.xml"
SITE_HOSTS = {"primekibris.com", "www.primekibris.com"}
REF_RE = re.compile(r"PK-2E-\d{6}", re.I)
PRICE_RE = re.compile(r"(?:£|GBP)\s*([0-9][0-9., ]{3,})", re.I)
AREA_RE = re.compile(r"(\d{2,4})\s*(?:m²|m2)", re.I)
BEDS_RE = re.compile(r"\b([0-9])\s*\+\s*1\b")
GENERIC = {"satilik", "satılık", "ikinci", "el", "daire", "villa", "studio", "studyo", "stüdyo",
           "penthouse", "duplex", "dubleks", "kat", "floor", "m2", "resale"}


def project_from_title(title):
    # Project names precede apartment type / area in existing Prime Kıbrıs titles.
    first = re.split(r"\s*[|–—]\s*", title, maxsplit=1)[0].strip()
    first = re.sub(r"\b\d+\s*\+\s*1\b.*$", "", first).strip()
    first = re.sub(r"\b\d{2,4}\s*(?:m²|m2)\b.*$", "", first, flags=re.I).strip()
    tokens = first.split()
    while tokens and tokens[-1].lower() in GENERIC:
        tokens.pop()
    return " ".join(tokens[:5]).strip()


def sitemap_urls(session, timeout=15):
    r = session.get(SITEMAP, timeout=timeout)
    r.raise_for_status()
    root = ET.fromstring(r.content)
    urls = []
    for el in root.iter():
        if el.tag.rsplit("}", 1)[-1] != "loc" or not el.text:
            continue
        url = el.text.strip()
        p = urlparse(url)
        if p.scheme == "https" and p.netloc in SITE_HOSTS and "/tr/ikinci-el/" in p.path:
            urls.append(url)
    if not urls:
        raise ValueError("Sitemap returned no Turkish resale detail URLs")
    return list(dict.fromkeys(urls))


def parse_listing(html, url):
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.find("h1")
    title = h1.get_text(" ", strip=True) if h1 else ""
    if not title:
        tag = soup.find("meta", property="og:title")
        title = tag.get("content", "") if tag else ""
    if not title:
        return None
    body = soup.get_text(" ", strip=True)[:6000]
    price = None
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            import json
            data = json.loads(tag.string or tag.get_text())
        except (ValueError, TypeError):
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            obj = stack.pop()
            if isinstance(obj, list):
                stack.extend(obj)
            if not isinstance(obj, dict):
                continue
            stack.extend(v for v in obj.values() if isinstance(v, (list, dict)))
            if str(obj.get("priceCurrency", "")).upper() in ("GBP", "STG") and obj.get("price"):
                try:
                    price = int(float(str(obj["price"]).replace(",", "")))
                except ValueError:
                    pass
    if price is None:
        m = PRICE_RE.search(body[:1400])
        if m:
            digits = re.sub(r"[^0-9]", "", m.group(1))
            if digits:
                price = int(digits)
    m = BEDS_RE.search(title)
    beds = int(m.group(1)) if m else (0 if re.search(r"stüdyo|studio", title, re.I) else None)
    m = AREA_RE.search(title)
    area = int(m.group(1)) if m else None
    project = project_from_title(title)
    if not project or beds is None:
        return None
    return {"url": url, "title": title, "project": project, "aliases": [project],
            "beds": beds, "area_m2": area, "price_gbp": price}


def sync(catalog, session=None):
    """Return merged catalog, status. Existing approved properties always win."""
    session = session or requests.Session()
    merged = [dict(p) for p in catalog["properties"]]
    by_url = {p.get("prime_url"): p for p in merged if p.get("prime_url")}
    # Existing refs and names protect against duplicate creation from live site.
    known_names = {(p["beds"], re.sub(r"[^a-z0-9]", "", p["project"].lower())) for p in merged}
    status = {"source": SITEMAP, "site_urls": 0, "new_properties": 0,
              "unparsed": [], "errors": [], "fallback_count": len(merged)}
    try:
        urls = sitemap_urls(session)
    except (requests.RequestException, ET.ParseError, ValueError) as e:
        status["errors"].append("sitemap_" + type(e).__name__)
        return {**catalog, "properties": merged}, status
    status["site_urls"] = len(urls)
    for url in urls:
        if url in by_url:
            continue
        try:
            r = session.get(url, timeout=15)
            r.raise_for_status()
            obj = parse_listing(r.text, url)
            if obj is None:
                status["unparsed"].append(url)
                continue
            key = (obj["beds"], re.sub(r"[^a-z0-9]", "", obj["project"].lower()))
            # Same project and bedroom count may contain several distinct units;
            # use title and area for stronger comparison, but do not drop same-project units.
            same = next((p for p in merged if p.get("prime_url") == url), None)
            if same:
                continue
            # For known catalog entries without their URL, use price/area/bedrooms
            # to link; never overwrite their manually approved fields.
            candidate = next((p for p in merged if
                p["beds"] == obj["beds"] and
                re.sub(r"[^a-z0-9]", "", p["project"].lower()) == key[1] and
                p.get("area_m2") == obj["area_m2"] and
                p.get("our_price_gbp") == obj["price_gbp"] and
                not p.get("prime_url")), None)
            if candidate:
                candidate["prime_url"] = url
                continue
            new = {"ref": "URL:" + urlparse(url).path.rsplit("/", 1)[-1],
                   "name": obj["title"], "project": obj["project"],
                   "aliases": obj["aliases"], "beds": obj["beds"],
                   "our_price_gbp": obj["price_gbp"], "our_extra_gbp": 0,
                   "prime_url": url, "seed_urls": []}
            if obj["area_m2"]:
                new["area_m2"] = obj["area_m2"]
            merged.append(new)
            status["new_properties"] += 1
        except requests.RequestException as e:
            status["errors"].append("detail_" + type(e).__name__ + ":" + url)
    return {**catalog, "properties": merged}, status

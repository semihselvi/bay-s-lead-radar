from __future__ import annotations

import re
from urllib.parse import urlparse

import reddit_nc_buyer_miner_resilient as app


_BLOCKED_SUBREDDIT_RE = re.compile(
    r"/(?:r/)(?:buttcoin|beschissene_werbungen|cryptocurrency|memes?|shitposting|scams?)(?:/|$)",
    re.I,
)

_VIRTUAL_PROPERTY_RE = re.compile(
    r"(?:"
    r"\bvirtual\s+(?:property|real\s+estate|land)\b|"
    r"\bvirtuelle\s+immobilie\w*\b|\bvirtuelles\s+grundst[üu]ck\b|"
    r"\bmetaverse\b|\bdigital\s+land\b|\bnft\s+(?:land|property)\b|"
    r"\bcrypto\s+(?:property|land)\b"
    r")",
    re.I,
)

_original_classify_index_result = app.classify_index_result


def _combined(row: dict) -> str:
    return " ".join(
        str(row.get(k) or "") for k in ("title", "snippet", "text")
    )


def _real_north_context(row: dict) -> bool:
    url = str(row.get("link") or row.get("url") or "")
    low = url.casefold()
    if "/r/northcyprus/" in low:
        return True
    # Serper query wording is discovery context only. It must never manufacture
    # a North-Cyprus signal when the returned Reddit thread itself is unrelated.
    return bool(app.base.NORTH_RE.search(_combined(row)))


def classify_index_result_quality(row: dict, query: str):
    url = str(row.get("link") or row.get("url") or "")
    combined = _combined(row)

    try:
        path = urlparse(url).path.casefold()
    except Exception:
        path = url.casefold()

    if _BLOCKED_SUBREDDIT_RE.search(path):
        return None, "blocked_nonbuyer_subreddit"
    if _VIRTUAL_PROPERTY_RE.search(combined):
        return None, "virtual_or_crypto_property"
    if not _real_north_context(row):
        return None, "no_north_context"

    return _original_classify_index_result(row, query)


app.classify_index_result = classify_index_result_quality


if __name__ == "__main__":
    app.run()

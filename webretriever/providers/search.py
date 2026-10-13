"""Web search providers with automatic fallback.

Chain (first working provider wins):
  1. TinyFish  — highest quality, needs TINYFISH_API_KEY env var
  2. DuckDuckGo HTML — keyless, no signup

Rate limits are respected: TinyFish search is 5 req/min on the free plan.
"""

from __future__ import annotations

import html as html_lib
import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import List, Optional
from urllib.parse import quote_plus, urlparse

import requests

LOGGER = logging.getLogger("webretriever.search")

_TINYFISH_SEARCH_URL = "https://api.search.tinyfish.ai"
_DDG_HTML_URL = "https://html.duckduckgo.com/html/"
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

_last_tinyfish_search = 0.0


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str = ""
    site: str = ""
    provider: str = ""


def _domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lower().removeprefix("www.")
    except Exception:
        return ""


def tinyfish_search(query: str, api_key: Optional[str] = None,
                    timeout: int = 20) -> List[SearchResult]:
    """Search via TinyFish. Raises on failure so the caller can fall back."""
    global _last_tinyfish_search
    key = api_key or os.environ.get("TINYFISH_API_KEY")
    if not key:
        raise RuntimeError("no TINYFISH_API_KEY")
    # Free plan: 5 req/min -> min 12s spacing.
    wait = 12.0 - (time.time() - _last_tinyfish_search)
    if wait > 0:
        time.sleep(wait)
    resp = requests.get(
        _TINYFISH_SEARCH_URL,
        params={"query": query},
        headers={"X-API-Key": key, "User-Agent": _UA},
        timeout=timeout,
    )
    _last_tinyfish_search = time.time()
    resp.raise_for_status()
    data = resp.json()
    out = []
    for r in data.get("results", []) or []:
        url = (r.get("url") or "").strip()
        if not url.startswith("http"):
            continue
        out.append(SearchResult(
            title=(r.get("title") or "").strip(),
            url=url,
            snippet=(r.get("snippet") or "").strip(),
            site=r.get("site_name") or _domain(url),
            provider="tinyfish",
        ))
    return out


def duckduckgo_search(query: str, timeout: int = 20,
                      max_results: int = 10) -> List[SearchResult]:
    """Keyless search via DuckDuckGo HTML endpoint."""
    resp = requests.post(
        _DDG_HTML_URL,
        data={"q": query},
        headers={"User-Agent": _UA},
        timeout=timeout,
    )
    resp.raise_for_status()
    out = []
    # DDG html results: <a class="result__a" href="...">title</a> ... snippet
    for m in re.finditer(
        r'<a[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>'
        r'.*?<a[^>]*class="result__snippet"[^>]*>(.*?)</a>',
        resp.text, re.S,
    ):
        href, title_html, snip_html = m.groups()
        # DDG wraps in //duckduckgo.com/l/?uddg=<encoded>
        um = re.search(r"uddg=([^&]+)", href)
        url = um.group(1) if um else href
        try:
            from urllib.parse import unquote
            url = unquote(url)
        except Exception:
            pass
        if not url.startswith("http"):
            continue
        title = re.sub(r"<[^>]+>", "", title_html)
        snip = re.sub(r"<[^>]+>", "", snip_html)
        out.append(SearchResult(
            title=html_lib.unescape(title).strip(),
            url=url.strip(),
            snippet=html_lib.unescape(snip).strip(),
            site=_domain(url),
            provider="duckduckgo",
        ))
        if len(out) >= max_results:
            break
    if not out:
        raise RuntimeError("no results parsed from DuckDuckGo")
    return out


def search(query: str, max_results: int = 8) -> List[SearchResult]:
    """Search with automatic provider fallback. Never raises empty-handed
    without trying every provider; raises RuntimeError only if all fail."""
    errors = []
    try:
        results = tinyfish_search(query)
        if results:
            return results[:max_results]
    except Exception as exc:  # noqa: BLE001 - fallback is the point
        errors.append(f"tinyfish: {exc}")
        LOGGER.debug("TinyFish search failed, falling back: %s", exc)
    try:
        results = duckduckgo_search(query, max_results=max_results)
        if results:
            return results[:max_results]
    except Exception as exc:  # noqa: BLE001
        errors.append(f"duckduckgo: {exc}")
    raise RuntimeError("all search providers failed: " + " | ".join(errors))

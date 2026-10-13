"""Page fetching with automatic fallback.

Chain:
  1. TinyFish Fetch — JS-rendered, clean markdown (needs TINYFISH_API_KEY)
  2. requests + BeautifulSoup — keyless, readability-style extraction

TinyFish failed URLs are free (don't count against quota), so we try it
first whenever a key is present.
"""

from __future__ import annotations

import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import List, Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

LOGGER = logging.getLogger("webretriever.fetch")

_TINYFISH_FETCH_URL = "https://api.fetch.tinyfish.ai"
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

_last_tinyfish_fetch = 0.0

_SKIP_TAGS = {"script", "style", "noscript", "svg", "canvas", "iframe",
              "header", "footer", "nav", "aside", "form", "button"}


@dataclass
class PageLink:
    text: str
    url: str


@dataclass
class FetchedPage:
    url: str
    final_url: str = ""
    title: str = ""
    text: str = ""
    links: List[PageLink] = field(default_factory=list)
    provider: str = ""
    ok: bool = True
    error: str = ""
    raw_html: str = ""  # truncated raw HTML for JSON-LD/table extraction


def _absolutize(base: str, href: str) -> str:
    try:
        return urljoin(base, href.strip())
    except Exception:
        return ""


def tinyfish_fetch(urls: List[str], api_key: Optional[str] = None,
                   timeout: int = 60) -> List[FetchedPage]:
    """Fetch via TinyFish (JS-rendered markdown). Raises on failure."""
    global _last_tinyfish_fetch
    key = api_key or os.environ.get("TINYFISH_API_KEY")
    if not key:
        raise RuntimeError("no TINYFISH_API_KEY")
    # Free plan: 25 req/min -> min ~2.5s spacing.
    wait = 2.5 - (time.time() - _last_tinyfish_fetch)
    if wait > 0:
        time.sleep(wait)
    resp = requests.post(
        _TINYFISH_FETCH_URL,
        json={"urls": urls[:10]},
        headers={"X-API-Key": key, "Content-Type": "application/json",
                 "User-Agent": _UA},
        timeout=timeout,
    )
    _last_tinyfish_fetch = time.time()
    resp.raise_for_status()
    data = resp.json()
    pages = []
    for r in data.get("results", []) or []:
        pages.append(FetchedPage(
            url=r.get("url", ""),
            final_url=r.get("final_url", "") or r.get("url", ""),
            title=(r.get("title") or "").strip(),
            text=(r.get("text") or "").strip(),
            provider="tinyfish",
            ok=True,
        ))
    for e in data.get("errors", []) or []:
        pages.append(FetchedPage(url=e.get("url", ""), ok=False,
                                 error=str(e.get("error", "fetch failed")),
                                 provider="tinyfish"))
    return pages


def _readability_text(soup: BeautifulSoup) -> str:
    """Extract main content: prefer article/main, else largest text block."""
    for tag in soup(["script", "style", "noscript", "svg", "canvas",
                     "iframe", "footer", "nav", "aside", "form"]):
        tag.decompose()
    candidates = []
    for sel in ("article", "main", "[role=main]", ".content", "#content"):
        for el in soup.select(sel):
            t = el.get_text("\n", strip=True)
            if len(t) > 200:
                candidates.append(t)
    if candidates:
        return max(candidates, key=len)
    body = soup.body or soup
    return body.get_text("\n", strip=True)


def requests_fetch(url: str, timeout: int = 25) -> FetchedPage:
    """Keyless fetch with BeautifulSoup readability-style extraction."""
    try:
        resp = requests.get(url, headers={"User-Agent": _UA},
                            timeout=timeout, allow_redirects=True)
        resp.raise_for_status()
    except Exception as exc:
        return FetchedPage(url=url, ok=False, error=str(exc)[:200],
                            provider="requests")
    ctype = resp.headers.get("Content-Type", "")
    if "html" not in ctype and "text" not in ctype:
        return FetchedPage(url=url, ok=False,
                            error=f"non-HTML content: {ctype[:60]}",
                            provider="requests")
    soup = BeautifulSoup(resp.text, "lxml")
    title = ""
    if soup.title and soup.title.string:
        title = soup.title.string.strip()
    text = _readability_text(soup)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    links: List[PageLink] = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = _absolutize(url, a["href"])
        if not href.startswith("http") or href in seen:
            continue
        label = a.get_text(" ", strip=True)
        if len(label) < 3 or len(label) > 120:
            continue
        seen.add(href)
        links.append(PageLink(text=label, url=href))
        if len(links) >= 60:
            break
    return FetchedPage(url=url, final_url=resp.url, title=title,
                       text=text, links=links, provider="requests", ok=True,
                       raw_html=resp.text[:500_000])


def fetch_pages(urls: List[str], timeout: int = 25) -> List[FetchedPage]:
    """Fetch pages with automatic provider fallback per URL."""
    pages: List[FetchedPage] = []
    key = os.environ.get("TINYFISH_API_KEY")
    if key:
        try:
            tf_pages = tinyfish_fetch(urls, api_key=key)
            # TinyFish gives markdown but no link graph; enrich failures
            # via requests fallback below.
            for p in tf_pages:
                if p.ok and len(p.text) > 100:
                    pages.append(p)
                else:
                    fb = requests_fetch(p.url, timeout=timeout)
                    pages.append(fb if fb.ok else p)
            # Anything TinyFish didn't return at all -> fallback.
            returned = {p.url for p in tf_pages}
            for u in urls:
                if u not in returned:
                    pages.append(requests_fetch(u, timeout=timeout))
            return pages
        except Exception as exc:  # noqa: BLE001 - fallback is the point
            LOGGER.debug("TinyFish fetch failed, using requests: %s", exc)
    for u in urls:
        pages.append(requests_fetch(u, timeout=timeout))
    return pages

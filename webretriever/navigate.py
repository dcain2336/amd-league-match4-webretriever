"""Bounded multi-hop navigation.

Search results often land on index/category pages; the answer lives one or
two clicks deeper (product page -> specs tab, org homepage -> contact page).
This module fetches the top search hits, scores each page for answer
likelihood, and follows the most promising in-page links up to a fixed
budget. Same-domain links are preferred; the budget keeps us honest.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import List, Set
from urllib.parse import urlparse

from .providers.fetch import FetchedPage, fetch_pages
from .providers.search import SearchResult
from .understand import RetrievalPlan

LOGGER = logging.getLogger("webretriever.navigate")

MAX_PAGES = 8       # total page budget per request
MAX_HOPS = 2        # link-following depth beyond search results
INITIAL_FETCH = 4   # search hits fetched in round one


@dataclass
class ScoredPage:
    page: FetchedPage
    score: float
    hop: int = 0


def _domain(url: str) -> str:
    return urlparse(url).netloc.lower().removeprefix("www.")


def _keyword_hits(text: str, keywords: List[str]) -> int:
    low = text.lower()
    return sum(1 for k in keywords if k.lower() in low)


def score_page(page: FetchedPage, plan: RetrievalPlan) -> float:
    """Heuristic: does this page look like it contains the answer?"""
    if not page.ok or len(page.text) < 150:
        return 0.0
    text = page.text
    score = 0.0
    # Entity mentions are the strongest signal.
    score += 3.0 * _keyword_hits(text[:4000], plan.entities)
    score += 1.0 * _keyword_hits(text, [w for w in plan.queries[0].split()][:8]
                                 if plan.queries else [])
    # Intent-specific signals.
    low = text.lower()
    if plan.intent == "price" and re.search(r"\$\s?[\d,]+(\.\d{2})?|\bUSD\b", text):
        score += 4.0
    if plan.intent == "contact" and re.search(
            r"(\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}|[\w.+-]+@[\w-]+\.[\w.]+",
            text):
        score += 4.0
    if plan.intent == "hours" and re.search(
            r"\b(mon|tue|wed|thu|fri|sat|sun)[a-z]*\b.{0,20}\d{1,2}(:\d{2})?\s?(am|pm)",
            low):
        score += 4.0
    if plan.intent == "date" and re.search(
            r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{1,2},?\s+\d{4}\b",
            low):
        score += 3.0
    # Thin pages are rarely the answer.
    if len(text) < 600:
        score *= 0.5
    return score


_NAV_HINTS = re.compile(
    r"spec|detail|pricing|price|contact|about|support|faq|manual|docs?|"
    r"product|service|feature|overview", re.I)


def _rank_links(page: FetchedPage, plan: RetrievalPlan,
                seen: Set[str]) -> List[str]:
    base_dom = _domain(page.final_url or page.url)
    scored = []
    for link in page.links:
        if link.url in seen:
            continue
        if not link.url.startswith("http"):
            continue
        s = 0.0
        if _domain(link.url) == base_dom:
            s += 2.0
        if _NAV_HINTS.search(link.text) or _NAV_HINTS.search(link.url):
            s += 2.0
        s += 0.5 * _keyword_hits(link.text, plan.entities)
        if s > 0:
            scored.append((s, link.url))
    scored.sort(reverse=True)
    return [u for _, u in scored[:6]]


def gather_evidence(results: List[SearchResult],
                    plan: RetrievalPlan) -> List[ScoredPage]:
    """Fetch, score, and optionally follow links. Returns scored pages."""
    seen: Set[str] = set()
    scored: List[ScoredPage] = []

    def _fetch(urls: List[str], hop: int):
        fresh = [u for u in urls if u not in seen]
        if not fresh:
            return []
        seen.update(fresh)
        pages = fetch_pages(fresh)
        out = []
        for p in pages:
            out.append(ScoredPage(page=p, score=score_page(p, plan), hop=hop))
        return out

    # Round 1: top search hits.
    first_urls = [r.url for r in results[:INITIAL_FETCH]]
    scored.extend(_fetch(first_urls, hop=0))

    # Rounds 2..MAX_HOPS: follow promising links from low-scoring pages.
    for hop in range(1, MAX_HOPS + 1):
        if len(seen) >= MAX_PAGES:
            break
        # Follow links from the best pages we have that still look thin.
        cands = sorted(scored, key=lambda s: s.score, reverse=True)[:3]
        next_urls: List[str] = []
        for c in cands:
            if c.score < 6.0:  # only dig deeper when the page looks thin
                next_urls.extend(_rank_links(c.page, plan, seen))
            if len(seen) + len(next_urls) >= MAX_PAGES:
                break
        new = _fetch(next_urls[: MAX_PAGES - len(seen)], hop=hop)
        if not new:
            break
        scored.extend(new)

    scored.sort(key=lambda s: s.score, reverse=True)
    LOGGER.debug("gathered %d pages", len(scored))
    return scored

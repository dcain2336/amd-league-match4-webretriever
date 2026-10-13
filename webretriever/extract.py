"""Structure-aware answer extraction.

Pulls candidate answers from a page using, in order:
  1. JSON-LD structured data (Product, Organization, FAQPage, ...)
  2. Intent-specific patterns (price, phone, email, hours, dates)
  3. HTML tables (spec sheets love tables)
  4. Ranked text spans around entity/keyword mentions

Every candidate carries the exact source URL and a snippet of evidence.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Dict, List

from bs4 import BeautifulSoup

from .providers.fetch import FetchedPage
from .understand import RetrievalPlan

LOGGER = logging.getLogger("webretriever.extract")


@dataclass
class Candidate:
    value: str
    evidence: str
    source_url: str
    source_title: str = ""
    method: str = ""          # jsonld | pattern | table | span
    score: float = 0.0


_PRICE_RE = re.compile(r"\$\s?[\d,]+(?:\.\d{2})?|\bUSD\s?[\d,]+(?:\.\d{2})?")
_PHONE_RE = re.compile(r"(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}")
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]{2,}")
_HOURS_RE = re.compile(
    r"\b((?:mon|tue|wed|thu|fri|sat|sun)[a-z]*(?:\s*[-–]\s*(?:mon|tue|wed|thu|fri|sat|sun)[a-z]*)?"
    r"\s*:?\s*\d{1,2}(?::\d{2})?\s*(?:am|pm)?\s*(?:[-–]|to)\s*\d{1,2}(?::\d{2})?\s*(?:am|pm))",
    re.I)
_DATE_RE = re.compile(
    r"\b((?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{1,2},?\s+\d{4}"
    r"|\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{4})\b", re.I)


def candidates_from_html(html: str, page: FetchedPage,
                         plan: RetrievalPlan) -> List[Candidate]:
    """Extract candidates using the raw HTML (JSON-LD + tables)."""
    out: List[Candidate] = []
    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:
        return out

    # --- JSON-LD ---
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
        except Exception:
            continue
        items = data if isinstance(data, list) else [data]
        for item in items:
            if not isinstance(item, dict):
                continue
            t = str(item.get("@type", ""))
            flat = json.dumps(item)
            if plan.intent == "price":
                offers = item.get("offers", {})
                if isinstance(offers, dict):
                    price = offers.get("price")
                    if price:
                        out.append(Candidate(
                            value=f"${offers.get('price')} {offers.get('priceCurrency', '')}".strip(),
                            evidence=flat[:400], source_url=page.final_url or page.url,
                            source_title=page.title, method="jsonld", score=9.0))
            if plan.intent == "contact":
                for key in ("telephone", "email"):
                    if item.get(key):
                        out.append(Candidate(
                            value=str(item[key]), evidence=flat[:400],
                            source_url=page.final_url or page.url,
                            source_title=page.title, method="jsonld", score=9.0))
            if "FAQPage" in t or "QAPage" in t:
                for ent in (item.get("mainEntity") or []):
                    if isinstance(ent, dict):
                        q = (ent.get("name") or "")
                        a = ent.get("acceptedAnswer", {})
                        if isinstance(a, dict) and a.get("text"):
                            out.append(Candidate(
                                value=_clean(a["text"])[:500], evidence=q[:200],
                                source_url=page.final_url or page.url,
                                source_title=page.title, method="jsonld", score=7.0))

    # --- Tables (spec sheets) ---
    if plan.intent in ("spec", "fact", "price"):
        for table in soup.find_all("table"):
            rows = []
            for tr in table.find_all("tr"):
                cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
                if any(cells):
                    rows.append(cells)
            if not rows:
                continue
            text_blob = " | ".join(" ".join(r) for r in rows[:12])
            hits = sum(1 for e in plan.entities if e.lower() in text_blob.lower())
            if hits or any(k.lower() in text_blob.lower()
                           for k in plan.queries[0].split()[:6] if plan.queries):
                for r in rows:
                    if len(r) >= 2 and len(" ".join(r)) < 300:
                        out.append(Candidate(
                            value=": ".join(r[:2]), evidence=text_blob[:400],
                            source_url=page.final_url or page.url,
                            source_title=page.title, method="table", score=6.0 + hits))
    return out


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def pattern_candidates(page: FetchedPage,
                       plan: RetrievalPlan) -> List[Candidate]:
    """Intent-specific regex extraction from page text."""
    out: List[Candidate] = []
    text = page.text
    url = page.final_url or page.url

    def add(pattern, intent_match: str, score: float, clean_fn=None):
        if plan.intent != intent_match:
            return
        for m in pattern.finditer(text):
            v = _clean(m.group(1) if m.groups() else m.group(0))
            if clean_fn:
                v = clean_fn(v)
            if len(v) > 200:
                continue
            start = max(0, m.start() - 120)
            out.append(Candidate(value=v,
                                 evidence=_clean(text[start:m.end() + 120])[:400],
                                 source_url=url, source_title=page.title,
                                 method="pattern", score=score))

    add(_PRICE_RE, "price", 8.0)
    add(_PHONE_RE, "contact", 8.0)
    add(_EMAIL_RE, "contact", 7.5)
    add(_HOURS_RE, "hours", 8.0)
    add(_DATE_RE, "date", 7.5)
    return out


def span_candidates(page: FetchedPage, plan: RetrievalPlan,
                    max_spans: int = 6) -> List[Candidate]:
    """Ranked sentences/paragraphs around entity mentions."""
    out: List[Candidate] = []
    url = page.final_url or page.url
    paras = [p.strip() for p in re.split(r"\n+", page.text) if len(p.strip()) > 40]
    terms = [e.lower() for e in plan.entities] + \
            [w.lower() for w in (plan.queries[0].split()[:8] if plan.queries else [])]
    for para in paras[:80]:
        low = para.lower()
        hits = sum(1 for t in terms if t in low)
        if hits == 0:
            continue
        # Penalize nav-ish boilerplate.
        if re.search(r"cookie|subscribe|newsletter|sign up|all rights reserved", low):
            continue
        # For definition intent prefer "X is ..." sentences.
        score = 3.0 + hits
        if plan.intent == "definition" and re.search(r"\bis\b|\bare\b|\brefers to\b", low):
            score += 2.0
        sentences = re.split(r"(?<=[.!?])\s+", para)
        best = max(sentences, key=lambda s: sum(1 for t in terms if t in s.lower()),
                   default=para)
        out.append(Candidate(value=_clean(best)[:600],
                             evidence=_clean(para)[:400],
                             source_url=url, source_title=page.title,
                             method="span", score=min(score, 8.0)))
        if len(out) >= max_spans:
            break
    return out


def extract_candidates(page: FetchedPage, plan: RetrievalPlan) -> List[Candidate]:
    """All extraction methods, de-duplicated, best first."""
    cands: List[Candidate] = []
    if page.raw_html:
        cands.extend(candidates_from_html(page.raw_html, page, plan))
    cands.extend(pattern_candidates(page, plan))
    cands.extend(span_candidates(page, plan))
    # De-dupe by normalized value, keep highest score.
    best: Dict[str, Candidate] = {}
    for c in cands:
        key = re.sub(r"\s+", " ", c.value.lower()).strip()
        if not key or len(key) < 2:
            continue
        if key not in best or c.score > best[key].score:
            best[key] = c
    return sorted(best.values(), key=lambda c: c.score, reverse=True)

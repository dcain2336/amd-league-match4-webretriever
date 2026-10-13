"""Evidence verification: ground every answer in its sources.

Rules:
  - A candidate is *supported* if its value (or its key tokens) appears in
    the evidence text from its own source page.
  - Confidence rises with independent multi-source agreement.
  - If nothing is supported, the agent refuses honestly instead of guessing.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import List
from urllib.parse import urlparse

from .extract import Candidate

LOGGER = logging.getLogger("webretriever.verify")


@dataclass
class VerifiedAnswer:
    answer: str
    citations: List[str] = field(default_factory=list)
    confidence: float = 0.0            # 0..1
    evidence: List[str] = field(default_factory=list)
    verified: bool = False
    refused: bool = False
    refusal_reason: str = ""
    method: str = ""
    sources_checked: int = 0


def _tokens(s: str) -> List[str]:
    return [t for t in re.findall(r"[A-Za-z0-9$.,/-]+", s.lower()) if len(t) > 2]


def _domain(url: str) -> str:
    return urlparse(url).netloc.lower().removeprefix("www.")


def is_supported(c: Candidate) -> bool:
    """Does the candidate's value trace back to its evidence?"""
    val_tokens = _tokens(c.value)
    ev_low = c.evidence.lower()
    if not val_tokens:
        return False
    # For short factual values (prices, phones, dates): near-verbatim match.
    if len(val_tokens) <= 6:
        hits = sum(1 for t in val_tokens if t in ev_low)
        return hits / len(val_tokens) >= 0.6
    # For longer spans: majority of distinctive tokens present.
    hits = sum(1 for t in val_tokens if t in ev_low)
    return hits / len(val_tokens) >= 0.5


def _normalize_value(v: str) -> str:
    v = v.lower().strip()
    v = re.sub(r"[\s,]+", " ", v)
    return v


def verify(candidates: List[Candidate],
           sources_checked: int) -> VerifiedAnswer:
    supported = [c for c in candidates if is_supported(c)]
    if not supported:
        return VerifiedAnswer(
            answer="", verified=False, refused=True,
            refusal_reason=(
                "No verifiable answer found. The retrieved pages did not "
                "contain a fact matching the request that could be traced "
                "to a source. Try rephrasing or narrowing the request."
            ),
            sources_checked=sources_checked,
        )

    # Group near-identical values across independent domains.
    groups: List[List[Candidate]] = []
    for c in supported:
        key = _normalize_value(c.value)
        placed = False
        for g in groups:
            gkey = _normalize_value(g[0].value)
            if key == gkey or (len(key) > 8 and (key in gkey or gkey in key)):
                g.append(c)
                placed = True
                break
        if not placed:
            groups.append([c])

    def group_score(g: List[Candidate]) -> float:
        domains = {_domain(c.source_url) for c in g}
        base = max(c.score for c in g)
        # Independent corroboration is the strongest trust signal.
        return base + 3.0 * (len(domains) - 1) + 0.5 * (len(g) - 1)

    groups.sort(key=group_score, reverse=True)
    best = groups[0]
    domains = {_domain(c.source_url) for c in best}
    top = max(best, key=lambda c: c.score)

    # Confidence: method strength + corroboration, capped.
    conf = 0.45
    if top.method in ("jsonld", "pattern"):
        conf += 0.15
    if len(domains) >= 2:
        conf += 0.25
    elif len(best) >= 2:
        conf += 0.10
    if len(top.evidence) > 120:
        conf += 0.05
    conf = min(conf, 0.95)

    citations = []
    for c in best:
        if c.source_url not in citations:
            citations.append(c.source_url)

    return VerifiedAnswer(
        answer=top.value,
        citations=citations[:5],
        confidence=round(conf, 2),
        evidence=[c.evidence for c in best[:3]],
        verified=True,
        refused=False,
        method=top.method,
        sources_checked=sources_checked,
    )

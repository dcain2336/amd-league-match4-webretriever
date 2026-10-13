"""Orchestrator: the full retrieval pipeline in one call."""

from __future__ import annotations

import logging
import time
from dataclasses import asdict, dataclass, field
from typing import List

from .extract import Candidate, extract_candidates
from .navigate import gather_evidence
from .providers.search import SearchResult, search
from .understand import RetrievalPlan, plan_request
from .verify import VerifiedAnswer, verify

LOGGER = logging.getLogger("webretriever")


@dataclass
class RetrievalReport:
    request: str
    plan: dict = field(default_factory=dict)
    answer: str = ""
    citations: List[str] = field(default_factory=list)
    confidence: float = 0.0
    verified: bool = False
    refused: bool = False
    refusal_reason: str = ""
    evidence: List[str] = field(default_factory=list)
    method: str = ""
    sources_checked: int = 0
    search_queries_used: List[str] = field(default_factory=list)
    elapsed_s: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


def retrieve(request: str, max_search_queries: int = 2) -> RetrievalReport:
    """Run the full pipeline for a natural-language request."""
    t0 = time.time()
    plan: RetrievalPlan = plan_request(request)
    report = RetrievalReport(request=request)
    report.plan = {
        "intent": plan.intent,
        "entities": plan.entities,
        "target": plan.target,
    }

    # --- Search (try query variants until one yields results) ---
    results: List[SearchResult] = []
    for q in plan.queries[:max_search_queries]:
        try:
            results = search(q)
            if results:
                report.search_queries_used.append(q)
                break
        except Exception as exc:  # noqa: BLE001 - next query variant
            LOGGER.debug("search failed for %r: %s", q, exc)
    if not results:
        report.refused = True
        report.refusal_reason = (
            "Web search returned no usable results for this request. "
            "Check your network connection or try different wording."
        )
        report.elapsed_s = round(time.time() - t0, 1)
        return report

    # --- Fetch + navigate ---
    scored = gather_evidence(results, plan)
    pages_ok = [s for s in scored if s.page.ok]
    report.sources_checked = len(pages_ok)
    if not pages_ok:
        report.refused = True
        report.refusal_reason = (
            "Found candidate pages but none could be fetched. "
            "The sites may be blocking automated access."
        )
        report.elapsed_s = round(time.time() - t0, 1)
        return report

    # --- Extract candidates from the best pages ---
    candidates: List[Candidate] = []
    for s in scored[:6]:
        try:
            candidates.extend(extract_candidates(s.page, plan))
        except Exception as exc:  # noqa: BLE001 - one bad page shouldn't kill it
            LOGGER.debug("extraction failed for %s: %s", s.page.url, exc)

    # --- Verify + synthesize ---
    verdict: VerifiedAnswer = verify(candidates, report.sources_checked)
    report.answer = verdict.answer
    report.citations = verdict.citations
    report.confidence = verdict.confidence
    report.verified = verdict.verified
    report.refused = verdict.refused
    report.refusal_reason = verdict.refusal_reason
    report.evidence = verdict.evidence
    report.method = verdict.method
    report.elapsed_s = round(time.time() - t0, 1)
    return report

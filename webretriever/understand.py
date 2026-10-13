"""Query understanding: turn a natural-language request into a retrieval plan.

Deterministic and dependency-free. Produces:
  - intent: one of fact, price, contact, hours, spec, definition, howto, list, other
  - entities: quoted strings + salient noun phrases
  - target: what kind of value the user wants back
  - queries: 2-4 search query variants, best first
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List

_STOPWORDS = frozenset("""
a an the and or but of to in on for with is are was were be been being
what which who whom whose where when why how do does did can could should
would will shall may might must i me my we us our you your he him his she
her it its they them their this that these those there here than then so as
at by from into about over after before between under again once any all
each few more most other some such no nor not only own same too very just
find get give tell show me please
""".split())

_QUESTION_LEADS = (
    "what is", "what are", "what was", "what were", "who is", "who are",
    "where is", "where are", "when is", "when does", "when did",
    "how much", "how many", "how do", "how does", "how to",
    "is there", "are there", "does", "do", "can you", "could you",
    "tell me", "show me", "find", "find me", "get me", "give me",
    "please",
)

_INTENT_PATTERNS = [
    ("price", re.compile(r"\b(price|cost|how much|pricing|msrp|retail|fee|rates?|fare)\b", re.I)),
    ("contact", re.compile(r"\b(phone|telephone|email|e-mail|contact|address|location|directions|fax)\b", re.I)),
    ("hours", re.compile(r"\b(hours|open|close|opening|closing|schedule|timetable)\b", re.I)),
    ("spec", re.compile(r"\b(spec|specs|specification|dimensions|weight|size|capacity|model|version|features?)\b", re.I)),
    ("definition", re.compile(r"^\s*(what is|what are|define|meaning of|definition of)\b", re.I)),
    ("howto", re.compile(r"\b(how (do|does|to|can)|steps?|instructions?|guide|tutorial)\b", re.I)),
    ("list", re.compile(r"\b(list|top \d+|best|compare|comparison|versus|vs\.?)\b", re.I)),
    ("date", re.compile(r"\b(when|date|deadline|released?|announced?|founded)\b", re.I)),
]


@dataclass
class RetrievalPlan:
    original: str
    intent: str
    entities: List[str] = field(default_factory=list)
    target: str = ""
    queries: List[str] = field(default_factory=list)


def _strip_question_lead(text: str) -> str:
    t = text.strip()
    low = t.lower()
    for lead in sorted(_QUESTION_LEADS, key=len, reverse=True):
        if low.startswith(lead):
            t = t[len(lead):].strip(" ?.,;:")
            low = t.lower()
    return t


def _detect_intent(text: str) -> str:
    for intent, pat in _INTENT_PATTERNS:
        if pat.search(text):
            return intent
    return "fact"


def _extract_entities(text: str) -> List[str]:
    entities: List[str] = []
    # Quoted strings are almost always entities.
    for m in re.finditer(r'"([^"]{2,80})"|\'([^\']{2,80})\'', text):
        entities.append(m.group(1) or m.group(2))
    # Capitalized phrases (2+ words) — proper nouns.
    core = _strip_question_lead(text)
    for m in re.finditer(r"\b([A-Z][\w&'.-]{1,30}(?:\s+[A-Z][\w&'.-]{1,30}){1,4})\b", core):
        phrase = m.group(1).strip()
        if phrase.lower() not in _STOPWORDS and phrase not in entities:
            entities.append(phrase)
    # Version / model tokens like "v4", "RTX 5080", "iPhone 17".
    for m in re.finditer(r"\b([A-Z]{1,4}[- ]?\d[\w.-]*)\b", core):
        tok = m.group(1)
        if tok not in entities:
            entities.append(tok)
    return entities[:6]


def _keywords(text: str) -> List[str]:
    core = _strip_question_lead(text)
    words = re.findall(r"[A-Za-z][\w'.-]*", core.lower())
    seen, out = set(), []
    for w in words:
        w = w.strip("'.-")
        if len(w) > 2 and w not in _STOPWORDS and w not in seen:
            seen.add(w)
            out.append(w)
    return out


def _target_for(intent: str) -> str:
    return {
        "price": "a price or cost figure",
        "contact": "contact details (phone, email, address)",
        "hours": "opening hours or schedule",
        "spec": "a specification value",
        "definition": "a concise definition",
        "howto": "step-by-step instructions",
        "list": "a list of items",
        "date": "a date",
        "fact": "a specific fact",
    }.get(intent, "a specific fact")


def plan_request(request: str) -> RetrievalPlan:
    """Build a retrieval plan from a natural-language request."""
    request = " ".join(request.split())
    intent = _detect_intent(request)
    entities = _extract_entities(request)
    keywords = _keywords(request)

    queries: List[str] = []
    base = " ".join(keywords)
    if entities:
        # Entity-first query usually has the highest precision.
        queries.append(" ".join(entities) + (" " + base if base else ""))
    if base and base not in queries:
        queries.append(base)
    # Intent-flavored variant helps for price/contact/hours style asks.
    flavor = {
        "price": "price", "contact": "contact",
        "hours": "hours", "spec": "specifications",
        "date": "date", "howto": "how to",
    }.get(intent)
    if flavor and base and flavor not in base.lower():
        queries.append(f"{base} {flavor}")
    # Fallback: the raw request minus politeness.
    stripped = _strip_question_lead(request)
    if stripped and stripped not in queries:
        queries.append(stripped)

    # De-dupe, cap at 4.
    seen, uniq = set(), []
    for q in queries:
        ql = q.lower()
        if ql not in seen and q.strip():
            seen.add(ql)
            uniq.append(q.strip())
    return RetrievalPlan(
        original=request,
        intent=intent,
        entities=entities,
        target=_target_for(intent),
        queries=uniq[:4],
    )

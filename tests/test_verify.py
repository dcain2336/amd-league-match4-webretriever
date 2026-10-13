"""Unit tests for extraction + verification (no network needed)."""

from webretriever.extract import Candidate
from webretriever.understand import plan_request
from webretriever.verify import is_supported, verify


def _cand(value, evidence, url="https://example.com/p", method="pattern", score=8.0):
    return Candidate(value=value, evidence=evidence, source_url=url,
                     source_title="Example", method=method, score=score)


def test_supported_short_value():
    c = _cand("$499.99", "The Sony WH-1000XM5 is on sale for $499.99 today only.")
    assert is_supported(c)


def test_unsupported_value():
    c = _cand("$499.99", "We sell many headphones at great prices every day.")
    assert not is_supported(c)


def test_multi_source_agreement_boosts_confidence():
    plan = plan_request("price of widget")
    c1 = _cand("$19.99", "widget costs $19.99 at our store", url="https://a.com/x")
    c2 = _cand("$19.99", "get the widget for $19.99", url="https://b.com/y")
    v = verify([c1, c2], sources_checked=2)
    assert v.verified and not v.refused
    assert v.answer == "$19.99"
    assert len(v.citations) == 2
    assert v.confidence >= 0.7


def test_refusal_when_nothing_supported():
    c = _cand("$19.99", "completely unrelated text about weather patterns")
    v = verify([c], sources_checked=1)
    assert v.refused and not v.verified
    assert v.refusal_reason


def test_best_group_wins():
    c1 = _cand("$19.99", "widget is $19.99 here", url="https://a.com", score=8.0)
    c2 = _cand("$24.99", "widget costs $24.99", url="https://b.com", score=5.0)
    v = verify([c1, c2], sources_checked=2)
    assert v.answer == "$19.99"

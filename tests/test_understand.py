"""Unit tests for query understanding (no network needed)."""

from webretriever.understand import plan_request


def test_price_intent():
    p = plan_request("What is the price of the Sony WH-1000XM5?")
    assert p.intent == "price"
    assert any("Sony" in e for e in p.entities)
    assert p.queries, "should produce search queries"


def test_contact_intent():
    p = plan_request("What is the phone number for Domino's Pizza in Jacksonville NC?")
    assert p.intent == "contact"


def test_hours_intent():
    p = plan_request("When does the DMV open on Saturdays?")
    assert p.intent == "hours"


def test_definition_intent():
    p = plan_request("What is retrieval-augmented generation?")
    assert p.intent == "definition"


def test_quoted_entity():
    p = plan_request('Find the release date of "Dune Messiah" movie')
    assert "Dune Messiah" in p.entities


def test_query_variants_capped():
    p = plan_request("How much does an AMD Ryzen 9 9950X cost right now?")
    assert 1 <= len(p.queries) <= 4
    assert p.intent == "price"


def test_empty_safe():
    p = plan_request("  ")
    assert isinstance(p.queries, list)

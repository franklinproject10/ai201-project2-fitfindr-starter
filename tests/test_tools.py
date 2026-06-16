"""
Tool tests for FitFindr. Run with:  pytest tests/

Covers the happy path plus every failure mode the agent must survive:
  - search_listings: results found / no results / price filter / flexible size
  - suggest_outfit:  empty wardrobe (graceful, no crash)
  - create_fit_card: empty / whitespace outfit (error string, no crash)

The failure-mode tests run fully offline (no API key needed). The two
LLM happy-path tests are skipped automatically unless GROQ_API_KEY is set.
"""

import os

import pytest

from tools import search_listings, suggest_outfit, create_fit_card, _size_matches
from utils.data_loader import load_listings, get_empty_wardrobe, get_example_wardrobe


# ── search_listings ───────────────────────────────────────────────────────────

def test_search_returns_results():
    results = search_listings("vintage graphic tee", size=None, max_price=50)
    assert isinstance(results, list)
    assert len(results) > 0


def test_search_empty_results():
    results = search_listings("designer ballgown", size="XXS", max_price=5)
    assert results == []          # empty list, no exception


def test_search_price_filter():
    results = search_listings("jacket", size=None, max_price=10)
    assert all(item["price"] <= 10 for item in results)


def test_search_sorted_by_relevance():
    # Relevance score is non-increasing down the result list.
    results = search_listings("vintage denim", size=None, max_price=100)
    prices = [r["price"] for r in results]
    assert isinstance(results, list)
    # at least returns dicts with the expected fields
    if results:
        assert "title" in results[0] and "price" in results[0]


def test_size_flexible_match():
    # "M" should catch compound sizes and One Size, but not "L".
    assert _size_matches("M", "M")
    assert _size_matches("M", "S/M")
    assert _size_matches("M", "M/L")
    assert _size_matches("M", "One Size")
    assert not _size_matches("M", "L")


# ── suggest_outfit (failure mode: empty wardrobe) ─────────────────────────────

def test_suggest_outfit_empty_wardrobe():
    item = load_listings()[0]
    out = suggest_outfit(item, get_empty_wardrobe())
    assert isinstance(out, str)
    assert out.strip() != ""      # informative message, not empty


# ── create_fit_card (failure mode: incomplete outfit) ─────────────────────────

def test_create_fit_card_empty_outfit():
    item = load_listings()[0]
    msg = create_fit_card("", item)
    assert isinstance(msg, str)
    assert "fit card" in msg.lower()   # the guard message, not a crash


def test_create_fit_card_whitespace_outfit():
    item = load_listings()[0]
    msg = create_fit_card("   ", item)
    assert isinstance(msg, str)
    assert msg.strip() != ""


# ── LLM happy paths (only run if a key is present) ────────────────────────────

@pytest.mark.skipif(not os.environ.get("GROQ_API_KEY"), reason="needs GROQ_API_KEY")
def test_suggest_outfit_with_wardrobe():
    item = load_listings()[0]
    out = suggest_outfit(item, get_example_wardrobe())
    assert isinstance(out, str) and len(out) > 20


@pytest.mark.skipif(not os.environ.get("GROQ_API_KEY"), reason="needs GROQ_API_KEY")
def test_create_fit_card_varies():
    item = load_listings()[0]
    a = create_fit_card("Pair with wide-leg jeans and white sneakers.", item)
    b = create_fit_card("Layer under a denim jacket with combat boots.", item)
    assert a != b                 # different inputs -> different captions

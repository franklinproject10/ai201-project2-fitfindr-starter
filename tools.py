"""
tools.py

The three required FitFindr tools. Each tool is a standalone function that
can be called and tested independently before being wired into the agent loop.

Complete and test each tool before moving to agent.py.

Tools:
    search_listings(description, size, max_price)  → list[dict]
    suggest_outfit(new_item, wardrobe)              → str
    create_fit_card(outfit, new_item)               → str
"""

import os
import re

from dotenv import load_dotenv
from groq import Groq

from utils.data_loader import load_listings

load_dotenv()

MODEL = "llama-3.3-70b-versatile"


# ── Groq client ───────────────────────────────────────────────────────────────

def _get_groq_client():
    """Initialize and return a Groq client using GROQ_API_KEY from .env."""
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise ValueError(
            "GROQ_API_KEY not set. Add it to a .env file in the project root."
        )
    return Groq(api_key=api_key)


# ── Tool 1: search_listings ───────────────────────────────────────────────────

def search_listings(
    description: str,
    size: str | None = None,
    max_price: float | None = None,
) -> list[dict]:
    """
    Search the mock listings dataset for items matching the description,
    optional size, and optional price ceiling.

    Args:
        description: Keywords describing what the user is looking for
                     (e.g., "vintage graphic tee").
        size:        Size string to filter by, or None to skip size filtering.
                     Matching is case-insensitive (e.g., "M" matches "S/M").
        max_price:   Maximum price (inclusive), or None to skip price filtering.

    Returns:
        A list of matching listing dicts, sorted by relevance (best match first).
        Returns an empty list if nothing matches — does NOT raise an exception.

    Each listing dict has the following fields:
        id, title, description, category, style_tags (list), size,
        condition, price (float), colors (list), brand, platform
    """
    listings = load_listings()

    # 1. Tokenize the description into lowercase keywords.
    desc_words = [w for w in re.split(r"[^a-z0-9]+", (description or "").lower()) if w]

    scored = []
    for item in listings:
        # 2a. Price filter (skipped if max_price is None).
        if max_price is not None and item["price"] > max_price:
            continue
        # 2b. Size filter (skipped if size is None).
        if size is not None and not _size_matches(size, item["size"]):
            continue
        # 3. Score by keyword overlap with the searchable text.
        score = _relevance(desc_words, item)
        # 4. Drop anything with no relevant match.
        if score == 0:
            continue
        scored.append((score, item["price"], item))

    # 5. Sort by score (desc), then price (asc) as a tiebreak.
    scored.sort(key=lambda t: (-t[0], t[1]))
    return [item for _score, _price, item in scored]


def _size_matches(requested: str, listing_size: str) -> bool:
    """Flexible, case-insensitive size match.

    "M" matches "M", "S/M", "M/L"; "One Size" listings match any request.
    Token-based (splits on spaces and slashes) so single letters don't
    accidentally substring-match unrelated words.
    """
    req = (requested or "").strip().lower()
    ls = (listing_size or "").strip().lower()
    if not req:
        return True
    if "one size" in ls:
        return True
    if req == ls:
        return True
    tokens = [t for t in re.split(r"[\s/]+", ls) if t]
    return req in tokens


def _relevance(desc_words: list[str], item: dict) -> int:
    """Count how many description keywords appear in the listing's text."""
    haystack = " ".join([
        item.get("title", ""),
        item.get("description", ""),
        " ".join(item.get("style_tags", [])),
        item.get("category", ""),
        " ".join(item.get("colors", [])),
        item.get("brand") or "",
    ]).lower()
    return sum(1 for w in desc_words if w in haystack)


# ── Tool 2: suggest_outfit ────────────────────────────────────────────────────

def suggest_outfit(new_item: dict, wardrobe: dict) -> str:
    """
    Given a thrifted item and the user's wardrobe, suggest 1–2 complete outfits.

    Args:
        new_item: A listing dict (the item the user is considering buying).
        wardrobe: A wardrobe dict with an 'items' key containing a list of
                  wardrobe item dicts. May be empty — handle this gracefully.

    Returns:
        A non-empty string with outfit suggestions.
        If the wardrobe is empty, offer general styling advice for the item
        rather than raising an exception or returning an empty string.
    """
    items = (wardrobe or {}).get("items", [])
    title = new_item.get("title", "this piece")
    category = new_item.get("category", "item")
    tags = ", ".join(new_item.get("style_tags", [])) or "versatile"

    # 1–2. Empty wardrobe: return deterministic general styling (no LLM call).
    #      This keeps the failure mode fast, offline-testable, and crash-proof.
    if not items:
        return (
            f"Your closet is empty, so here's a general starting point for the {title}. "
            f"It reads as {tags}. Build around it with a few staples: a plain fitted top, "
            f"a pair of straight or wide-leg jeans, and clean neutral sneakers or boots. "
            f"Let this {category} be the statement piece and keep everything else simple. "
            f"Add items to your wardrobe and I can suggest specific pairings next time."
        )

    # 3. Non-empty wardrobe: ask the LLM for specific, named combinations.
    wardrobe_lines = "\n".join(
        f"- {w.get('name', '?')} ({w.get('category', '?')}; "
        f"colors: {', '.join(w.get('colors', []))}; "
        f"tags: {', '.join(w.get('style_tags', []))})"
        for w in items
    )
    prompt = (
        "A user is considering buying this thrifted item:\n"
        f"  Title: {title}\n"
        f"  Category: {category}\n"
        f"  Colors: {', '.join(new_item.get('colors', []))}\n"
        f"  Style tags: {tags}\n\n"
        f"Their current wardrobe:\n{wardrobe_lines}\n\n"
        "Suggest 1-2 complete outfits that pair the new item with SPECIFIC pieces "
        "from their wardrobe, naming those pieces. Add one concrete styling tip "
        "(how to wear, layer, or roll it). 2-4 sentences, casual and practical. "
        "Do not invent items they do not own."
    )

    # 4. Call the LLM; never raise — fall back to a safe string on error.
    try:
        client = _get_groq_client()
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": "You are a sharp, practical personal stylist."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.7,
        )
        text = (resp.choices[0].message.content or "").strip()
        return text or f"Pair the {title} with neutral basics and let it carry the look."
    except Exception as exc:
        return (
            f"Couldn't reach the styling model ({exc.__class__.__name__}). "
            f"As a fallback, pair the {title} with neutral wardrobe basics and let it "
            f"be the statement piece."
        )


# ── Tool 3: create_fit_card ───────────────────────────────────────────────────

def create_fit_card(outfit: str, new_item: dict) -> str:
    """
    Generate a short, shareable outfit caption for the thrifted find.

    Args:
        outfit:   The outfit suggestion string from suggest_outfit().
        new_item: The listing dict for the thrifted item.

    Returns:
        A 2–4 sentence string usable as an Instagram/TikTok caption.
        If outfit is empty or missing, return a descriptive error message
        string — do NOT raise an exception.
    """
    # 1. Guard against an empty / whitespace-only outfit.
    if not outfit or not outfit.strip():
        return "Couldn't generate a fit card — the outfit suggestion was empty or missing."

    title = new_item.get("title", "this find")
    price = new_item.get("price")
    platform = new_item.get("platform", "")
    brand = new_item.get("brand")  # may be None — omit rather than print "None"

    item_line = f"Item: {title}"
    if brand:
        item_line += f" by {brand}"
    if price is not None:
        item_line += f", ${price:g}"
    if platform:
        item_line += f", from {platform}"

    # 2. Build the caption prompt.
    prompt = (
        f"{item_line}\n"
        f"Outfit: {outfit}\n\n"
        "Write a short, casual OOTD-style caption (2-4 sentences) for a social post "
        "about this thrifted find and how it's styled. Mention the item name, price, "
        "and platform naturally — once each. Sound like a real person posting, not a "
        "product listing. Capture the vibe in specific terms. Emojis are ok but sparing."
    )

    # 3. Call the LLM with a higher temperature for variety; never raise.
    try:
        client = _get_groq_client()
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": "You write authentic, casual thrift / OOTD captions."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.95,
        )
        text = (resp.choices[0].message.content or "").strip()
        return text or "Couldn't generate a fit card — the model returned an empty response."
    except Exception as exc:
        return f"Couldn't generate a fit card ({exc.__class__.__name__}). Please try again."

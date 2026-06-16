"""
agent.py

The FitFindr planning loop. Orchestrates the three tools in response to a
natural language user query, passing state between them via a session dict.

Complete tools.py and test each tool in isolation before implementing this file.

Usage (once implemented):
    from agent import run_agent
    from utils.data_loader import get_example_wardrobe

    result = run_agent(
        query="vintage graphic tee under $30, size M",
        wardrobe=get_example_wardrobe(),
    )
    print(result["fit_card"])
    print(result["error"])   # None on success
"""

import re

from tools import search_listings, suggest_outfit, create_fit_card


# ── session state ─────────────────────────────────────────────────────────────

def _new_session(query: str, wardrobe: dict) -> dict:
    """
    Initialize and return a fresh session dict for one user interaction.

    The session dict is the single source of truth for everything that happens
    during a run — it stores the original query, parsed parameters, tool results,
    and any error that caused early termination.

    You may add fields to this dict as needed for your implementation.
    """
    return {
        "query": query,              # original user query
        "parsed": {},                # extracted description / size / max_price
        "search_results": [],        # list of matching listing dicts
        "selected_item": None,       # top result, passed into suggest_outfit
        "wardrobe": wardrobe,        # user's wardrobe dict
        "outfit_suggestion": None,   # string returned by suggest_outfit
        "fit_card": None,            # string returned by create_fit_card
        "error": None,               # set if the interaction ended early
    }


# ── query parsing ─────────────────────────────────────────────────────────────

def _parse_query(query: str) -> dict:
    """
    Extract a description, size, and max_price from a natural language query.

    Chosen approach: regex (deterministic, offline, testable). Handles patterns
    like "under $30", "$40", "below 25", "size M", "size 8.5". The size and price
    phrases are stripped out so the leftover words become the search description.

    Returns a dict: {"description": str, "size": str|None, "max_price": float|None}
    """
    q = (query or "").strip()
    text = q.lower()

    # max_price: "under $30", "below 30", "less than $40", "max 25", or a bare "$30"
    max_price = None
    m = re.search(r"(?:under|below|less than|max|cheaper than|<)\s*\$?\s*(\d+(?:\.\d+)?)", text)
    if not m:
        m = re.search(r"\$\s*(\d+(?:\.\d+)?)", text)
    if m:
        max_price = float(m.group(1))

    # size: "size M", "size 8", "size 8.5"
    size = None
    sm = re.search(r"\bsize\s+([a-z0-9.\/]+)", text)
    if sm:
        size = sm.group(1).upper()

    # description: the query with the price + size phrases removed
    description = q
    description = re.sub(r"(?:under|below|less than|max|cheaper than|<)\s*\$?\s*\d+(?:\.\d+)?", "", description, flags=re.I)
    description = re.sub(r"\$\s*\d+(?:\.\d+)?", "", description)
    description = re.sub(r"\bsize\s+[a-z0-9.\/]+", "", description, flags=re.I)
    description = re.sub(r"\s+", " ", description).strip(" ,")

    return {"description": description, "size": size, "max_price": max_price}


# ── planning loop ─────────────────────────────────────────────────────────────

def run_agent(query: str, wardrobe: dict) -> dict:
    """
    Main agent entry point. Runs the FitFindr planning loop for a single
    user interaction and returns the completed session dict.

    Args:
        query:    Natural language user request
                  (e.g., "vintage graphic tee under $30, size M")
        wardrobe: User's wardrobe dict — use get_example_wardrobe() or
                  get_empty_wardrobe() from utils/data_loader.py

    Returns:
        The session dict after the interaction completes. Check session["error"]
        first — if it is not None, the interaction ended early and the other
        output fields (outfit_suggestion, fit_card) will be None.
    """
    # Step 1: Initialize the session.
    session = _new_session(query, wardrobe)

    # Step 2: Parse the query into search parameters.
    session["parsed"] = _parse_query(query)
    description = session["parsed"]["description"]
    size = session["parsed"]["size"]
    max_price = session["parsed"]["max_price"]

    # Step 3: Search. This is the branch point of the whole agent.
    session["search_results"] = search_listings(description, size, max_price)
    if not session["search_results"]:
        # Empty result → set an error and STOP. Do not call suggest_outfit.
        msg = f"No listings matched '{description or query}'"
        if size:
            msg += f" in size {size}"
        if max_price is not None:
            msg += f" under ${max_price:g}"
        msg += ". Try loosening your search — raise the price or drop the size filter."
        session["error"] = msg
        return session

    # Step 4: Select the top result and write it to state.
    session["selected_item"] = session["search_results"][0]

    # Step 5: Suggest an outfit using the selected item + wardrobe (reads from state).
    session["outfit_suggestion"] = suggest_outfit(
        session["selected_item"], session["wardrobe"]
    )

    # Step 6: Create a fit card from the outfit + selected item (reads from state).
    session["fit_card"] = create_fit_card(
        session["outfit_suggestion"], session["selected_item"]
    )

    # Step 7: Return the completed session.
    return session


# ── CLI test ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from utils.data_loader import get_example_wardrobe, get_empty_wardrobe

    print("=== Happy path: graphic tee ===\n")
    session = run_agent(
        query="looking for a vintage graphic tee under $30",
        wardrobe=get_example_wardrobe(),
    )
    if session["error"]:
        print(f"Error: {session['error']}")
    else:
        print(f"Found: {session['selected_item']['title']}")
        print(f"\nOutfit: {session['outfit_suggestion']}")
        print(f"\nFit card: {session['fit_card']}")

    print("\n\n=== No-results path ===\n")
    session2 = run_agent(
        query="designer ballgown size XXS under $5",
        wardrobe=get_example_wardrobe(),
    )
    print(f"Error message: {session2['error']}")
    print(f"fit_card is None: {session2['fit_card'] is None}")
    print(f"suggest_outfit skipped (outfit_suggestion is None): {session2['outfit_suggestion'] is None}")
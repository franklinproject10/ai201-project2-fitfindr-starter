# FitFindr 🛍️

FitFindr is a multi-tool AI agent for thrift shopping. A user describes what they
want in plain language ("vintage graphic tee under $30, size M"); the agent searches
a mock listings dataset, suggests how to wear the top result against the user's
existing wardrobe, and writes a shareable outfit caption — all in one pass, with
state flowing between every step.

The interesting part isn't the three tools — it's the **planning loop** that decides
which tool to call based on what came back, the **session dict** that carries data
from one step to the next, and the **per-tool error handling** that keeps the agent
useful when a search returns nothing or a wardrobe is empty.

---

## Setup & How to Run

```bash
# 1. Create and activate a virtual environment
python -m venv .venv
source .venv/Scripts/activate     # Windows Git Bash
# source .venv/bin/activate        # Mac/Linux

# 2. Install dependencies
pip install -r requirements.txt

# 3. Add your Groq API key to a .env file in the repo root
#    GROQ_API_KEY=your_key_here   (free key at console.groq.com)
```

Run the tests:

```bash
pytest tests/
```

Run the agent from the command line (shows the happy path + the no-results branch):

```bash
python agent.py
```

Run the web UI (opens at http://localhost:7860):

```bash
python app.py
```

---

## Tool Inventory

The agent uses three tools, each a standalone function in `tools.py` with a defined
input/output contract. `search_listings` is deterministic; `suggest_outfit` and
`create_fit_card` call Groq's `llama-3.3-70b-versatile`.

### 1. `search_listings(description, size, max_price) -> list[dict]`

|             |                                                                                                                                                                                                                                              |
| ----------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Purpose** | Entry point. Filters the 40 mock listings and returns matches ranked best-first.                                                                                                                                                             |
| **Inputs**  | `description` (str): keywords, matched against title + description + style_tags. `size` (str \| None): requested size; flexible match — "M" also catches "S/M", "M/L", and "One Size". `max_price` (float \| None): inclusive price ceiling. |
| **Output**  | A `list[dict]` of full listing dicts, sorted by keyword relevance (cheaper-first tiebreak). Returns `[]` when nothing matches.                                                                                                               |

### 2. `suggest_outfit(new_item, wardrobe) -> str`

|             |                                                                                                                                                      |
| ----------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Purpose** | Suggests how to style the found item using pieces the user already owns.                                                                             |
| **Inputs**  | `new_item` (dict): a listing dict (the top search result). `wardrobe` (dict): `{"items": [...]}`, each item with name, category, colors, style_tags. |
| **Output**  | A non-empty `str` of styling advice. If the wardrobe is empty, returns deterministic general-styling advice instead of crashing.                     |

### 3. `create_fit_card(outfit, new_item) -> str`

|             |                                                                                                                                                    |
| ----------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Purpose** | Writes a short, casual, shareable caption for the complete look.                                                                                   |
| **Inputs**  | `outfit` (str): the suggestion string from `suggest_outfit`. `new_item` (dict): the listing dict, for price/platform/brand.                        |
| **Output**  | A `str` caption. Returns a descriptive error string if `outfit` is empty/whitespace. Higher LLM temperature (0.95) so captions vary across inputs. |

---

## How the Planning Loop Works

The loop is a **coded conditional pipeline** (`run_agent` in `agent.py`). It does not
call all three tools unconditionally — it checks what each tool returns and decides
the next step. The decisive moment is the empty-search branch:

```
1. Parse the query (regex) → description, size, max_price
2. search_listings(...)
       ├── results == []  → set session["error"], RETURN EARLY
       │                     (suggest_outfit and create_fit_card never run)
       └── results found  → session["selected_item"] = results[0]
3. suggest_outfit(selected_item, wardrobe) → session["outfit_suggestion"]
4. create_fit_card(outfit_suggestion, selected_item) → session["fit_card"]
5. Return the session
```

The agent's behavior genuinely differs based on input: a query that matches runs all
three tools; an impossible query (e.g. "designer ballgown size XXS under $5") stops
after step 2 with an error and never touches the LLM tools.

**Query parsing** uses regex rather than the LLM: it's deterministic, offline, and
testable. It pulls a price from patterns like "under $30" or "$40", a size from
"size M" / "size 8.5", and treats the leftover words as the search description.

---

## State Management

A single `session` dict is created per run and threaded through every step. Each tool's
output is written to the session; the next tool reads from it, so the user never
re-enters anything.

```python
session = {
    "query": query,              # original user query
    "parsed": {},                # description / size / max_price from the parser
    "search_results": [],        # list of matching listing dicts
    "selected_item": None,       # top result → passed into suggest_outfit
    "wardrobe": wardrobe,        # the user's wardrobe dict
    "outfit_suggestion": None,   # str from suggest_outfit → passed into create_fit_card
    "fit_card": None,            # str from create_fit_card
    "error": None,               # set on early termination
}
```

State passing is verifiable: after a run, `session["selected_item"] is
session["search_results"][0]` is `True` — the exact object `search_listings` returned
is what flows into the rest of the pipeline, with no copying or re-entry.

---

## Error Handling (per tool)

Every tool owns its failure mode and returns a usable value instead of raising. The
empty-wardrobe and empty-outfit guards run _before_ any LLM call, so those failure
paths are fast, offline, and deterministic.

| Tool              | Failure mode              | Behavior                                                                                                                           |
| ----------------- | ------------------------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| `search_listings` | No listings match         | Returns `[]`. The loop catches it, sets a helpful `error`, and stops before calling the LLM tools.                                 |
| `suggest_outfit`  | Empty wardrobe            | Returns deterministic general-styling advice (no crash, no empty string). Also catches LLM/API errors and returns a safe fallback. |
| `create_fit_card` | Empty / whitespace outfit | Returns a descriptive error string. Also catches LLM/API errors.                                                                   |

**Concrete example from testing** — the no-results branch, triggered deliberately:

```bash
$ python -c "from tools import search_listings; print(search_listings('designer ballgown', size='XXS', max_price=5))"
[]
```

Run end-to-end, the agent turns that empty list into a specific, actionable message
rather than a bare "no results":

```
No listings matched 'designer ballgown' in size XXS under $5.
Try loosening your search — raise the price or drop the size filter.
```

And `session["fit_card"]` stays `None`, `session["outfit_suggestion"]` stays `None` —
proof the LLM tools were never called on empty input.

---

## Spec Reflection

The most useful thing my `planning.md` did was surface a contract mismatch _before_ I
wrote code. My original spec had `suggest_outfit` return a structured dict
(`{text, paired_items}`), but the stub signature in `tools.py` declared `-> str`, and
`create_fit_card` declared `outfit: str`. Rather than fight the stub, I reconciled the
spec to it and made the whole pipeline string-based. Lesson: when the spec and the
stub disagree, the stub is the contract — update the plan, don't override the file.

Two other places the implementation went beyond the original plan: (1) the **query
parser** wasn't fully specified in my first draft — I added a regex approach and
documented it in the Planning Loop section; (2) I moved both the empty-wardrobe and
empty-outfit guards to run _before_ the LLM call, which I hadn't thought about until I
realized those failure-mode tests would otherwise need a live API key and would flake.

The spec earned its keep: because each tool's input/output/failure was written down
first, the generated code matched on the first pass and the tools tested green in
isolation before I wired the loop.

---

## AI Usage

I used Claude as my coding assistant, feeding it specific sections of `planning.md`
one piece at a time rather than asking it to "build the agent."

**Instance 1 — implementing `search_listings`.**
_Input:_ the Tool 1 spec block (inputs, return value, failure mode) plus the
`load_listings()` helper. _Output:_ a filter-score-sort implementation. _What I
changed:_ I made the size-matching decision myself — the data has messy sizes ("S/M",
"One Size", "US 8.5"), so a strict `==` match would silently drop valid items. I had
it implement flexible token-based matching instead, and verified with three queries
(one that returns results, one that returns `[]`, one testing that "M" also catches
"S/M").

**Instance 2 — implementing the planning loop.**
_Input:_ the Planning Loop section, the State Management section, and the Mermaid agent
diagram from `planning.md`. _Output:_ the `run_agent()` function. _What I verified /
overrode:_ I checked that it actually branches on the `search_listings` result and
returns early on `[]` instead of calling all three tools unconditionally. I confirmed
state passing with an identity check (`selected_item is search_results[0]`) and
adjusted the error message to name the specific filters the user could loosen.

**Instance 3 — reconciling the spec to the stub.**
When the AI's `planning.md` draft had `suggest_outfit` returning a dict but the stub
declared `-> str`, I had it update the spec (return type, state keys, error table,
diagram, walkthrough) to match the stub rather than changing the function signature.

---

## Project Structure

```
ai201-project2-fitfindr-starter/
├── tools.py            # The three tools + Groq client
├── agent.py            # run_agent() planning loop + query parser + session state
├── app.py              # Gradio UI (handle_query maps session → 3 panels)
├── planning.md         # Full design spec written before any code
├── conftest.py         # Puts repo root on sys.path for pytest
├── tests/
│   └── test_tools.py   # 10 tests: happy paths + every failure mode
├── data/               # listings.json (40 items) + wardrobe_schema.json
└── utils/data_loader.py
```

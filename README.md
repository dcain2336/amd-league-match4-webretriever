# WebRetriever

Autonomous web information retrieval agent — **AMD AI League Match 4:
Intelligent Web Information Retrieval** entry.

Ask in plain English. Get back the specific information you asked for,
with the exact source URLs behind it — or an honest refusal when no
verifiable answer exists.

```
$ python -m webretriever "What is the current price of an AMD Ryzen 9 9950X?"

Request: What is the current price of an AMD Ryzen 9 9950X?
Intent: price (looking for a price or cost figure)

Answer: $649.00
Confidence: 85% (verified)
Sources:
  - https://www.amd.com/...
  - https://www.newegg.com/...

Checked 6 pages in 24.3s.
```

## How it works

Five-stage pipeline, deterministic core:

1. **Understand** — parses the request into intent (price, contact, hours,
   spec, definition, how-to, date, fact), entities, and 2–4 search query
   variants. No ML model required.
2. **Search** — provider chain with automatic fallback:
   - [TinyFish](https://tinyfish.ai) Search (set `TINYFISH_API_KEY`) — best quality, JS-aware
   - DuckDuckGo HTML — keyless fallback, no signup
3. **Fetch + navigate** — fetches top hits (TinyFish Fetch renders JS-heavy
   pages to clean markdown; otherwise requests + BeautifulSoup readability
   extraction), then follows promising in-page links up to a fixed budget
   (8 pages, 2 hops) when the answer looks like it's one click deeper.
4. **Extract** — structure-aware: JSON-LD (`Product`, `Organization`,
   `FAQPage`), HTML tables (spec sheets), intent-specific patterns
   (prices, phone numbers, emails, hours, dates), and ranked text spans.
5. **Verify** — every candidate is checked against its own source text;
   independent multi-source agreement boosts confidence; near-identical
   values from different domains corroborate each other. If nothing is
   supported by evidence, the agent **refuses** instead of guessing.

Output contract (also available as JSON via `--json`):
`answer`, `citations[]`, `confidence`, `evidence[]`, `verified`,
`refused` + `refusal_reason`, `sources_checked`.

## Setup

```bash
pip install -r requirements.txt

# Recommended: TinyFish API key (free tier, no card)
export TINYFISH_API_KEY="your-key"

# Without a key the agent still works via the keyless fallback,
# with reduced resilience on JS-heavy sites.
python -m webretriever "your natural-language request"
```

Docker:

```bash
docker build -t webretriever .
docker run -e TINYFISH_API_KEY="$TINYFISH_API_KEY" webretriever \
  "What are the Saturday hours for the Jacksonville NC DMV?"
```

## Architecture

```
webretriever/
  understand.py        query -> intent, entities, search queries
  providers/
    search.py          TinyFish -> DuckDuckGo fallback chain
    fetch.py           TinyFish Fetch -> requests+bs4 fallback chain
  navigate.py          bounded multi-hop link following + page scoring
  extract.py           JSON-LD, tables, patterns, ranked spans
  verify.py            evidence grounding, corroboration, refusal
  agent.py             pipeline orchestration
  cli.py               human + JSON output
tests/                 unit tests (no network)
examples/              sample queries
```

Design notes:

- **Deterministic first.** The core pipeline uses no LLM, so results are
  reproducible and cheap. An LLM can be layered on later for query
  expansion / answer synthesis without changing the evidence contract.
- **Citations are mandatory.** An answer without a traceable source URL
  is treated as unverified.
- **Refusal is a feature.** "I couldn't verify this" beats a confident
  hallucination, every time.
- **Free-tier only.** No paid APIs, no keys required to run.

## Match 4 fit

Match 4 asks for an AI agent that *navigates websites, understands a
natural-language request, and accurately retrieves the specific
information a user needs.* That's exactly this pipeline: NL request in,
navigation across real pages (including one click deeper when needed),
and the specific fact back with its sources — or an explicit refusal.

## Tests

```bash
python -m pytest tests/ -q   # 12 unit tests, no network required
```

## License

MIT — see [LICENSE](LICENSE).

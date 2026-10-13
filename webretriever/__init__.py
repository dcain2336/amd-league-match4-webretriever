"""WebRetriever — autonomous web information retrieval agent.

Built for AMD AI League Match 4: Intelligent Web Information Retrieval.

Pipeline:
    natural-language request
      -> understand (intent + entities + search queries)
      -> search (TinyFish / DuckDuckGo)
      -> fetch + navigate (TinyFish fetch / requests+bs4, bounded multi-hop)
      -> extract (JSON-LD, tables, structured patterns, ranked spans)
      -> verify (evidence grounding, multi-source agreement)
      -> answer with citations, confidence, or honest refusal
"""

__version__ = "0.1.0"

"""Semantic layer: LangChain + Pinecone for natural-language questions over
historical findings — 'what's our ransomware exposure?' can't be answered by
a REST filter; it needs vector search over past reports and notes.
"""
from langchain_openai import OpenAIEmbeddings
from pinecone import Pinecone

from app.config import settings


class FindingsRAG:
    def __init__(self):
        self._embeddings = None
        self._index = None
        if settings.openai_api_key and settings.pinecone_api_key:
            self._embeddings = OpenAIEmbeddings(model="text-embedding-3-small")
            self._index = Pinecone(
                api_key=settings.pinecone_api_key
            ).Index(settings.pinecone_index)
        self._mock_findings = [
            {"text": "Ransomware exposure: 2 vendors run unpatched VPN appliances "
                     "with public CVEs. Prioritize vendor_acme and vendor_apex.",
             "source": "quarterly-risk-report-Q2"},
        ]

    def query(self, question: str, top_k: int = 3) -> str:
        """Return a plain-text answer string for the voice agent to speak."""
        if self._index is None:
            # Demo mode: echo the closest canned finding
            hits = [f for f in self._mock_findings if "ransomware" in question.lower()] \
                   or self._mock_findings
            return hits[0]["text"]

        vector = self._embeddings.embed_query(question)
        results = self._index.query(vector=vector, top_k=top_k, include_metadata=True)
        if not results["matches"]:
            return "I don't have any documented findings on that topic."
        return " ".join(m["metadata"]["text"] for m in results["matches"])

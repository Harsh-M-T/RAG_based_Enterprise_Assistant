"""
Enterprise Knowledge Assistant - Retrieval Module

Handles FAISS vector search, BM25 keyword search, and hybrid
rank fusion for document retrieval.
"""

import logging
import pickle
import re
from pathlib import Path
from typing import Optional

import faiss
import numpy as np
from sentence_transformers import SentenceTransformer

from config import (
    BM25_INDEX_PATH,
    BM25_WEIGHT,
    EMBEDDING_MODEL_NAME,
    FAISS_INDEX_PATH,
    HYBRID_SEARCH_ENABLED,
    METADATA_PATH,
    SIMILARITY_THRESHOLD,
    TOP_K,
    VECTOR_WEIGHT,
)

logger = logging.getLogger(__name__)


class Retriever:
    """Retrieves relevant document chunks using vector search and optional BM25."""

    def __init__(self):
        self._index: Optional[faiss.IndexFlatIP] = None
        self._metadata: Optional[list[dict]] = None
        self._model: Optional[SentenceTransformer] = None
        self._bm25 = None
        self._bm25_corpus_tokens = None
        self._loaded = False

    # ── Lazy Loading ──────────────────────────────────────────────────────

    def _ensure_loaded(self) -> None:
        """Load index, metadata, and models on first use."""
        if self._loaded:
            return

        # FAISS index
        if not FAISS_INDEX_PATH.exists():
            raise FileNotFoundError(
                f"FAISS index not found at {FAISS_INDEX_PATH}. "
                "Run ingestion.py first."
            )
        self._index = faiss.read_index(str(FAISS_INDEX_PATH))
        logger.info(f"Loaded FAISS index with {self._index.ntotal} vectors")

        # Metadata
        if not METADATA_PATH.exists():
            raise FileNotFoundError(
                f"Metadata not found at {METADATA_PATH}. "
                "Run ingestion.py first."
            )
        with open(METADATA_PATH, "rb") as f:
            self._metadata = pickle.load(f)
        logger.info(f"Loaded metadata for {len(self._metadata)} chunks")

        # Embedding model
        logger.info(f"Loading embedding model: {EMBEDDING_MODEL_NAME}")
        self._model = SentenceTransformer(EMBEDDING_MODEL_NAME)

        # BM25 index (optional)
        if HYBRID_SEARCH_ENABLED and BM25_INDEX_PATH.exists():
            with open(BM25_INDEX_PATH, "rb") as f:
                bm25_data = pickle.load(f)
                self._bm25 = bm25_data["bm25"]
                self._bm25_corpus_tokens = bm25_data["corpus_tokens"]
            logger.info("Loaded BM25 index for hybrid search")

        self._loaded = True

    # ── Vector Search ─────────────────────────────────────────────────────

    def _vector_search(self, query: str, top_k: int = TOP_K) -> list[dict]:
        """Perform FAISS cosine similarity search."""
        query_embedding = self._model.encode(
            [query], normalize_embeddings=True
        ).astype("float32")

        scores, indices = self._index.search(query_embedding, top_k)

        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0 or idx >= len(self._metadata):
                continue
            meta = self._metadata[idx].copy()
            meta["score"] = float(score)
            results.append(meta)

        return results

    # ── BM25 Search ───────────────────────────────────────────────────────

    def _bm25_search(self, query: str, top_k: int = TOP_K) -> list[dict]:
        """Perform BM25 keyword search."""
        if self._bm25 is None:
            return []

        query_tokens = re.findall(r'\b\w+\b', query.lower())
        bm25_scores = self._bm25.get_scores(query_tokens)

        # Get top-k indices
        top_indices = np.argsort(bm25_scores)[::-1][:top_k]

        results = []
        for idx in top_indices:
            if bm25_scores[idx] > 0:
                meta = self._metadata[idx].copy()
                meta["score"] = float(bm25_scores[idx])
                results.append(meta)

        return results

    # ── Hybrid Search (Reciprocal Rank Fusion) ────────────────────────────

    def _hybrid_search(self, query: str, top_k: int = TOP_K) -> list[dict]:
        """Combine vector and BM25 results using weighted Reciprocal Rank Fusion."""
        vector_results = self._vector_search(query, top_k=top_k * 2)
        bm25_results = self._bm25_search(query, top_k=top_k * 2)

        # RRF scoring
        k = 60  # RRF constant
        chunk_scores: dict[int, float] = {}
        chunk_data: dict[int, dict] = {}

        for rank, result in enumerate(vector_results):
            cid = result["chunk_id"]
            rrf_score = VECTOR_WEIGHT / (k + rank + 1)
            chunk_scores[cid] = chunk_scores.get(cid, 0) + rrf_score
            chunk_data[cid] = result

        for rank, result in enumerate(bm25_results):
            cid = result["chunk_id"]
            rrf_score = BM25_WEIGHT / (k + rank + 1)
            chunk_scores[cid] = chunk_scores.get(cid, 0) + rrf_score
            if cid not in chunk_data:
                chunk_data[cid] = result

        # Sort by combined RRF score
        sorted_ids = sorted(chunk_scores, key=chunk_scores.get, reverse=True)[:top_k]

        results = []
        for cid in sorted_ids:
            data = chunk_data[cid]
            data["score"] = chunk_scores[cid]
            results.append(data)

        return results

    # ── Public API ────────────────────────────────────────────────────────

    def search(self, query: str, top_k: int = TOP_K,
               threshold: float = SIMILARITY_THRESHOLD) -> list[dict]:
        """Search for relevant chunks.

        Returns a list of chunk dicts with keys:
            text, document, page, chunk_id, score

        Chunks below the similarity threshold are filtered out.
        """
        self._ensure_loaded()

        if HYBRID_SEARCH_ENABLED and self._bm25 is not None:
            results = self._hybrid_search(query, top_k)
        else:
            results = self._vector_search(query, top_k)

        # Filter by threshold (only applies meaningfully to vector scores)
        if not HYBRID_SEARCH_ENABLED:
            results = [r for r in results if r["score"] >= threshold]

        if not results:
            logger.info(f"No results above threshold {threshold} for: {query}")

        return results

    def get_formatted_sources(self, results: list[dict]) -> list[dict]:
        """Deduplicate and format source references."""
        seen = set()
        sources = []
        for r in results:
            key = (r["document"], r["page"])
            if key not in seen:
                seen.add(key)
                sources.append({
                    "document": r["document"],
                    "page": r["page"],
                })
        return sources

    def get_confidence(self, results: list[dict]) -> float:
        """Compute a confidence score from the retrieval scores."""
        if not results:
            return 0.0
        scores = [r["score"] for r in results]
        return round(float(np.mean(scores)), 4)

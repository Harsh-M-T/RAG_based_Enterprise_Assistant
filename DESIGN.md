# System Design Document

## Enterprise Knowledge Assistant — RAG Architecture

---

## 1. Overview

The Enterprise Knowledge Assistant is a Retrieval Augmented Generation (RAG) system designed to answer employee questions using internal company documents. The system runs entirely offline — both the embedding model and the language model execute locally, requiring no external API keys or cloud services.

### Core Components

```
┌──────────────────────────────────────────────────────────────────┐
│                        User Interfaces                          │
│                                                                  │
│   ┌─────────────────┐           ┌──────────────────────┐        │
│   │  Streamlit UI   │           │  FastAPI REST API     │        │
│   │  (ui.py)        │───────────│  (app.py)             │        │
│   │                 │   HTTP    │  POST /ask            │        │
│   └─────────────────┘           └──────────┬───────────┘        │
│                                             │                    │
├─────────────────────────────────────────────┼────────────────────┤
│                     Core Pipeline           │                    │
│                                             ▼                    │
│   ┌─────────────────────────────────────────────────────┐       │
│   │                  Retriever (retrieval.py)            │       │
│   │                                                      │       │
│   │   ┌──────────────┐    ┌──────────────┐              │       │
│   │   │ FAISS Vector │    │  BM25 Keyword│              │       │
│   │   │   Search     │    │   Search     │              │       │
│   │   └──────┬───────┘    └──────┬───────┘              │       │
│   │          │                    │                      │       │
│   │          └────────┬───────────┘                      │       │
│   │                   ▼                                  │       │
│   │         Reciprocal Rank Fusion                       │       │
│   │         + Relevance Filtering                        │       │
│   └──────────────────────┬──────────────────────────────┘       │
│                          │                                       │
│                          ▼                                       │
│   ┌──────────────────────────────────────────────────────┐      │
│   │               Generator (generation.py)              │      │
│   │                                                       │      │
│   │   Context + Question → Prompt → Ollama LLM → Answer  │      │
│   │   (with source citations)                             │      │
│   └──────────────────────────────────────────────────────┘      │
│                                                                  │
├──────────────────────────────────────────────────────────────────┤
│                    Ingestion Pipeline                            │
│                                                                  │
│   ┌────────┐    ┌──────────┐    ┌──────────┐    ┌───────────┐   │
│   │  PDFs  │    │ Chunking │    │Embedding │    │   FAISS   │   │
│   │  TXTs  │───▶│ (page-   │───▶│(MiniLM-  │───▶│  Index +  │   │
│   │  DOCXs │    │  aware)  │    │  L6-v2)  │    │ Metadata  │   │
│   └────────┘    └──────────┘    └──────────┘    └───────────┘   │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

---

## 2. Data Flow

### 2.1 Ingestion Flow (Offline, Batch)

1. **Document Loading**: Files are read from `sample_data/` directory.
   - **PDF**: `pypdf` extracts text **page by page**, each page tagged with `{document, page_number, text}`.
   - **TXT**: Read as a single block, tagged as page 1.
   - **DOCX**: `python-docx` extracts paragraph text, tagged as page 1.

2. **Chunking**: Each page's text is split into chunks of ~500 characters with 100-character overlap.
   - **Page boundary preservation**: Chunks are created *within* each page — a chunk from page 2 never includes text from page 3.
   - **Sentence-aware splitting**: The chunker tries to break at sentence boundaries (`. `), newlines, or word boundaries to avoid splitting mid-word.
   - **Metadata propagation**: Each chunk carries `{text, document, page, chunk_id}`.

3. **Embedding**: The `all-MiniLM-L6-v2` Sentence Transformer model generates 384-dimensional embeddings for each chunk. Vectors are L2-normalized for cosine similarity.

4. **Indexing**:
   - **FAISS**: `IndexFlatIP` (inner product on normalized vectors = cosine similarity). All vectors stored in a single flat index.
   - **BM25**: `rank_bm25.BM25Okapi` built from tokenized chunk texts for keyword matching.
   - **Metadata**: Parallel pickle file mapping vector index → chunk metadata.

### 2.2 Query Flow (Online, Per-Request)

1. **User submits question** via Streamlit UI or REST API.
2. **Retriever**:
   - Embeds the query using the same Sentence Transformer model.
   - **Vector search**: FAISS returns top-K nearest neighbors with cosine similarity scores.
   - **BM25 search**: Tokenizes query and scores against the BM25 index.
   - **Hybrid fusion**: Reciprocal Rank Fusion combines both result sets with configurable weights (default: 70% vector, 30% BM25).
   - **Relevance filtering**: Chunks below the similarity threshold (default: 0.30) are discarded.
3. **Generator**:
   - Formats retrieved chunks into a context block with source annotations.
   - Constructs the prompt with explicit instructions to answer only from context and cite sources.
   - Sends prompt to Ollama (local LLM) via HTTP POST to `localhost:11434`.
   - Returns the answer with structured source citations and a confidence score.

---

## 3. PDF Page Metadata Preservation

This is a critical design requirement. Here is exactly how page numbers flow through the system:

```
PDF File
  │
  ├─ pypdf.PdfReader.pages[0] → {text: "...", page: 1, document: "hr_policy.pdf"}
  ├─ pypdf.PdfReader.pages[1] → {text: "...", page: 2, document: "hr_policy.pdf"}
  └─ pypdf.PdfReader.pages[2] → {text: "...", page: 3, document: "hr_policy.pdf"}
       │
       ▼
  Chunking (within each page independently)
       │
       ├─ chunk_0: {text: "...", page: 2, document: "hr_policy.pdf", chunk_id: 5}
       ├─ chunk_1: {text: "...", page: 2, document: "hr_policy.pdf", chunk_id: 6}
       └─ chunk_2: {text: "...", page: 2, document: "hr_policy.pdf", chunk_id: 7}
       │
       ▼
  FAISS Index: vector at position 5,6,7
  Metadata:    metadata[5], metadata[6], metadata[7] → page: 2
       │
       ▼
  Retrieved chunk → "Source: hr_policy.pdf Page 2"
```

**Key guarantee**: Because chunking happens *per page*, every chunk has exactly one page number. There is no ambiguity.

---

## 4. Chunking Strategy Rationale

| Parameter | Value | Rationale |
|-----------|-------|----------|
| Chunk size | 500 chars | Small enough for precise retrieval, large enough to preserve semantic meaning. Fits within embedding model's optimal input range. |
| Overlap | 100 chars | Prevents information loss at chunk boundaries. ~20% overlap provides continuity without excessive duplication. |
| Splitting | Sentence-aware | Avoids breaking mid-sentence, which would harm both embedding quality and readability. |
| Page boundary | Preserved | Each chunk belongs to exactly one page, enabling accurate source citations. |

---

## 5. Prompt Engineering

The system prompt is carefully designed to prevent hallucination:

```
You are a helpful enterprise knowledge assistant. Answer the question using 
ONLY the provided context below. Follow these rules strictly:

1. Base your answer ONLY on the provided context.
2. If the context does not contain enough information, say so.
3. Be concise and accurate.
4. ALWAYS cite source documents: Source: <doc_name> Page <page_number>
5. Do not make up or hallucinate any information.
```

The context block explicitly tags each passage with its source:
```
--- Passage 1 [Source: hr_policy.pdf Page 2] ---
Employees are eligible for 24 paid leaves annually...
```

This makes it easy for the LLM to copy the citation into its answer.

---

## 6. Hallucination Prevention

Multiple layers prevent the system from generating false information:

1. **Retrieval threshold**: If the best chunk's similarity score is below 0.30, no context is provided and the system returns a "not enough information" response.
2. **Prompt guardrails**: The prompt explicitly says "ONLY use provided context" and "say when you don't know."
3. **Low temperature**: `temperature=0.1` reduces creative/hallucinated outputs.
4. **Confidence scoring**: The API returns a confidence score (average similarity of top-K chunks) so the caller can decide whether to trust the answer.

---

## 7. Hybrid Search Design

The system combines two retrieval strategies:

| Strategy | Strength | Weakness |
|----------|----------|----------|
| FAISS (semantic) | Understands meaning, handles paraphrasing | May miss exact terms |
| BM25 (keyword) | Exact term matching, handles rare terms | No semantic understanding |

**Reciprocal Rank Fusion (RRF)** combines both rankings:

$$\text{RRF}(d) = \sum_{r \in \text{rankings}} \frac{w_r}{k + \text{rank}_r(d)}$$

Where $k=60$ (standard constant) and $w_r$ is the strategy weight (0.7 for vector, 0.3 for BM25).

This avoids the need to normalize scores across different scoring systems.

---

## 8. Technology Choices

| Component | Choice | Rationale |
|-----------|--------|----------|
| Embedding | `all-MiniLM-L6-v2` | 80MB, 384-dim, excellent quality/speed ratio, runs on CPU |
| Vector DB | FAISS `IndexFlatIP` | Zero infrastructure, fast for <100K vectors, exact search |
| LLM | Ollama + `llama3.2:3b` | Simple setup, runs on 8GB RAM, good instruction following |
| API | FastAPI | Async, auto-docs, type validation, production-ready |
| UI | Streamlit | Rapid prototyping, built-in widgets, no frontend code needed |
| PDF parser | pypdf | Lightweight, reliable text extraction with page indexing |

---

## 9. Scalability Considerations

- **Current**: Flat FAISS index supports ~100K chunks efficiently on CPU.
- **Scaling to 1M+ chunks**: Switch to `IndexIVFFlat` or `IndexHNSW` for approximate nearest neighbor search.
- **Scaling to distributed**: Replace FAISS with Milvus, Qdrant, or Weaviate for multi-node deployment.
- **Incremental ingestion**: Current system rebuilds the full index. Future: support append-only updates.
- **Caching**: Add Redis or LRU cache for repeated queries.

# 🏢 Enterprise Knowledge Assistant

A production-ready **Retrieval Augmented Generation (RAG)** system that answers employee questions from internal company documents. Powered by a fully **offline LLM** — no API keys, no cloud services. All inference runs locally.



---

## 🚀 Features

- **Multi-format document ingestion**: PDF (with page-number tracking), TXT, DOCX
- **Hybrid search**: Semantic (FAISS) + Keyword (BM25) with Reciprocal Rank Fusion
- **Accurate citations**: Every answer includes source document name and page number
- **Hallucination prevention**: Relevance threshold filtering + explicit prompt guardrails
- **REST API**: FastAPI server with `POST /ask` endpoint
- **Interactive UI**: Streamlit frontend with conversation history and feedback
- **Fully offline**: Ollama LLM + Sentence Transformers — no API keys needed
- **Confidence scoring**: Based on retrieval similarity scores

---

## 📁 Project Structure

```
project/
├── app.py                  # FastAPI server (POST /ask, GET /health)
├── ui.py                   # Streamlit frontend
├── ingestion.py            # Document loading, chunking, embedding, indexing
├── retrieval.py            # FAISS + BM25 hybrid search
├── generation.py           # Prompt construction + Ollama LLM calls
├── config.py               # All configurable parameters
├── create_sample_data.py   # Generates sample PDF/TXT/DOCX files
├── requirements.txt        # Python dependencies
├── README.md               # This file
├── DESIGN.md               # System design document
├── sample_data/            # Sample documents for demo
│   ├── hr_policy.pdf       # 3-page HR policy (leave, benefits, complaints)
│   ├── product_faq.txt     # Product FAQ with pricing, refunds, support
│   ├── onboarding.docx     # Employee onboarding guide
│   └── security_guidelines.pdf  # Data security & compliance
├── index_store/            # Generated FAISS index + metadata (gitignored)
├── logs/                   # Application logs
└── evaluation/
    ├── test_queries.json   # 10 test questions with expected results
    └── evaluate.py         # Automated evaluation script
```

---

## 🛠️ Setup Instructions

### Prerequisites

- **Python 3.10+** (with pip)
- **8 GB RAM** minimum (CPU is sufficient)
- **Ollama** (for the local LLM)

### Step 1: Clone and Install Dependencies

```bash
cd Ai_assistant_rag
pip install -r requirements.txt
```

### Step 2: Install and Start Ollama

1. Download Ollama from [ollama.com](https://ollama.com/download)
2. Install and start the Ollama service:
   ```bash
   # On Windows: Ollama runs as a background service after installation
   # On macOS/Linux:
   ollama serve
   ```
3. Pull the LLM model:
   ```bash
   ollama pull llama3.2:3b
   ```
   > **Alternative models**: `mistral`, `phi3:mini`, `gemma2:2b` — update `OLLAMA_MODEL` in `config.py`.

### Step 3: Generate Sample Documents

```bash
python create_sample_data.py
```

This creates 4 sample documents in `sample_data/`:
- `hr_policy.pdf` (3 pages — leave, benefits, complaints)
- `product_faq.txt` (product pricing, refunds, support)
- `onboarding.docx` (new employee guide)
- `security_guidelines.pdf` (2 pages — passwords, incidents)

### Step 4: Run Document Ingestion

```bash
python ingestion.py
```

This will:
1. Extract text from all documents (with page numbers for PDFs)
2. Chunk text into overlapping segments with metadata
3. Generate embeddings using `all-MiniLM-L6-v2`
4. Build FAISS vector index and BM25 keyword index
5. Save everything to `index_store/`

### Step 5: Start the API Server

```bash
python app.py
# or: uvicorn app:app --host 0.0.0.0 --port 8000 --reload
```

API will be available at `http://localhost:8000`

### Step 6: Launch the Streamlit UI

```bash
streamlit run ui.py
```

UI will open at `http://localhost:8501`

---

## 📡 API Usage

### Ask a Question

```bash
curl -X POST http://localhost:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "What is the employee leave policy?"}'
```

**Response:**
```json
{
  "answer": "Employees are eligible for 24 paid leaves annually...",
  "sources": [
    {"document": "hr_policy.pdf", "page": 2}
  ],
  "confidence": 0.82,
  "model": "llama3.2:3b"
}
```

### Health Check

```bash
curl http://localhost:8000/health
```

---

## 📊 Evaluation

Run the evaluation suite (requires API server to be running):

```bash
cd evaluation
python evaluate.py
```

Or run in direct mode (no API server needed, but requires Ollama):

```bash
python evaluate.py --direct
```

The suite tests 10 queries across HR, Product, Security, Onboarding, and out-of-scope categories, measuring:
- **Source accuracy**: Correct document retrieved
- **Page accuracy**: Correct page cited
- **Keyword score**: Expected information present in answer
- **Mean Reciprocal Rank (MRR)**
- **Response time**

---

## ⚙️ Configuration

All parameters are in [`config.py`](config.py):

| Parameter | Default | Description |
|---|---|---|
| `CHUNK_SIZE` | 500 | Characters per chunk |
| `CHUNK_OVERLAP` | 100 | Overlap between chunks |
| `TOP_K` | 5 | Number of chunks to retrieve |
| `SIMILARITY_THRESHOLD` | 0.30 | Minimum similarity score |
| `OLLAMA_MODEL` | `llama3.2:3b` | Ollama model name |
| `HYBRID_SEARCH_ENABLED` | `True` | Enable BM25 + vector fusion |
| `BM25_WEIGHT` | 0.3 | BM25 weight in hybrid search |
| `VECTOR_WEIGHT` | 0.7 | Vector weight in hybrid search |
| `LLM_TEMPERATURE` | 0.1 | Low temp for factual answers |

---

## 🏗️ Architecture Decisions

See [DESIGN.md](DESIGN.md) for the full system design document. Key decisions:

1. **Page-aware chunking**: Chunks never cross page boundaries, ensuring accurate page citations.
2. **Hybrid retrieval**: BM25 catches exact keyword matches that semantic search might miss.
3. **Reciprocal Rank Fusion**: Combines BM25 and vector rankings fairly without score normalization.
4. **Relevance threshold**: Prevents hallucination by filtering low-confidence retrievals.
5. **Explicit prompt design**: The LLM prompt strictly instructs "answer ONLY from context."

---

## ⚠️ Limitations

- **Scanned PDFs**: Only text-based PDFs are supported. OCR for scanned/image PDFs is out of scope.
- **Large documents**: Very large corpora (10,000+ documents) may require a more scalable vector DB (e.g., Milvus, Qdrant).
- **Model quality**: The 3B model provides good answers but may occasionally miss nuance. Larger models (7B+) improve quality.
- **No authentication**: The API has no auth layer — add JWT/OAuth for production.
- **Single language**: Currently supports English documents only.

---


## 📝 License

This project is provided as-is for educational and evaluation purposes.

"""
Enterprise Knowledge Assistant - Configuration

Centralized configuration for all system parameters.
"""

import os
from pathlib import Path

# ─── Project Paths ───────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent
SAMPLE_DATA_DIR = PROJECT_ROOT / "sample_data"
INDEX_DIR = PROJECT_ROOT / "index_store"
LOG_DIR = PROJECT_ROOT / "logs"

# Ensure directories exist
INDEX_DIR.mkdir(exist_ok=True)
LOG_DIR.mkdir(exist_ok=True)

# ─── Document Processing ─────────────────────────────────────────────────────
SUPPORTED_EXTENSIONS = {".pdf", ".txt", ".docx"}
CHUNK_SIZE = 500          # characters per chunk
CHUNK_OVERLAP = 100       # overlap between consecutive chunks

# ─── Embedding Model ─────────────────────────────────────────────────────────
EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"
EMBEDDING_DIMENSION = 384

# ─── Vector Store ─────────────────────────────────────────────────────────────
FAISS_INDEX_PATH = INDEX_DIR / "faiss_index.bin"
METADATA_PATH = INDEX_DIR / "metadata.pkl"
BM25_INDEX_PATH = INDEX_DIR / "bm25_index.pkl"

# ─── Retrieval ────────────────────────────────────────────────────────────────
TOP_K = 5                           # number of chunks to retrieve
SIMILARITY_THRESHOLD = 0.30         # minimum cosine similarity
HYBRID_SEARCH_ENABLED = True        # combine BM25 + vector search
BM25_WEIGHT = 0.3                   # weight for BM25 in hybrid fusion
VECTOR_WEIGHT = 0.7                 # weight for vector search in hybrid fusion

# ─── LLM (Ollama) ─────────────────────────────────────────────────────────────
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:3b")
OLLAMA_TIMEOUT = 120                # seconds
LLM_TEMPERATURE = 0.1               # low temperature for factual answers
LLM_MAX_TOKENS = 512

# ─── API Server ───────────────────────────────────────────────────────────────
API_HOST = "0.0.0.0"
API_PORT = 8000

# ─── Logging ──────────────────────────────────────────────────────────────────
LOG_LEVEL = "INFO"
LOG_FILE = LOG_DIR / "assistant.log"

# ─── Prompt Template ──────────────────────────────────────────────────────────
SYSTEM_PROMPT = """You are a helpful enterprise knowledge assistant. Answer the question using ONLY the provided context below. Follow these rules strictly:

1. Base your answer ONLY on the provided context. Do not use any external knowledge.
2. If the context does not contain enough information to answer the question, respond with: "I don't have enough information to answer that question based on the provided documents."
3. Be concise and accurate.
4. At the end of your answer, ALWAYS cite the source documents using this exact format:
   Source: <document_name> Page <page_number>
5. If multiple sources are relevant, list each on a separate line.
6. Do not make up or hallucinate any information.

Context:
{context}

Question: {question}

Answer:"""

CONVERSATION_PROMPT = """You are a helpful enterprise knowledge assistant. Answer the question using ONLY the provided context below. Follow these rules strictly:

1. Base your answer ONLY on the provided context. Do not use any external knowledge.
2. If the context does not contain enough information to answer the question, respond with: "I don't have enough information to answer that question based on the provided documents."
3. Be concise and accurate.
4. At the end of your answer, ALWAYS cite the source documents using this exact format:
   Source: <document_name> Page <page_number>
5. If multiple sources are relevant, list each on a separate line.
6. Do not make up or hallucinate any information.
7. Consider the conversation history for context, but only answer from the provided documents.

Conversation History:
{history}

Context:
{context}

Question: {question}

Answer:"""

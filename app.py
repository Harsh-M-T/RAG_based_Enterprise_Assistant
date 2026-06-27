"""
Enterprise Knowledge Assistant - FastAPI Server

REST API exposing the RAG system via a POST /ask endpoint.
"""

import logging
import sys
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from config import API_HOST, API_PORT, LOG_FILE, LOG_LEVEL, OLLAMA_MODEL
from generation import Generator
from retrieval import Retriever

# ─── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)

# ─── Global instances ─────────────────────────────────────────────────────────
retriever: Optional[Retriever] = None
generator: Optional[Generator] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize retriever and generator on startup."""
    global retriever, generator
    logger.info("Initializing retriever and generator...")
    retriever = Retriever()
    generator = Generator()

    # Pre-load indices
    try:
        retriever._ensure_loaded()
        logger.info("Retriever loaded successfully")
    except FileNotFoundError as e:
        logger.warning(f"Index not found: {e}. Run ingestion.py first.")

    yield
    logger.info("Shutting down...")


# ─── FastAPI App ──────────────────────────────────────────────────────────────
app = FastAPI(
    title="Enterprise Knowledge Assistant",
    description="RAG-based question answering from internal company documents",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Request / Response Models ────────────────────────────────────────────────

class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=1000,
                          description="The question to ask")


class SourceInfo(BaseModel):
    document: str
    page: int


class AskResponse(BaseModel):
    answer: str
    sources: list[SourceInfo]
    confidence: float
    model: str


class HealthResponse(BaseModel):
    status: str
    index_loaded: bool
    ollama_available: bool
    model: str


# ─── Endpoints ────────────────────────────────────────────────────────────────

@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Check system health: index status and LLM availability."""
    index_loaded = (
        retriever is not None
        and retriever._index is not None
    )
    ollama_ok = generator.is_ollama_available() if generator else False

    return HealthResponse(
        status="healthy" if (index_loaded and ollama_ok) else "degraded",
        index_loaded=index_loaded,
        ollama_available=ollama_ok,
        model=OLLAMA_MODEL,
    )


@app.post("/ask", response_model=AskResponse)
async def ask_question(request: AskRequest):
    """Answer a question using RAG.

    Request:  {"question": "What is the refund policy?"}
    Response: {"answer": "...", "sources": [...], "confidence": 0.91}
    """
    if retriever is None or generator is None:
        raise HTTPException(status_code=503, detail="System not initialized")

    question = request.question.strip()
    logger.info(f"Received question: {question}")

    try:
        # Retrieve
        results = retriever.search(question)
        logger.info(f"Retrieved {len(results)} chunks")

        # Generate
        response = generator.generate(question, results)

        if response.get("error"):
            logger.warning(f"Generation error: {response['error']}")

        return AskResponse(
            answer=response["answer"],
            sources=[SourceInfo(**s) for s in response["sources"]],
            confidence=response["confidence"],
            model=response["model"],
        )

    except FileNotFoundError as e:
        raise HTTPException(
            status_code=503,
            detail=f"Index not found. Run ingestion first. {e}",
        )
    except Exception as e:
        logger.error(f"Error processing question: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/")
async def root():
    """Root endpoint with API info."""
    return {
        "name": "Enterprise Knowledge Assistant",
        "version": "1.0.0",
        "endpoints": {
            "POST /ask": "Ask a question",
            "GET /health": "Health check",
        },
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host=API_HOST, port=API_PORT, reload=True)

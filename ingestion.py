"""
Enterprise Knowledge Assistant - Document Ingestion Pipeline

Handles document loading, text extraction (with page tracking),
chunking with metadata, embedding generation, and FAISS index building.
Also builds a BM25 index for hybrid search.
"""

import logging
import pickle
import re
import sys
from pathlib import Path
from typing import Optional

import faiss
import numpy as np
from sentence_transformers import SentenceTransformer

from config import (
    BM25_INDEX_PATH,
    CHUNK_OVERLAP,
    CHUNK_SIZE,
    EMBEDDING_DIMENSION,
    EMBEDDING_MODEL_NAME,
    FAISS_INDEX_PATH,
    LOG_FILE,
    LOG_LEVEL,
    METADATA_PATH,
    SAMPLE_DATA_DIR,
    SUPPORTED_EXTENSIONS,
)

# ─── Logging Setup ────────────────────────────────────────────────────────────
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)


# ─── Document Parsers ─────────────────────────────────────────────────────────

def extract_text_from_pdf(file_path: Path) -> list[dict]:
    """Extract text from a PDF file, page by page.
    
    Returns a list of dicts: [{"text": str, "page": int, "document": str}, ...]
    """
    try:
        import pypdf
    except ImportError:
        logger.error("pypdf is not installed. Run: pip install pypdf")
        return []

    pages = []
    try:
        reader = pypdf.PdfReader(str(file_path))
        for i, page in enumerate(reader.pages):
            text = page.extract_text()
            if text and text.strip():
                pages.append({
                    "text": text.strip(),
                    "page": i + 1,  # 1-indexed
                    "document": file_path.name,
                })
        logger.info(f"Extracted {len(pages)} pages from {file_path.name}")
    except Exception as e:
        logger.error(f"Failed to read PDF {file_path.name}: {e}")
    return pages


def extract_text_from_txt(file_path: Path) -> list[dict]:
    """Extract text from a plain text file.
    
    Returns a list with a single dict (TXT files have no page concept).
    """
    try:
        text = file_path.read_text(encoding="utf-8", errors="replace")
        if text.strip():
            logger.info(f"Extracted text from {file_path.name}")
            return [{"text": text.strip(), "page": 1, "document": file_path.name}]
    except Exception as e:
        logger.error(f"Failed to read TXT {file_path.name}: {e}")
    return []


def extract_text_from_docx(file_path: Path) -> list[dict]:
    """Extract text from a DOCX file.
    
    Returns a list with a single dict (basic DOCX extraction).
    """
    try:
        from docx import Document
    except ImportError:
        logger.warning("python-docx is not installed. Skipping .docx files.")
        return []

    try:
        doc = Document(str(file_path))
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        text = "\n".join(paragraphs)
        if text.strip():
            logger.info(f"Extracted text from {file_path.name}")
            return [{"text": text.strip(), "page": 1, "document": file_path.name}]
    except Exception as e:
        logger.error(f"Failed to read DOCX {file_path.name}: {e}")
    return []


EXTRACTORS = {
    ".pdf": extract_text_from_pdf,
    ".txt": extract_text_from_txt,
    ".docx": extract_text_from_docx,
}


# ─── Chunking ─────────────────────────────────────────────────────────────────

def chunk_pages(pages: list[dict], chunk_size: int = CHUNK_SIZE,
                chunk_overlap: int = CHUNK_OVERLAP) -> list[dict]:
    """Split extracted pages into overlapping chunks, preserving page metadata.
    
    Each chunk carries: text, document name, page_number(s).
    Chunks respect page boundaries — a chunk from page 2 won't bleed into page 3
    unless the overlap naturally crosses the boundary.
    """
    chunks = []
    
    for page_data in pages:
        text = page_data["text"]
        doc_name = page_data["document"]
        page_num = page_data["page"]
        
        # If the page text is shorter than chunk_size, keep it as one chunk
        if len(text) <= chunk_size:
            chunks.append({
                "text": text,
                "document": doc_name,
                "page": page_num,
                "chunk_id": len(chunks),
            })
            continue
        
        # Sliding window chunking within the page
        start = 0
        while start < len(text):
            end = start + chunk_size
            chunk_text = text[start:end]
            
            # Try to break at a sentence or word boundary
            if end < len(text):
                # Look for the last period, newline, or space
                for sep in ['. ', '\n', ' ']:
                    last_sep = chunk_text.rfind(sep)
                    if last_sep > chunk_size * 0.5:  # only if we keep >50% of chunk
                        chunk_text = chunk_text[:last_sep + 1]
                        end = start + last_sep + 1
                        break
            
            if chunk_text.strip():
                chunks.append({
                    "text": chunk_text.strip(),
                    "document": doc_name,
                    "page": page_num,
                    "chunk_id": len(chunks),
                })
            
            start = end - chunk_overlap
            if start <= (end - chunk_size):  # prevent infinite loop
                start = end
    
    logger.info(f"Created {len(chunks)} chunks from {len(pages)} pages")
    return chunks


# ─── BM25 Index ───────────────────────────────────────────────────────────────

def tokenize(text: str) -> list[str]:
    """Simple whitespace + punctuation tokenizer for BM25."""
    text = text.lower()
    tokens = re.findall(r'\b\w+\b', text)
    return tokens


def build_bm25_index(chunks: list[dict]) -> None:
    """Build and save a BM25 index from the chunks."""
    try:
        from rank_bm25 import BM25Okapi
    except ImportError:
        logger.warning("rank_bm25 not installed. BM25 hybrid search disabled.")
        return
    
    tokenized_corpus = [tokenize(chunk["text"]) for chunk in chunks]
    bm25 = BM25Okapi(tokenized_corpus)
    
    with open(BM25_INDEX_PATH, "wb") as f:
        pickle.dump({"bm25": bm25, "corpus_tokens": tokenized_corpus}, f)
    
    logger.info(f"BM25 index saved to {BM25_INDEX_PATH}")


# ─── Embedding & FAISS Index ──────────────────────────────────────────────────

def build_faiss_index(chunks: list[dict],
                      model_name: str = EMBEDDING_MODEL_NAME) -> None:
    """Generate embeddings for all chunks and build a FAISS index."""
    if not chunks:
        logger.error("No chunks to index. Aborting.")
        return
    
    logger.info(f"Loading embedding model: {model_name}")
    model = SentenceTransformer(model_name)
    
    texts = [chunk["text"] for chunk in chunks]
    logger.info(f"Generating embeddings for {len(texts)} chunks...")
    embeddings = model.encode(texts, show_progress_bar=True, normalize_embeddings=True)
    embeddings = np.array(embeddings, dtype="float32")
    
    # Build FAISS index (Inner Product = cosine similarity on normalized vectors)
    index = faiss.IndexFlatIP(EMBEDDING_DIMENSION)
    index.add(embeddings)
    
    # Save FAISS index
    faiss.write_index(index, str(FAISS_INDEX_PATH))
    logger.info(f"FAISS index saved to {FAISS_INDEX_PATH} ({index.ntotal} vectors)")
    
    # Save metadata
    metadata = []
    for chunk in chunks:
        metadata.append({
            "text": chunk["text"],
            "document": chunk["document"],
            "page": chunk["page"],
            "chunk_id": chunk["chunk_id"],
        })
    
    with open(METADATA_PATH, "wb") as f:
        pickle.dump(metadata, f)
    logger.info(f"Metadata saved to {METADATA_PATH}")


# ─── Main Ingestion Pipeline ─────────────────────────────────────────────────

def load_documents(data_dir: Path = SAMPLE_DATA_DIR) -> list[dict]:
    """Load and extract text from all supported documents in a directory."""
    if not data_dir.exists():
        logger.error(f"Data directory not found: {data_dir}")
        return []
    
    all_pages = []
    files = sorted(data_dir.iterdir())
    
    for file_path in files:
        if file_path.suffix.lower() in SUPPORTED_EXTENSIONS:
            extractor = EXTRACTORS.get(file_path.suffix.lower())
            if extractor:
                pages = extractor(file_path)
                all_pages.extend(pages)
                logger.info(f"Loaded {file_path.name}: {len(pages)} page(s)")
        else:
            logger.debug(f"Skipping unsupported file: {file_path.name}")
    
    logger.info(f"Total pages extracted: {len(all_pages)}")
    return all_pages


def run_ingestion(data_dir: Optional[Path] = None) -> dict:
    """Run the full ingestion pipeline.
    
    Returns a summary dict with counts.
    """
    data_dir = data_dir or SAMPLE_DATA_DIR
    logger.info(f"{'='*60}")
    logger.info(f"Starting ingestion from: {data_dir}")
    logger.info(f"{'='*60}")
    
    # Step 1: Load documents
    pages = load_documents(data_dir)
    if not pages:
        logger.error("No documents found. Aborting ingestion.")
        return {"status": "error", "message": "No documents found"}
    
    # Step 2: Chunk
    chunks = chunk_pages(pages)
    
    # Step 3: Build FAISS index
    build_faiss_index(chunks)
    
    # Step 4: Build BM25 index (for hybrid search)
    build_bm25_index(chunks)
    
    summary = {
        "status": "success",
        "documents_processed": len(set(p["document"] for p in pages)),
        "pages_extracted": len(pages),
        "chunks_created": len(chunks),
        "index_path": str(FAISS_INDEX_PATH),
    }
    
    logger.info(f"Ingestion complete: {summary}")
    return summary


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Ingest documents into the knowledge base")
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=SAMPLE_DATA_DIR,
        help=f"Directory containing documents to ingest (default: {SAMPLE_DATA_DIR})",
    )
    args = parser.parse_args()
    
    result = run_ingestion(args.data_dir)
    print(f"\nIngestion Result: {result}")

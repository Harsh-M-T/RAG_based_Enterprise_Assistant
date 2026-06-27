"""
Enterprise Knowledge Assistant - Answer Generation Module

Builds prompts from retrieved context and calls the local LLM
(Ollama) to generate answers with source citations.
"""

import json
import logging
from typing import Optional

import requests

from config import (
    CONVERSATION_PROMPT,
    LLM_MAX_TOKENS,
    LLM_TEMPERATURE,
    OLLAMA_BASE_URL,
    OLLAMA_MODEL,
    OLLAMA_TIMEOUT,
    SYSTEM_PROMPT,
)

logger = logging.getLogger(__name__)


class Generator:
    """Generates answers using the local Ollama LLM."""

    def __init__(self, model: str = OLLAMA_MODEL, base_url: str = OLLAMA_BASE_URL):
        self.model = model
        self.base_url = base_url.rstrip("/")

    # ── Health Check ──────────────────────────────────────────────────────

    def is_ollama_available(self) -> bool:
        """Check if Ollama is running and reachable."""
        try:
            resp = requests.get(f"{self.base_url}/api/tags", timeout=5)
            return resp.status_code == 200
        except requests.ConnectionError:
            return False
        except Exception as e:
            logger.warning(f"Ollama health check failed: {e}")
            return False

    def list_models(self) -> list[str]:
        """List available Ollama models."""
        try:
            resp = requests.get(f"{self.base_url}/api/tags", timeout=5)
            if resp.status_code == 200:
                data = resp.json()
                return [m["name"] for m in data.get("models", [])]
        except Exception as e:
            logger.warning(f"Failed to list models: {e}")
        return []

    # ── Context Building ──────────────────────────────────────────────────

    @staticmethod
    def build_context(results: list[dict]) -> str:
        """Format retrieved chunks into a context string for the prompt."""
        if not results:
            return "No relevant context found."

        context_parts = []
        for i, r in enumerate(results, 1):
            source_ref = f"[Source: {r['document']} Page {r['page']}]"
            context_parts.append(f"--- Passage {i} {source_ref} ---\n{r['text']}")

        return "\n\n".join(context_parts)

    # ── Prompt Construction ───────────────────────────────────────────────

    def build_prompt(self, question: str, results: list[dict],
                     history: Optional[list[dict]] = None) -> str:
        """Build the full prompt with context and optional conversation history."""
        context = self.build_context(results)

        if history:
            history_str = "\n".join(
                f"{msg['role'].capitalize()}: {msg['content']}" for msg in history[-6:]
            )
            return CONVERSATION_PROMPT.format(
                history=history_str, context=context, question=question
            )

        return SYSTEM_PROMPT.format(context=context, question=question)

    # ── LLM Call ──────────────────────────────────────────────────────────

    def generate(self, question: str, results: list[dict],
                 history: Optional[list[dict]] = None) -> dict:
        """Generate an answer from the LLM.

        Returns:
            dict with keys: answer, sources, confidence, model, error
        """
        # Handle no results
        if not results:
            return {
                "answer": (
                    "I don't have enough information to answer that question "
                    "based on the provided documents."
                ),
                "sources": [],
                "confidence": 0.0,
                "model": self.model,
                "error": None,
            }

        # Build prompt
        prompt = self.build_prompt(question, results, history)

        # Check Ollama availability
        if not self.is_ollama_available():
            error_msg = (
                "Ollama is not running. Please start Ollama with: ollama serve\n"
                f"Then pull the model: ollama pull {self.model}"
            )
            logger.error(error_msg)
            return {
                "answer": "Error: The LLM service (Ollama) is not available. "
                          "Please ensure Ollama is running.",
                "sources": [],
                "confidence": 0.0,
                "model": self.model,
                "error": error_msg,
            }

        # Call Ollama API
        try:
            payload = {
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": LLM_TEMPERATURE,
                    "num_predict": LLM_MAX_TOKENS,
                },
            }

            logger.info(f"Calling Ollama model: {self.model}")
            resp = requests.post(
                f"{self.base_url}/api/generate",
                json=payload,
                timeout=OLLAMA_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
            answer = data.get("response", "").strip()

            if not answer:
                answer = (
                    "I don't have enough information to answer that question "
                    "based on the provided documents."
                )

            # Extract sources from results
            seen = set()
            sources = []
            for r in results:
                key = (r["document"], r["page"])
                if key not in seen:
                    seen.add(key)
                    sources.append({"document": r["document"], "page": r["page"]})

            # Compute confidence
            scores = [r["score"] for r in results]
            confidence = round(float(sum(scores) / len(scores)), 4) if scores else 0.0

            return {
                "answer": answer,
                "sources": sources,
                "confidence": confidence,
                "model": self.model,
                "error": None,
            }

        except requests.Timeout:
            logger.error("Ollama request timed out")
            return {
                "answer": "Error: The request to the LLM timed out. Try again.",
                "sources": [],
                "confidence": 0.0,
                "model": self.model,
                "error": "timeout",
            }
        except requests.RequestException as e:
            logger.error(f"Ollama request failed: {e}")
            return {
                "answer": f"Error: Failed to get a response from the LLM. {e}",
                "sources": [],
                "confidence": 0.0,
                "model": self.model,
                "error": str(e),
            }
        except Exception as e:
            logger.error(f"Unexpected error during generation: {e}")
            return {
                "answer": "Error: An unexpected error occurred.",
                "sources": [],
                "confidence": 0.0,
                "model": self.model,
                "error": str(e),
            }

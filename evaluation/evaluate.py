"""
Enterprise Knowledge Assistant - Evaluation Suite

Runs test queries against the RAG system and measures:
- Source accuracy (correct document and page retrieved)
- Answer quality (expected keywords present)
- Mean Reciprocal Rank (MRR) for retrieval
- Hallucination detection (out-of-scope questions)

Can run in two modes:
  1. API mode (default): Sends requests to the FastAPI server
  2. Direct mode (--direct): Calls retriever/generator directly
"""

import json
import sys
import time
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

TEST_FILE = Path(__file__).parent / "test_queries.json"


def load_test_queries() -> list[dict]:
    """Load test queries from JSON."""
    with open(TEST_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def evaluate_api_mode(base_url: str = "http://localhost:8000") -> dict:
    """Evaluate using the FastAPI endpoint."""
    import requests

    queries = load_test_queries()
    results = []
    total_time = 0

    print(f"\n{'='*70}")
    print(f"  EVALUATION SUITE — API Mode ({base_url})")
    print(f"{'='*70}\n")

    for q in queries:
        print(f"[{q['id']:2d}] {q['question']}")

        start = time.time()
        try:
            resp = requests.post(
                f"{base_url}/ask",
                json={"question": q["question"]},
                timeout=120,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print(f"     ERROR: {e}")
            results.append({"id": q["id"], "error": str(e)})
            continue
        elapsed = time.time() - start
        total_time += elapsed

        answer = data.get("answer", "")
        sources = data.get("sources", [])
        confidence = data.get("confidence", 0)

        # Check source accuracy
        source_correct = False
        page_correct = False
        if q["expected_source"] is None:
            # Out-of-scope: should say "don't have enough information"
            source_correct = any(
                kw.lower() in answer.lower() for kw in q["expected_keywords"]
            )
            page_correct = source_correct
        else:
            for s in sources:
                if s["document"] == q["expected_source"]:
                    source_correct = True
                    if s["page"] == q["expected_page"]:
                        page_correct = True

        # Check keyword presence in answer
        keywords_found = [
            kw for kw in q["expected_keywords"]
            if kw.lower() in answer.lower()
        ]
        keyword_score = len(keywords_found) / len(q["expected_keywords"]) if q["expected_keywords"] else 0

        result = {
            "id": q["id"],
            "question": q["question"],
            "category": q["category"],
            "source_correct": source_correct,
            "page_correct": page_correct,
            "keyword_score": keyword_score,
            "keywords_found": keywords_found,
            "keywords_missing": [kw for kw in q["expected_keywords"] if kw.lower() not in answer.lower()],
            "confidence": confidence,
            "response_time": round(elapsed, 2),
        }
        results.append(result)

        status = "[PASS]" if source_correct and keyword_score >= 0.5 else "[FAIL]"
        print(f"     {status} Source: {'PASS' if source_correct else 'FAIL'} | "
              f"Page: {'PASS' if page_correct else 'FAIL'} | "
              f"Keywords: {keyword_score:.0%} | "
              f"Conf: {confidence:.2f} | Time: {elapsed:.1f}s")

    # Compute aggregate metrics
    valid = [r for r in results if "error" not in r]
    if not valid:
        print("\nNo valid results to evaluate.")
        return {"error": "No valid results"}

    metrics = {
        "total_queries": len(queries),
        "successful_queries": len(valid),
        "source_accuracy": sum(r["source_correct"] for r in valid) / len(valid),
        "page_accuracy": sum(r["page_correct"] for r in valid) / len(valid),
        "avg_keyword_score": sum(r["keyword_score"] for r in valid) / len(valid),
        "avg_confidence": sum(r["confidence"] for r in valid) / len(valid),
        "avg_response_time": total_time / len(valid),
        "total_time": round(total_time, 2),
    }

    # MRR (simplified: 1/rank where rank=1 if source is in top sources)
    mrr_scores = []
    for r in valid:
        if r["source_correct"]:
            mrr_scores.append(1.0)  # Source found in results = rank 1
        else:
            mrr_scores.append(0.0)
    metrics["mrr"] = sum(mrr_scores) / len(mrr_scores) if mrr_scores else 0

    print(f"\n{'='*70}")
    print(f"  RESULTS SUMMARY")
    print(f"{'='*70}")
    print(f"  Source Accuracy:    {metrics['source_accuracy']:.1%}")
    print(f"  Page Accuracy:      {metrics['page_accuracy']:.1%}")
    print(f"  Avg Keyword Score:  {metrics['avg_keyword_score']:.1%}")
    print(f"  Mean Reciprocal Rank (MRR): {metrics['mrr']:.3f}")
    print(f"  Avg Confidence:     {metrics['avg_confidence']:.3f}")
    print(f"  Avg Response Time:  {metrics['avg_response_time']:.1f}s")
    print(f"  Total Time:         {metrics['total_time']:.1f}s")
    print(f"{'='*70}\n")

    # Save results
    output_path = Path(__file__).parent / "evaluation_results.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump({"metrics": metrics, "details": results}, f, indent=2)
    print(f"Results saved to: {output_path}")

    return metrics


def evaluate_direct_mode() -> dict:
    """Evaluate by calling retriever and generator directly (no API server needed)."""
    from retrieval import Retriever
    from generation import Generator

    queries = load_test_queries()
    retriever = Retriever()
    generator = Generator()

    results = []
    total_time = 0

    print(f"\n{'='*70}")
    print(f"  EVALUATION SUITE — Direct Mode")
    print(f"{'='*70}\n")

    for q in queries:
        print(f"[{q['id']:2d}] {q['question']}")

        start = time.time()
        try:
            search_results = retriever.search(q["question"])
            response = generator.generate(q["question"], search_results)
        except Exception as e:
            print(f"     ERROR: {e}")
            results.append({"id": q["id"], "error": str(e)})
            continue
        elapsed = time.time() - start
        total_time += elapsed

        answer = response.get("answer", "")
        sources = response.get("sources", [])
        confidence = response.get("confidence", 0)

        # Check source accuracy
        source_correct = False
        page_correct = False
        if q["expected_source"] is None:
            source_correct = any(
                kw.lower() in answer.lower() for kw in q["expected_keywords"]
            )
            page_correct = source_correct
        else:
            for s in sources:
                if s["document"] == q["expected_source"]:
                    source_correct = True
                    if s["page"] == q["expected_page"]:
                        page_correct = True

        keywords_found = [
            kw for kw in q["expected_keywords"]
            if kw.lower() in answer.lower()
        ]
        keyword_score = len(keywords_found) / len(q["expected_keywords"]) if q["expected_keywords"] else 0

        result = {
            "id": q["id"],
            "question": q["question"],
            "category": q["category"],
            "source_correct": source_correct,
            "page_correct": page_correct,
            "keyword_score": keyword_score,
            "confidence": confidence,
            "response_time": round(elapsed, 2),
        }
        results.append(result)

        status = "[PASS]" if source_correct and keyword_score >= 0.5 else "[FAIL]"
        print(f"     {status} Source: {'PASS' if source_correct else 'FAIL'} | "
              f"Page: {'PASS' if page_correct else 'FAIL'} | "
              f"Keywords: {keyword_score:.0%} | Time: {elapsed:.1f}s")

    valid = [r for r in results if "error" not in r]
    if valid:
        metrics = {
            "total_queries": len(queries),
            "successful_queries": len(valid),
            "source_accuracy": sum(r["source_correct"] for r in valid) / len(valid),
            "page_accuracy": sum(r["page_correct"] for r in valid) / len(valid),
            "avg_keyword_score": sum(r["keyword_score"] for r in valid) / len(valid),
            "avg_response_time": total_time / len(valid),
        }
        print(f"\n{'='*70}")
        print(f"  Source Accuracy:  {metrics['source_accuracy']:.1%}")
        print(f"  Page Accuracy:    {metrics['page_accuracy']:.1%}")
        print(f"  Keyword Score:    {metrics['avg_keyword_score']:.1%}")
        print(f"{'='*70}\n")
        return metrics

    return {"error": "No valid results"}


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Evaluate the Knowledge Assistant")
    parser.add_argument("--direct", action="store_true",
                        help="Run in direct mode (no API server needed)")
    parser.add_argument("--url", default="http://localhost:8000",
                        help="API base URL (default: http://localhost:8000)")
    args = parser.parse_args()

    if args.direct:
        evaluate_direct_mode()
    else:
        evaluate_api_mode(args.url)

from __future__ import annotations

import requests
from functools import lru_cache


class AISummaryUnavailable(RuntimeError):
    """Raised when the optional AI summary model cannot be used."""


OLLAMA_URL = "http://127.0.0.1:11434"  # Ollama local server


def _run_ollama_summary(text: str, max_length: int = 130, min_length: int = 45, **kwargs) -> list[dict[str, str]]:
    """Generate summary using Ollama local server."""
    prompt = f"Summarize the following text in {min_length} to {max_length} words:\n\n{text}"
    try:
        response = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={
                "model": "phi:latest",
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.1,
                    "num_predict": max_length * 2,  # Allow some buffer
                    "top_p": 0.9,
                },
            },
            timeout=60,  # Increased timeout
        )
        response.raise_for_status()
        result = response.json()
        summary = result.get("response", "").strip()
        return [{"summary_text": summary}]
    except (requests.RequestException, KeyError) as exc:
        raise AISummaryUnavailable(f"Ollama summarizer unavailable: {exc}") from exc


@lru_cache(maxsize=1)
def get_summarizer():
    # Try Ollama first
    try:
        # Test Ollama connection with a simple summary
        test_result = _run_ollama_summary("Test text for summarization.")
        if test_result and test_result[0].get("summary_text"):
            return _run_ollama_summary
    except AISummaryUnavailable:
        pass

    # Fallback to transformers
    try:
        from transformers import pipeline
        try:
            return pipeline("summarization", model="sshleifer/distilbart-cnn-12-6")
        except Exception as exc:  # pragma: no cover - model download depends on environment
            raise AISummaryUnavailable(
                "The AI summary model is not available locally yet. Run once with internet access to download it."
            ) from exc
    except ImportError as exc:
        raise AISummaryUnavailable(
            "AI summarization needs the transformers package. Install requirements to enable it."
        ) from exc


def generate_ai_summary(text: str, max_length: int = 130, min_length: int = 45) -> str:
    summarizer = get_summarizer()
    normalized = " ".join(text.split())
    if not normalized:
        raise AISummaryUnavailable("The transcript is empty, so AI summarization cannot run.")

    chunks: list[str] = []
    words = normalized.split()
    chunk_size = 220
    for start in range(0, len(words), chunk_size):
        chunks.append(" ".join(words[start : start + chunk_size]))

    partial_summaries: list[str] = []
    for chunk in chunks:
        target_max = min(max_length, max(min_length + 10, len(chunk.split()) // 2))
        summary = summarizer(chunk, max_length=target_max, min_length=min_length, do_sample=False)[0][
            "summary_text"
        ]
        partial_summaries.append(summary.strip())

    if len(partial_summaries) == 1:
        return partial_summaries[0]

    combined = " ".join(partial_summaries)
    final_max = min(160, max(70, len(combined.split()) // 2))
    return summarizer(combined, max_length=final_max, min_length=50, do_sample=False)[0]["summary_text"].strip()

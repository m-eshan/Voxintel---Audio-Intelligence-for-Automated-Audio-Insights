from __future__ import annotations

import re
import requests
from functools import lru_cache

OLLAMA_URL = "http://127.0.0.1:11434"  # Ollama local server


class LocalPolishUnavailable(RuntimeError):
    """Raised when the local offline polish model cannot be used."""


def _run_ollama(prompt: str, model: str = "phi:latest", max_tokens: int = 256) -> str:
    try:
        response = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={
                "model": model,
                "prompt": prompt,
                "stream": True,
                "options": {
                    "temperature": 0.0,
                    "num_predict": max_tokens,
                    "top_p": 0.9,
                },
            },
            timeout=300,
            stream=True,

        )
        response.raise_for_status()
        data = response.json()
        return data.get("response", "").strip()
    except Exception as exc:
        raise LocalPolishUnavailable(f"Ollama not available: {exc}") from exc


# Legacy function for backward compatibility
@lru_cache(maxsize=1)
def _load_polish_stack():
    raise LocalPolishUnavailable("T5/FLAN models replaced with Ollama. Use _run_ollama instead.")


def _run_t5(prompt: str, max_len: int = 256) -> str:
    # Redirect to Ollama
    return _run_ollama(prompt, max_tokens=max_len)


def rewrite_summary(text: str) -> str:
    prompt = (
        "Rewrite this into a clean, concise executive meeting summary in 2 to 4 sentences. "
        "Use third-person meeting-note style and avoid dialogue.\n\n"
        f"{text[:1400]}"
    )
    # return _run_t5(prompt, max_len=140)
    return _run_ollama(prompt, max_tokens=140)


def generate_mom_sections(text: str) -> dict:
    prompt = (
        "Convert these meeting notes into clean sections.\n"
        "Return exactly in this format:\n"
        "Summary: ...\n"
        "Discussion Points:\n- ...\n- ...\n"
        "Decisions:\n- ...\n"
        "Action Items:\n- task | owner | deadline | notes\n\n"
        f"{text[:1800]}"
    )
    raw = _run_ollama(prompt, max_tokens=320)
    return _parse_structured_output(raw)


def _parse_bullets(block: str) -> list[str]:
    lines = []
    for line in block.splitlines():
        line = line.strip()
        if not line:
            continue
        line = re.sub(r"^[-*]\s*", "", line)
        if line:
            lines.append(line)
    return lines


def _parse_action_items(block: str) -> list[dict]:
    items: list[dict] = []
    for line in _parse_bullets(block):
        parts = [part.strip() for part in line.split("|")]
        while len(parts) < 4:
            parts.append("Unknown" if len(parts) < 3 else "")
        items.append(
            {
                "task": parts[0] or "Unknown",
                "owner": parts[1] or "Unknown",
                "deadline": parts[2] or "Unknown",
                "notes": parts[3] or "Follow up on this item.",
            }
        )
    return items


def _parse_structured_output(text: str) -> dict:
    summary_match = re.search(r"Summary:\s*(.+?)(?=\n[A-Z][A-Za-z ]+:\s*|\Z)", text, flags=re.S)
    discussion_match = re.search(r"Discussion Points:\s*(.+?)(?=\nDecisions:|\Z)", text, flags=re.S)
    decisions_match = re.search(r"Decisions:\s*(.+?)(?=\nAction Items:|\Z)", text, flags=re.S)
    actions_match = re.search(r"Action Items:\s*(.+?)\Z", text, flags=re.S)

    return {
        "summary": (summary_match.group(1).strip() if summary_match else text.strip()),
        "discussion_points": _parse_bullets(discussion_match.group(1) if discussion_match else ""),
        "decisions": _parse_bullets(decisions_match.group(1) if decisions_match else ""),
        "action_items": _parse_action_items(actions_match.group(1) if actions_match else ""),
    }

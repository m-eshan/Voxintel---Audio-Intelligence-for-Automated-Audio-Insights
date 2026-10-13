from __future__ import annotations

import json
import os
import re
from pathlib import Path
from urllib import request, error

from .exports import render_mom_html, render_mom_pdf
from .optimized_pipeline import OptimizedPipelineError, run_optimized_voxintel

DEFAULT_OLLAMA_HOST = "http://127.0.0.1:11434"
DEFAULT_OLLAMA_MODEL = "phi:latest"  # Default to Phi for lightweight polishing


class OllamaPolishError(RuntimeError):
    """Raised when local Ollama polishing cannot continue."""


def _get_ollama_settings() -> tuple[str, str]:
    host = os.getenv("OLLAMA_HOST", DEFAULT_OLLAMA_HOST).rstrip("/")
    model = os.getenv("OLLAMA_MODEL", "").strip() or DEFAULT_OLLAMA_MODEL
    return host, model


def _build_prompt(base_results: dict) -> str:
    transcript = base_results["transcript"][:5000]  # Shorter for Phi
    draft_summary = base_results.get("summary", "")
    draft_mom = base_results.get("mom", {})
    participants = draft_mom.get("participants", [])

    # Simplified prompt for Phi model
    return (
        "You are an expert meeting note writer. Rewrite this into a professional MoM.\n\n"
        "OUTPUT FORMAT STRICTLY:\n"
        "TITLE:\n"
        "SUMMARY:\n"
        "DISCUSSION POINTS:\n"
        "DECISIONS:\n"
        "ACTION ITEMS:\n"
        "RISKS:\n"
        "NEXT STEPS:\n\n"
        "RULES:\n"
        "- Use formal, third-person corporate language.\n"
        "- No more than 3 consecutive words from transcript.\n"
        "- Summary must be 2-4 sentences.\n"
        "- Discussion: 3-5 points, max 32 words each.\n"
        "- Decisions: only firm decisions (decided/agreed/approved/confirmed).\n"
        "- Action Items: format 'Task | Owner | Deadline | High/Med/Low'\n"
        "- Keep participant names when possible.\n\n"
        f"Participants: {', '.join(participants) if participants else 'Unknown'}\n"
        f"Draft summary: {draft_summary}\n"
        f"Transcript snippet: {transcript}\n\n"
        "Generate the final polished MoM strictly following the format."
    )


def _parse_sectioned_response(content: str) -> dict:
    aliases = {
        "title": "title",
        "summary": "summary",
        "discussion points": "discussion",
        "decisions": "decisions",
        "action items": "actions",
        "risks": "risks",
        "next steps": "next_steps",
    }
    sections = {key: [] for key in aliases.values()}
    current_key = None

    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = re.match(r"^([A-Za-z ]+):\s*(.*)$", line)
        if match:
            key = aliases.get(match.group(1).strip().lower())
            if key:
                current_key = key
                remainder = match.group(2).strip()
                if remainder:
                    sections[key].append(remainder)
                continue
        if current_key:
            sections[current_key].append(line)

    def parse_bullets(text: str) -> list[str]:
        return [l.strip().lstrip("-* ").strip() for l in text.splitlines() if l.strip()]

    # Parse action items into structured dict
    action_items = []
    for line in parse_bullets("\n".join(sections["actions"]))[:5]:
        parts = [p.strip() for p in line.split("|")]
        confidence_str = parts[3].lower() if len(parts) > 3 else "medium"
        if "high" in confidence_str:
            confidence = 0.85
        elif "med" in confidence_str:
            confidence = 0.72
        else:
            confidence = 0.50
        action_items.append({
            "task": parts[0] if len(parts) > 0 else "Unknown",
            "owner": parts[1] if len(parts) > 1 else "Team",
            "deadline": parts[2] if len(parts) > 2 else "Unknown",
            "notes": "",
            "confidence": confidence,
        })

    return {
        "title": " ".join(sections["title"]) or "VoxIntel Ollama Meeting Report",
        "summary": " ".join(sections["summary"]) or "The meeting focused on key discussion points.",
        "discussion_points": parse_bullets("\n".join(sections["discussion"]))[:5],
        "decisions": parse_bullets("\n".join(sections["decisions"]))[:3],
        "action_items": action_items,
        "risks": parse_bullets("\n".join(sections["risks"]))[:3],
        "next_steps": parse_bullets("\n".join(sections["next_steps"]))[:3],
    }


def _normalize_sentence(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\b(um|uh|like|you know|basically|kind of|sort of)\b", "", text, flags=re.IGNORECASE)
    text = text.strip(" ,.")
    if not text:
        return ""
    text = text[0].upper() + text[1:]
    if text[-1] not in ".!?":
        text += "."
    return text


def _rewrite_formal_style(text: str) -> str:
    text = _normalize_sentence(text)
    text = re.sub(r"\bwe\b", "the team", text, flags=re.IGNORECASE)
    text = re.sub(r"\bour\b", "the team's", text, flags=re.IGNORECASE)
    return text


def _polish_title(title: str) -> str:
    title = _normalize_sentence(title).rstrip(".")
    title = re.sub(r"\b(discussed stuff|talked about stuff|stuff)\b", "Discussion", title, flags=re.IGNORECASE)
    title = re.sub(r"^(The team discussed|We discussed|Discussion on)\s+", "", title, flags=re.IGNORECASE)
    if not title or title.lower() in {"meeting", "discussion", "update"}:
        return "Executive Meeting Summary"
    title = title[0].upper() + title[1:]
    return title


def _post_process_response(
    parsed_response: dict,
    confidence_threshold: float = 0.6,
    drop_generic_owners: bool = False,
    require_participant_names: bool = False,
    auto_fix_grammar: bool = False,
) -> dict:
    result = dict(parsed_response)
    # Polish title
    result["title"] = _polish_title(result.get("title", ""))

    # Summary: split, cap to 4 sentences, and polish
    raw_summary = result.get("summary", "")
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", raw_summary) if s.strip()]
    if len(sentences) > 4:
        sentences = sentences[:4]
    
    formatted_sentences = []
    for s in sentences:
        s_norm = _rewrite_formal_style(s) if auto_fix_grammar or "we" in s.lower() else _normalize_sentence(s)
        formatted_sentences.append(s_norm)
    result["summary"] = " ".join(formatted_sentences)

    # Filter action items
    raw_actions = list(result.get("action_items", []))
    filtered_actions = []
    num_filtered = 0
    quality_warnings = []

    for item in raw_actions:
        conf = float(item.get("confidence", 0.7))
        owner = str(item.get("owner", "Team")).strip()

        if conf < confidence_threshold:
            num_filtered += 1
            quality_warnings.append(f"Filtered low-confidence task ({conf:.2f} < {confidence_threshold:.2f}): {item.get('task')}")
            continue

        if owner.lower() in {"team", "unknown"}:
            quality_warnings.append(f"Action item has generic owner '{owner}': {item.get('task')}")

        filtered_actions.append(item)

    result["action_items"] = filtered_actions[:5]
    result["num_filtered_items"] = num_filtered
    result["quality_warnings"] = quality_warnings
    result["quality_score"] = max(0.0, min(1.0, 1.0 - (0.15 * len(quality_warnings))))
    return result


def _call_ollama(prompt: str, confidence_threshold: float = None) -> dict:
    if confidence_threshold is None:
        confidence_threshold = float(os.getenv("OLLAMA_CONFIDENCE_THRESHOLD", "0.60"))

    host, model = _get_ollama_settings()
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.2, "num_predict": 300, "top_p": 0.9},
    }

    req = request.Request(
        url=f"{host}/api/generate",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with request.urlopen(req, timeout=300) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
    except error.URLError as exc:
        raise OllamaPolishError(f"Ollama not reachable at {host}") from exc

    content = raw.get("response", "")
    if not content.strip():
        raise OllamaPolishError("Ollama returned empty response.")

    parsed = _parse_sectioned_response(content)
    processed = _post_process_response(parsed, confidence_threshold=confidence_threshold)
    return processed


def polish_with_ollama(audio_path: str | Path, 
                       progress_callback=None,
                       confidence_threshold: float = None,
                       attendees: list[str] | None = None) -> dict:
    if progress_callback:
        progress_callback(20, "Running optimized transcription...")

    try:
        base_results = run_optimized_voxintel(audio_path, progress_callback=progress_callback, attendees=attendees)
    except OptimizedPipelineError as exc:
        raise OllamaPolishError(str(exc)) from exc

    if progress_callback:
        progress_callback(70, "Polishing meeting notes with Ollama...")

    payload = _call_ollama(_build_prompt(base_results), confidence_threshold=confidence_threshold)

    if progress_callback:
        progress_callback(100, "Polishing complete.")

    # Step 3: Build polished MoM
    polished_mom = {
        "participants": base_results["mom"].get("participants", ["Unknown"]),
        "overview": payload.get("summary", base_results.get("summary", "")),
        "discussion_points": payload.get("discussion_points", []),
        "decisions": payload.get("decisions", []),
        "action_items": [
            {
                "task": item["task"],
                "person": item["owner"],
                "deadline": item["deadline"],
                "notes": item["notes"],
                "confidence": item["confidence"],
            }
            for item in payload.get("action_items", [])
        ],
        "risks": payload.get("risks", []),
        "next_steps": payload.get("next_steps", []),
        "title": payload.get("title", "VoxIntel Ollama Meeting Report"),
    }

    # Step 4: Render reports
    report_context = {
        "title": polished_mom["title"],
        "summary": polished_mom["overview"],
        "participants": polished_mom["participants"],
        "discussion_points": polished_mom["discussion_points"],
        "decisions": polished_mom["decisions"],
        "risks": polished_mom["risks"],
        "action_items": [
            {
                "task": item["task"],
                "owner": item["person"],
                "deadline": item["deadline"],
                "notes": item.get("notes", ""),
            }
            for item in polished_mom["action_items"]
        ],
    }

    base_results["mom"] = polished_mom
    base_results["html_report"] = render_mom_html(report_context)
    base_results["pdf_report"] = render_mom_pdf(report_context)
    return base_results

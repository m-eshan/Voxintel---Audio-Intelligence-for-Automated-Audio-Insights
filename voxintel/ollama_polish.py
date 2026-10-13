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
    env_model = os.getenv("OLLAMA_MODEL", "").strip()
    if env_model:
        return host, env_model

    try:
        req = request.Request(f"{host}/api/tags", headers={"Content-Type": "application/json"}, method="GET")
        with request.urlopen(req, timeout=1.5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            installed = [m.get("name", "") for m in data.get("models", [])]
            for candidate in ["llama3.2:3b", "llama3.2", "phi3", "phi:latest", "mistral", "qwen"]:
                for inst in installed:
                    if candidate in inst:
                        return host, inst
            if installed:
                return host, installed[0]
    except Exception:
        pass

    return host, DEFAULT_OLLAMA_MODEL


def _build_prompt(base_results: dict, attendees: list[str] | None = None) -> str:
    segments = base_results.get("segments", [])
    if segments:
        turns = []
        for s in segments[:75]:
            start_sec = int(s.get("start", 0))
            mm = start_sec // 60
            ss = start_sec % 60
            spk = s.get("speaker", "Speaker")
            text = s.get("text", "")
            turns.append(f"[{mm:02d}:{ss:02d}] {spk}: {text}")
        transcript = "\n".join(turns)
    else:
        transcript = base_results.get("transcript", "")[:4500]

    draft_mom = base_results.get("mom", {})
    if not attendees:
        attendees = draft_mom.get("participants", [])
    attendee_list_str = ", ".join(attendees) if attendees else "Unknown attendees"

    return (
        "You are an executive meeting secretary. Write professional Minutes of Meeting (MoM) in THIRD PERSON, past tense.\n\n"
        "STRICT INSTRUCTIONS:\n"
        "1. Never use first-person pronouns (I, we, our, me, us). Always refer to speakers by name or 'Speaker N'.\n"
        "2. Write in formal past tense (e.g. 'George committed to...', 'The team approved...').\n"
        "3. Every discussion point and decision must cite the timestamp (mm:ss) from the transcript.\n"
        f"4. Action item owners MUST be chosen from this attendee list: [{attendee_list_str}]. If unassigned or unknown, use 'Unassigned'.\n"
        "5. Output valid JSON strictly conforming to this schema:\n\n"
        "{\n"
        '  "title": "Concise Descriptive Meeting Title",\n'
        '  "summary": "2-4 sentence executive summary strictly in third person past tense.",\n'
        '  "discussion_points": [{"time": "mm:ss", "speaker": "Name or Speaker", "point": "Concise summary of topic"}],\n'
        '  "decisions": [{"time": "mm:ss", "speaker": "Name or Speaker", "decision": "Agreed decision"}],\n'
        '  "action_items": [{"time": "mm:ss", "owner": "Name from attendees or Unassigned", "task": "Specific task", "deadline": "Deadline or Not specified"}],\n'
        '  "risks": ["Identified risk or blocker"],\n'
        '  "next_steps": ["Key next step"]\n'
        "}\n\n"
        f"TRANSCRIPT WITH TIMESTAMPS:\n{transcript}\n\n"
        "Generate the JSON MoM now:"
    )


def _parse_sectioned_response(content: str) -> dict:
    cleaned = content.strip()

    # Try parsing JSON first
    json_candidate = cleaned
    if "```json" in json_candidate:
        match = re.search(r"```json\s*(\{.*?\})\s*```", json_candidate, re.DOTALL)
        if match:
            json_candidate = match.group(1).strip()
    elif "```" in json_candidate:
        match = re.search(r"```\s*(\{.*?\})\s*```", json_candidate, re.DOTALL)
        if match:
            json_candidate = match.group(1).strip()
    elif "{" in json_candidate and "}" in json_candidate:
        match = re.search(r"(\{.*\})", json_candidate, re.DOTALL)
        if match:
            json_candidate = match.group(1).strip()

    try:
        data = json.loads(json_candidate)
        if isinstance(data, dict):
            raw_disc = data.get("discussion_points", [])
            discussion = []
            for d in raw_disc:
                if isinstance(d, dict):
                    time_str = f"[{d['time']}] " if d.get("time") else ""
                    spk_str = f"{d['speaker']}: " if d.get("speaker") else ""
                    discussion.append(f"{time_str}{spk_str}{d.get('point', '')}".strip())
                elif isinstance(d, str):
                    discussion.append(d)

            raw_dec = data.get("decisions", [])
            decisions = []
            for d in raw_dec:
                if isinstance(d, dict):
                    time_str = f"[{d['time']}] " if d.get("time") else ""
                    decisions.append(f"{time_str}{d.get('decision', '')}".strip())
                elif isinstance(d, str):
                    decisions.append(d)

            raw_actions = data.get("action_items", [])
            action_items = []
            for a in raw_actions:
                if isinstance(a, dict):
                    action_items.append({
                        "task": a.get("task", "Unknown"),
                        "owner": a.get("owner", a.get("person", "Unassigned")),
                        "deadline": a.get("deadline", "Unknown"),
                        "notes": a.get("time", ""),
                        "confidence": float(a.get("confidence", 0.9)),
                    })
                elif isinstance(a, str):
                    parts = [p.strip() for p in a.split("|")]
                    action_items.append({
                        "task": parts[0] if len(parts) > 0 else "Unknown",
                        "owner": parts[1] if len(parts) > 1 else "Team",
                        "deadline": parts[2] if len(parts) > 2 else "Unknown",
                        "notes": "",
                        "confidence": 0.85,
                    })

            return {
                "title": data.get("title", "") or "VoxIntel Meeting Report",
                "summary": data.get("summary", "") or data.get("overview", "") or "Executive meeting summary.",
                "discussion_points": discussion[:5],
                "decisions": decisions[:5],
                "action_items": action_items[:5],
                "risks": [r if isinstance(r, str) else str(r) for r in data.get("risks", [])][:3],
                "next_steps": [n if isinstance(n, str) else str(n) for n in data.get("next_steps", [])][:3],
            }
    except Exception:
        pass

    # Fallback to plain text header parsing (TITLE:, SUMMARY:, etc.)
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
    attendees: list[str] | None = None,
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
    attendees_lower = [a.lower() for a in attendees] if attendees else []

    for item in raw_actions:
        conf = float(item.get("confidence", 0.7))
        owner = str(item.get("owner", "Team")).strip()

        if attendees_lower and owner.lower() not in attendees_lower:
            if owner.lower() in {"team", "unknown", "the login", "the", "it", "user", "users"} or drop_generic_owners:
                item["owner"] = "Unassigned"
                owner = "Unassigned"

        if conf < confidence_threshold:
            num_filtered += 1
            quality_warnings.append(f"Filtered low-confidence task ({conf:.2f} < {confidence_threshold:.2f}): {item.get('task')}")
            continue

        if owner.lower() in {"team", "unknown", "unassigned"}:
            quality_warnings.append(f"Action item has generic owner '{owner}': {item.get('task')}")

        filtered_actions.append(item)

    result["action_items"] = filtered_actions[:5]
    result["num_filtered_items"] = num_filtered
    result["quality_warnings"] = quality_warnings
    result["quality_score"] = max(0.0, min(1.0, 1.0 - (0.15 * len(quality_warnings))))
    return result


def _call_ollama(prompt: str, confidence_threshold: float = None, attendees: list[str] | None = None) -> dict:
    if confidence_threshold is None:
        confidence_threshold = float(os.getenv("OLLAMA_CONFIDENCE_THRESHOLD", "0.60"))

    host, model = _get_ollama_settings()
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.1, "num_predict": 450, "top_p": 0.9},
    }

    req = request.Request(
        url=f"{host}/api/generate",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with request.urlopen(req, timeout=120) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
    except error.URLError as exc:
        raise OllamaPolishError(
            f"Ollama server is not reachable at {host}. "
            f"Please ensure Ollama is running (`ollama serve` or Ollama app) or use Fast Mode."
        ) from exc
    except Exception as exc:
        raise OllamaPolishError(f"Ollama generation failed: {exc}") from exc

    content = raw.get("response", "")
    if not content.strip():
        raise OllamaPolishError("Ollama returned empty response.")

    parsed = _parse_sectioned_response(content)
    processed = _post_process_response(parsed, confidence_threshold=confidence_threshold, attendees=attendees)
    return processed


def polish_results_with_ollama(
    base_results: dict,
    progress_callback=None,
    confidence_threshold: float = None,
    attendees: list[str] | None = None,
) -> dict:
    """Polish pre-computed transcription results using Ollama without re-transcribing."""
    if progress_callback:
        progress_callback(75, "Polishing meeting notes with Ollama LLM...")

    prompt = _build_prompt(base_results, attendees=attendees)
    payload = _call_ollama(prompt, confidence_threshold=confidence_threshold, attendees=attendees)

    if progress_callback:
        progress_callback(95, "Rendering polished reports...")

    polished_mom = {
        "participants": attendees or base_results.get("mom", {}).get("participants", ["Unknown"]),
        "overview": payload.get("summary", base_results.get("summary", "")),
        "discussion_points": payload.get("discussion_points", []),
        "decisions": payload.get("decisions", []),
        "action_items": [
            {
                "task": item["task"],
                "person": item["owner"],
                "deadline": item["deadline"],
                "notes": item.get("notes", ""),
                "confidence": item.get("confidence", 0.85),
            }
            for item in payload.get("action_items", [])
        ],
        "risks": payload.get("risks", []),
        "next_steps": payload.get("next_steps", []),
        "title": payload.get("title", "VoxIntel Ollama Meeting Report"),
    }

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

    base_results["summary"] = polished_mom["overview"]
    base_results["summary_engine"] = "ollama-polish"
    base_results["ollama_polish_used"] = True
    base_results["mom"] = polished_mom
    base_results["html_report"] = render_mom_html(report_context)
    base_results["pdf_report"] = render_mom_pdf(report_context)
    return base_results


def polish_with_ollama(
    audio_path: str | Path, 
    progress_callback=None,
    confidence_threshold: float = None,
    attendees: list[str] | None = None,
) -> dict:
    if progress_callback:
        progress_callback(20, "Running optimized transcription...")

    try:
        base_results = run_optimized_voxintel(audio_path, progress_callback=progress_callback, attendees=attendees)
    except OptimizedPipelineError as exc:
        raise OllamaPolishError(str(exc)) from exc

    return polish_results_with_ollama(
        base_results,
        progress_callback=progress_callback,
        confidence_threshold=confidence_threshold,
        attendees=attendees,
    )

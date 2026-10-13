from __future__ import annotations

import json
import re
import requests
from functools import lru_cache

from .ai_polish import LocalPolishUnavailable, generate_mom_sections, rewrite_summary
from .insights import generate_mom, generate_summary
from .nlp import clean_transcript

OLLAMA_URL = "http://127.0.0.1:11434"  # Ollama local server

MEETING_SCHEMA_EXAMPLE = {
    "title": "Short meeting title",
    "summary": "2-4 sentence executive summary.",
    "discussion_points": ["Point 1", "Point 2"],
    "decisions": ["Decision 1"],
    "action_items": [
        {
            "task": "Task description",
            "owner": "Owner or Unknown",
            "deadline": "Deadline or Unknown",
            "notes": "Short note",
        }
    ],
}


def _run_ollama_writer(prompt: str, model: str = "phi:latest") -> str:
    """Generate text using Ollama local server with phi
      model."""
    try:
        response = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={
                "model": model,
                "prompt": prompt,
                "stream": True,
                "options": {
                    "temperature": 0.1,
                    "num_predict": 256,
                    "top_p": 0.9,
                },
            },
            timeout=300,
            stream=True,
        )
        result_text = ""
        for line in response.iter_lines(decode_unicode=True):
            if line:
                try:
                    chunk = json.loads(line)
                    # Ollama streaming format: {"response": "partial text"}
                    if "response" in chunk:
                        result_text += chunk["response"]
                except json.JSONDecodeError:
                    continue
        return result_text.strip()

    except (requests.RequestException, KeyError) as exc:
        raise LocalPolishUnavailable(f"Ollama writer unavailable: {exc}") from exc
        

@lru_cache(maxsize=1)
def _get_writer_pipeline():
    """Return a writer function that uses TinyLlama via Ollama if available."""
    try:
        test_response = _run_ollama_writer("Test TinyLlama connection", model="phi:latest")
        if test_response:
            return lambda prompt, **kwargs: [{"generated_text": _run_ollama_writer(prompt, model="phi:latest")}]
    except LocalPolishUnavailable:
        pass

    # Optional fallback to HuggingFace transformers if Ollama TinyLlama fails
    try:
        from transformers import pipeline
        writer_configs = [
            {
                "task": "text2text-generation",
                "model": "google/flan-t5-small",
                "kwargs": {"max_new_tokens": 256},
            },
        ]
        for config in writer_configs:
            try:
                return pipeline(config["task"], model=config["model"], **config["kwargs"])
            except Exception:
                continue
    except ImportError:
        pass

    # If all else fails, return a dummy function that raises an error
    def dummy_writer(*args, **kwargs):
        raise LocalPolishUnavailable("No writing model available. Please ensure Ollama is running or transformers is installed.")
    
    return dummy_writer


def _extract_generated_text(result) -> str:
    if not result:
        return ""
    first = result[0]
    if "generated_text" in first:
        text = first["generated_text"]
        if isinstance(text, list):
            return "".join(part.get("content", "") for part in text if isinstance(part, dict))
        return str(text)
    return str(first)


def _clean_model_output(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:json)?", "", text).strip()
    text = re.sub(r"```$", "", text).strip()
    return text


def _normalize_sentence(text: str) -> str:
    text = re.sub(r"\s+", " ", (text or "")).strip(" .,-")
    if not text:
        return ""
    text = re.sub(r"^(and|so|then|because)\s+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\b(?:um|uh|like|you know|basically)\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip(" ,")
    if not text:
        return ""
    text = text[0].upper() + text[1:]
    if text[-1] not in ".!?":
        text += "."
    return text


def _rewrite_report_style(text: str, section: str = "summary") -> str:
    sentence = _normalize_sentence(text)
    if not sentence:
        return ""
    sentence = re.sub(r"^[,;\-\s]+", "", sentence)

    replacements = [
        (r"^We made some headway on\b", "Progress was made on"),
        (r"^We discussed\b", "The team discussed"),
        (r"^We covered\b", "The team reviewed"),
        (r"^We need to\b", "The team needs to"),
        (r"^We will\b", "The team will"),
        (r"^Let's\b", "The team agreed to"),
        (r"^I agree\b", "The team agreed"),
        (r"^Agreed\b", "The team agreed"),
        (r"^I agree,\s*let's\b", "The team agreed to"),
        (r"^I agree,\s*", "The team agreed that "),
        (r"^I'll\b", "It was assigned to"),
        (r"^I will\b", "It was assigned to"),
        (r"^I have\b", "It was noted that"),
        (r"^I've\b", "It was noted that"),
        (r"^Sounds good\b", "The team confirmed the approach"),
        (r"^Good idea\b", "The team accepted the proposal"),
        (r"^Good point\b", "The team acknowledged the concern"),
    ]
    for pattern, replacement in replacements:
        sentence = re.sub(pattern, replacement, sentence, flags=re.IGNORECASE)

    sentence = re.sub(r"\bwe\b", "the team", sentence, flags=re.IGNORECASE)
    sentence = re.sub(r"\bour\b", "the team's", sentence, flags=re.IGNORECASE)
    sentence = re.sub(r"\bi\b", "the speaker", sentence, flags=re.IGNORECASE)
    sentence = re.sub(r"\blet's\b", "the team agreed to", sentence, flags=re.IGNORECASE)
    sentence = re.sub(r"\bI'll\b", "It was assigned to", sentence, flags=re.IGNORECASE)
    sentence = re.sub(r"\bhowever,\b", "however", sentence, flags=re.IGNORECASE)

    if section == "discussion":
        sentence = re.sub(r"^The team discussed\s+", "", sentence, flags=re.IGNORECASE)
        sentence = re.sub(r"^Progress was made on\b", "progress on", sentence, flags=re.IGNORECASE)
        sentence = f"The discussion focused on {sentence[0].lower()}{sentence[1:]}" if sentence else sentence
    elif section == "decision":
        sentence = re.sub(r"^The team agreed,\s*", "", sentence, flags=re.IGNORECASE)
        sentence = re.sub(r"^The team agreed that\s+", "", sentence, flags=re.IGNORECASE)
        sentence = re.sub(r"^The team agreed to\s+", "", sentence, flags=re.IGNORECASE)
        sentence = re.sub(r"^The team agreed\s+", "", sentence, flags=re.IGNORECASE)
        sentence = f"The team decided to {sentence[0].lower()}{sentence[1:]}" if sentence else sentence
    elif section == "summary":
        if not re.search(r"\b(the meeting|the team|the discussion)\b", sentence, re.IGNORECASE):
            sentence = f"The meeting focused on {sentence[0].lower()}{sentence[1:]}"

    sentence = re.sub(r"\s+", " ", sentence).strip()
    sentence = re.sub(r"\s+\.", ".", sentence)
    if sentence and sentence[-1] not in ".!?":
        sentence += "."
    return sentence


def _polish_summary(summary: str, fallback_summary: str) -> str:
    base = summary or fallback_summary
    parts = [_rewrite_report_style(part, "summary") for part in re.split(r"(?<=[.!?])\s+", base) if part.strip()]
    parts = [part for part in parts if part]
    if not parts:
        parts = [_rewrite_report_style(fallback_summary, "summary")]
    polished = " ".join(parts[:4]).strip()
    return polished


def _polish_points(points: list[str], fallback_points: list[str], prefix: str) -> list[str]:
    source = points or fallback_points
    polished: list[str] = []
    seen = set()
    for point in source:
        section = "decision" if "decided" in prefix.lower() else "discussion"
        normalized = _rewrite_report_style(point, section)
        if not normalized:
            continue
        key = normalized.lower()
        if key not in seen:
            seen.add(key)
            polished.append(normalized)
    return polished[:5]


def _polish_action_items(items: list[dict], fallback_items: list[dict]) -> list[dict]:
    source = items or fallback_items
    polished: list[dict] = []
    seen = set()
    for item in source:
        task = _normalize_sentence(item.get("task", ""))
        if not task:
            continue
        task = re.sub(r"\.$", "", task)
        owner = (item.get("owner") or item.get("person") or "Unknown").strip() or "Unknown"
        deadline = (item.get("deadline") or "Unknown").strip() or "Unknown"
        notes = _normalize_sentence(item.get("notes", "")) if item.get("notes") else ""
        confidence = item.get("confidence", 0.7)
        key = (task.lower(), owner.lower(), deadline.lower())
        if key in seen:
            continue
        seen.add(key)
        polished.append(
            {
                "task": task,
                "owner": owner,
                "deadline": deadline,
                "notes": notes or "Follow up on this item.",
                "confidence": round(float(confidence), 2),
            }
        )
    return polished[:6]


def _polish_payload(payload: dict, fallback_summary: str, fallback_mom: dict) -> dict:
    payload = dict(payload or {})
    title = _normalize_sentence(payload.get("title", "")).rstrip(".") or "VoxIntel Local Meeting Report"
    payload["title"] = title
    payload["summary"] = _polish_summary(payload.get("summary", ""), fallback_summary)
    payload["discussion_points"] = _polish_points(
        payload.get("discussion_points", []),
        fallback_mom.get("discussion_points", []),
        "The discussion covered",
    ) or ["The discussion covered the main agenda items."]
    payload["decisions"] = _polish_points(
        payload.get("decisions", []),
        fallback_mom.get("decisions", []),
        "The team decided that",
    ) or ["No explicit decisions were confirmed."]
    fallback_items = [
        {
            "task": item.get("task", ""),
            "owner": item.get("person", "Unknown"),
            "deadline": item.get("deadline", "Unknown"),
            "notes": item.get("notes", ""),
        }
        for item in fallback_mom.get("action_items", [])
    ]
    payload["action_items"] = _polish_action_items(payload.get("action_items", []), fallback_items)
    return payload


def is_gemini_configured() -> bool:
    return False


def _build_writer_context(cleaned_text: str, fallback_summary: str, fallback_mom: dict) -> str:
    discussion_points = fallback_mom.get("discussion_points", [])[:6]
    decisions = fallback_mom.get("decisions", [])[:4]
    action_items = fallback_mom.get("action_items", [])[:5]
    action_lines = [
        f"task={item.get('task', 'Unknown')}; owner={item.get('person', 'Unknown')}; deadline={item.get('deadline', 'Unknown')}"
        for item in action_items
    ]
    compact_sentences = re.split(r"(?<=[.!?])\s+", cleaned_text)
    compact_excerpt = " ".join(sentence.strip() for sentence in compact_sentences[:8] if sentence.strip())[:2200]
    context_parts = [
        f"Draft summary: {fallback_summary}",
        "Draft discussion points: " + " | ".join(discussion_points or ["None detected"]),
        "Draft decisions: " + " | ".join(decisions or ["None detected"]),
        "Draft action items: " + " | ".join(action_lines or ["None detected"]),
        f"Selected transcript cues: {compact_excerpt}",
    ]
    return "\n".join(context_parts)


def generate_local_meeting_writeup(transcript: str, speaker_names: list[str] | None = None) -> dict:
    cleaned_text, sentences, tokens = clean_transcript(transcript)
    fallback_summary, _ = generate_summary(sentences, tokens, transcript=cleaned_text, method="rule_based")
    fallback_mom = generate_mom(transcript, fallback_summary)
    writer_context = _build_writer_context(cleaned_text, fallback_summary, fallback_mom)

    try:
        polished_sections = generate_mom_sections(writer_context)
        polished_summary = rewrite_summary(fallback_summary)
        payload = {
            "title": "VoxIntel Local Meeting Report",
            "summary": polished_summary or polished_sections.get("summary", fallback_summary),
            "discussion_points": polished_sections.get("discussion_points", fallback_mom["discussion_points"]),
            "decisions": polished_sections.get("decisions", fallback_mom["decisions"]),
            "action_items": polished_sections.get("action_items", []),
        }
    except LocalPolishUnavailable:
        try:
            writer = _get_writer_pipeline()
            prompt = (
                "You are a meeting assistant. Turn the meeting notes into polished third-person output. "
                "Do not copy dialogue. Rewrite it like professional meeting notes. "
                "Return valid JSON only with keys title, summary, discussion_points, decisions, action_items. "
                "The summary must be 2 to 4 crisp sentences. "
                "discussion_points and decisions must be short written statements, not transcript fragments. "
                "action_items must be an array of objects with task, owner, deadline, notes. "
                "Use Unknown if an owner or deadline is unclear. "
                f"Participants: {', '.join(speaker_names or ['Unknown'])}. "
                f"Schema example: {json.dumps(MEETING_SCHEMA_EXAMPLE)} "
                f"Meeting notes context: {writer_context[:2200]}"
            )
            result = _extract_generated_text(writer(prompt, do_sample=False))
            result = _clean_model_output(result)
            payload = json.loads(result)
        except Exception:
            payload = {
                "title": "VoxIntel Local Meeting Report",
                "summary": fallback_summary,
                "discussion_points": fallback_mom["discussion_points"],
                "decisions": fallback_mom["decisions"],
                "action_items": [
                    {
                        "task": item["task"],
                        "owner": item["person"],
                        "deadline": item["deadline"],
                        "notes": item["notes"],
                    }
                    for item in fallback_mom["action_items"]
                ],
            }

    payload = _polish_payload(payload, fallback_summary, fallback_mom)
    payload.setdefault("title", "VoxIntel Local Meeting Report")
    payload.setdefault("summary", fallback_summary)
    payload.setdefault("discussion_points", fallback_mom["discussion_points"])
    payload.setdefault("decisions", fallback_mom["decisions"])
    payload.setdefault(
        "action_items",
        [
            {
                "task": item["task"],
                "owner": item["person"],
                "deadline": item["deadline"],
                "notes": item["notes"],
            }
            for item in fallback_mom["action_items"]
        ],
    )
    return payload

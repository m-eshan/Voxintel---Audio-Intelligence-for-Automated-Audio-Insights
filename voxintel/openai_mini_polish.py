from __future__ import annotations

import json
import os
from pathlib import Path

from .exports import render_mom_html, render_mom_pdf
from .optimized_pipeline import OptimizedPipelineError, run_optimized_voxintel

DEFAULT_POLISH_MODEL = "gpt-4o-mini"


class OpenAIMiniPolishError(RuntimeError):
    """Raised when GPT-4o mini polishing cannot continue."""


BROKEN_LOCAL_PROXY_VALUES = {
    "http://127.0.0.1:9",
    "https://127.0.0.1:9",
}


def _load_project_env() -> None:
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _get_openai_client():
    _load_project_env()
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise OpenAIMiniPolishError("Set OPENAI_API_KEY in the environment or .env file to enable GPT-4o mini meeting polishing.")
    try:
        import httpx
        from openai import OpenAI
    except ImportError as exc:
        raise OpenAIMiniPolishError("The OpenAI SDK is not installed.") from exc
    # Ignore inherited dead local proxy settings so API requests can reach OpenAI.
    for proxy_key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        proxy_value = os.getenv(proxy_key, "").strip()
        if proxy_value.lower() in BROKEN_LOCAL_PROXY_VALUES:
            os.environ.pop(proxy_key, None)
    http_client = httpx.Client(trust_env=False, timeout=60.0)
    return OpenAI(api_key=api_key, http_client=http_client)


def _build_prompt(base_results: dict) -> str:
    transcript = base_results["transcript"][:12000]
    draft_summary = base_results["summary"]
    draft_mom = base_results["mom"]
    return (
        "You are a meeting analyst. Rewrite the draft output into a polished, concise meeting report. "
        "Return valid JSON only with keys: title, summary, discussion_points, decisions, action_items, risks, next_steps. "
        "Rules: summary must be 2-4 clear third-person sentences. discussion_points max 5. decisions max 3. "
        "action_items max 5 with fields task, owner, deadline, notes, confidence. Use Team if owner is unclear. "
        "Do not copy long raw transcript fragments.\n\n"
        f"Draft summary: {draft_summary}\n"
        f"Draft discussion points: {json.dumps(draft_mom.get('discussion_points', [])[:5])}\n"
        f"Draft decisions: {json.dumps(draft_mom.get('decisions', [])[:3])}\n"
        f"Draft action items: {json.dumps(draft_mom.get('action_items', [])[:5])}\n"
        f"Participants: {json.dumps(draft_mom.get('participants', []))}\n"
        f"Transcript excerpt: {transcript}"
    )


def _call_openai_mini(prompt: str) -> dict:
    client = _get_openai_client()
    try:
        response = client.chat.completions.create(
            model=DEFAULT_POLISH_MODEL,
            temperature=0.2,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": "Produce clean structured meeting JSON only."},
                {"role": "user", "content": prompt},
            ],
        )
        content = response.choices[0].message.content or "{}"
        payload = json.loads(content)
    except Exception as exc:
        raise OpenAIMiniPolishError(f"GPT-4o mini could not generate the polished meeting output. Details: {exc}") from exc
    if not isinstance(payload, dict):
        raise OpenAIMiniPolishError("GPT-4o mini returned an unexpected payload.")
    return payload


def polish_with_openai_mini(audio_path: str | Path, progress_callback=None) -> dict:
    try:
        if progress_callback:
            progress_callback(20, "Running local optimized transcription pipeline...")
        base_results = run_optimized_voxintel(audio_path, progress_callback=progress_callback)
    except OptimizedPipelineError as exc:
        raise OpenAIMiniPolishError(str(exc)) from exc

    if progress_callback:
        progress_callback(72, "Polishing summary and MoM with GPT-4o mini...")
    payload = _call_openai_mini(_build_prompt(base_results))

    polished_mom = {
        "participants": base_results["mom"].get("participants", ["Unknown"]),
        "meeting_date": base_results["mom"].get("meeting_date"),
        "overview": payload.get("summary", base_results["summary"]),
        "discussion_points": payload.get("discussion_points", base_results["mom"].get("discussion_points", []))[:5],
        "decisions": payload.get("decisions", base_results["mom"].get("decisions", []))[:3],
        "action_items": [
            {
                "task": item.get("task", "Unknown"),
                "person": item.get("owner", item.get("person", "Team")),
                "deadline": item.get("deadline", "Unknown"),
                "notes": item.get("notes", ""),
                "confidence": item.get("confidence", 0.7),
            }
            for item in payload.get("action_items", base_results["mom"].get("action_items", []))[:5]
        ],
        "cleaned_transcript": base_results["mom"].get("cleaned_transcript", ""),
        "risks": payload.get("risks", []),
        "next_steps": payload.get("next_steps", base_results["mom"].get("next_steps", [])),
        "speaker_highlights": base_results["mom"].get("speaker_highlights", []),
        "mom_markdown": payload.get("summary", base_results["summary"]),
        "title": payload.get("title", "VoxIntel GPT-4o mini Meeting Report"),
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
        "speaker_stats": base_results.get("speaker_activity", []),
    }

    base_results["summary"] = polished_mom["overview"]
    base_results["summary_engine"] = "gpt-4o-mini-polish"
    base_results["openai_polish_used"] = True
    base_results["openai_polish_error"] = ""
    base_results["mom"] = polished_mom
    base_results["html_report"] = render_mom_html(report_context)
    base_results["pdf_report"] = render_mom_pdf(report_context)
    return base_results

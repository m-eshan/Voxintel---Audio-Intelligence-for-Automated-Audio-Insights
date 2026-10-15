from __future__ import annotations

import json
import os
import re
from pathlib import Path
from urllib import request, error

from .exports import render_mom_html, render_mom_pdf
from .optimized_pipeline import OptimizedPipelineError, run_optimized_voxintel

DEFAULT_OLLAMA_HOST = "http://127.0.0.1:11434"
DEFAULT_OLLAMA_MODEL = "llama3.2:3b"


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
            for candidate in ["llama3.2:3b", "llama3.2", "gemma3:1b", "gemma3", "gemma2", "qwen2.5:0.5b", "qwen2.5", "phi3", "phi:latest", "mistral"]:
                for inst in installed:
                    if candidate in inst:
                        return host, inst
            if installed:
                return host, installed[0]
    except Exception:
        pass

    return host, DEFAULT_OLLAMA_MODEL


def resolve_speaker_mapping(segments: list[dict], attendees: list[str] | None = None) -> dict[str, str]:
    """Map anonymous Speaker clusters (Speaker 1, 2...) to real attendee names using conversational evidence."""
    if not attendees:
        return {}

    mapping: dict[str, str] = {}
    assigned_attendees: set[str] = set()
    clusters = sorted(list(set(s.get("speaker", "") for s in segments if s.get("speaker", "").startswith("Speaker"))))

    # 1. Direct self-introductions ("This is [Name]", "I am [Name]")
    for att in attendees:
        att_lower = att.lower()
        for s in segments:
            text_lower = (s.get("text") or "").lower()
            spk = s.get("speaker")
            if not spk or spk in mapping:
                continue
            if f"this is {att_lower}" in text_lower or f"i am {att_lower}" in text_lower or f"i'm {att_lower}" in text_lower:
                mapping[spk] = att
                assigned_attendees.add(att)
                break

    # 2. Conversational Adjacency Pairs:
    # A) "Thanks, [Name]" / "Thank you, [Name]" -> the PRECEDING turn belonged to [Name]
    for i, s in enumerate(segments):
        if i == 0:
            continue
        txt = (s.get("text") or "").lower()
        prev_spk = segments[i - 1].get("speaker")
        if not prev_spk or prev_spk in mapping:
            continue
        for att in attendees:
            if att in assigned_attendees:
                continue
            if re.search(rf"\b(?:thanks|thank you),?\s+{att.lower()}\b", txt):
                mapping[prev_spk] = att
                assigned_attendees.add(att)
                break

    # B) "[Name], what/how/can/could/is/are/do/did...?" -> the NEXT turn answering belongs to [Name]
    for i, s in enumerate(segments[:-1]):
        txt = (s.get("text") or "").lower()
        next_s = segments[i + 1]
        next_spk = next_s.get("speaker")
        if not next_spk or next_spk in mapping:
            continue
        next_txt = (next_s.get("text") or "").lower()
        for att in attendees:
            if att in assigned_attendees:
                continue
            if re.search(rf"\b{att.lower()},\s*(?:what|how|can|could|is|are|do|did|would|will)\b", txt):
                if any(next_txt.startswith(p) for p in ["i ", "i'll", "i will", "we ", "we'll", "from ", "the ", "over ", "yes", "sure", "thanks"]):
                    mapping[next_spk] = att
                    assigned_attendees.add(att)
                    break

    # 3. Cross-referencing conversational commitments:
    # E.g. Speaker A says: "Ravi handles support notifications, George patches login"
    # -> Speaker A is not Ravi and not George (it's the meeting chair/other attendee).
    # And the turn committing to support notifications belongs to Ravi!
    for s_third in segments:
        txt_third = (s_third.get("text") or "").lower()
        spk_third = s_third.get("speaker")
        
        # Check if speaker mentions multiple other attendees (chairperson pattern)
        mentions = [a for a in attendees if a.lower() in txt_third]
        if len(mentions) >= 2 and spk_third and spk_third not in mapping:
            chair_candidates = [a for a in attendees if a not in mentions and a not in assigned_attendees]
            if len(chair_candidates) == 1:
                mapping[spk_third] = chair_candidates[0]
                assigned_attendees.add(chair_candidates[0])

        for att in attendees:
            if att in assigned_attendees:
                continue
            att_lower = att.lower()
            m = re.findall(rf"\b{att_lower}\s+(?:will|handles|patches|is going to|takes|releases|completes)\s+([^.,;]+)", txt_third)
            for mention_context in m:
                mention_words = set(re.findall(r"[a-z]{3,}", mention_context))
                for s_first in segments:
                    spk_first = s_first.get("speaker")
                    if spk_first and spk_first != spk_third and spk_first not in mapping:
                        txt_first = (s_first.get("text") or "").lower()
                        if any(txt_first.startswith(p) for p in ["i'll", "i will", "i've", "i confirmed"]):
                            first_kw = set(re.findall(r"[a-z]{3,}", txt_first))
                            if len(mention_words & first_kw) >= 1:
                                mapping[spk_first] = att
                                assigned_attendees.add(att)
                                break

    # 4. Final 1-to-1 bijection if exactly 1 unmapped cluster and 1 unassigned attendee remains
    unmapped_clusters = [c for c in clusters if c not in mapping]
    unmapped_attendees = [a for a in attendees if a not in assigned_attendees]
    if len(unmapped_clusters) == 1 and len(unmapped_attendees) == 1:
        mapping[unmapped_clusters[0]] = unmapped_attendees[0]

    return mapping


def _build_hybrid_prompt(
    segments: list[dict],
    fast_mom: dict,
    attendees: list[str] | None = None,
    speaker_map: dict[str, str] | None = None,
) -> tuple[str, dict]:
    """Constructs prompt where rules extract structure and LLM only rewrites into third-person."""
    speaker_map = speaker_map or {}
    
    # 1. Format segments with explicit IDs [S1], [S2] and substituted real names
    labeled_turns = []
    for idx, s in enumerate(segments[:60], start=1):
        spk_raw = s.get("speaker", "Speaker")
        spk_name = speaker_map.get(spk_raw, spk_raw)
        s["display_speaker"] = spk_name
        s["seg_tag"] = f"S{idx}"
        labeled_turns.append(f"[{s['seg_tag']}] {spk_name}: {s.get('text', '')}")
    transcript_text = "\n".join(labeled_turns)

    # 2. Format rule-extracted decisions
    raw_decisions = fast_mom.get("decisions", [])
    extracted_decisions = []
    for d_idx, d in enumerate(raw_decisions, start=1):
        if isinstance(d, dict):
            dec_text = d.get("decision", "")
            spk = d.get("speaker", "Team")
            seg_id = d.get("seg_id", "")
        else:
            dec_text = str(d)
            spk = "Team"
            seg_id = ""
        spk_resolved = speaker_map.get(spk, spk)
        extracted_decisions.append({
            "id": f"D{d_idx}",
            "speaker": spk_resolved,
            "raw_text": dec_text,
            "original": d
        })

    # 3. Format rule-extracted action items
    raw_actions = fast_mom.get("action_items", [])
    extracted_actions = []
    for a_idx, a in enumerate(raw_actions, start=1):
        owner_raw = a.get("person", "Unassigned")
        owner_resolved = speaker_map.get(owner_raw, owner_raw)
        extracted_actions.append({
            "id": f"A{a_idx}",
            "owner": owner_resolved,
            "raw_task": a.get("task", ""),
            "deadline": a.get("deadline", "Not specified"),
            "original": a
        })

    # 4. Format key discussion segments
    raw_disc = fast_mom.get("discussion_points", [])
    extracted_points = []
    for p_idx, p in enumerate(raw_disc[:5], start=1):
        extracted_points.append({
            "id": f"P{p_idx}",
            "raw_text": str(p)
        })

    prompt_data = {
        "decisions": extracted_decisions,
        "action_items": extracted_actions,
        "discussion_points": extracted_points
    }

    attendees_str = ", ".join(attendees) if attendees else "Meeting participants"

    prompt = (
        "You are an executive meeting secretary. Rewrite the extracted meeting points into professional, formal THIRD-PERSON, PAST-TENSE meeting minutes.\n\n"
        "TRANSCRIPT SEGMENTS:\n"
        f"{transcript_text}\n\n"
        "EXTRACTED ITEMS TO POLISH (DO NOT INVENT NEW ITEMS, DO NOT ALTER OWNERS OR DEADLINES):\n"
        f"Attendees: [{attendees_str}]\n"
        "Decisions to polish:\n" + "\n".join(f"- [{d['id']}] ({d['speaker']}): {d['raw_text']}" for d in extracted_decisions) + "\n\n"
        "Action Items to polish:\n" + "\n".join(f"- [{a['id']}] ({a['owner']}): {a['raw_task']} (Deadline: {a['deadline']})" for a in extracted_actions) + "\n\n"
        "Discussion Points to polish:\n" + "\n".join(f"- [{p['id']}]: {p['raw_text']}" for p in extracted_points) + "\n\n"
        "STRICT INSTRUCTIONS:\n"
        "1. Do NOT invent roles (e.g. do NOT say 'executive team'), names, or facts not in the transcript.\n"
        "2. Keep the narrative strictly in formal THIRD-PERSON PAST TENSE. Never use I, we, me, or our.\n"
        "3. Rewrite each item into concise, professional third-person phrasing while preserving its exact meaning.\n"
        "4. Write an executive summary of 2 to 3 sentences strictly synthesizing the decisions and actions.\n"
        "5. Output valid JSON strictly conforming to this schema:\n"
        "{\n"
        '  "title": "Concise Descriptive Meeting Title",\n'
        '  "summary": "2 to 3 sentence executive summary strictly in third person past tense.",\n'
        '  "discussion_points": [{"id": "P1", "point": "Polished third-person text"}],\n'
        '  "decisions": [{"id": "D1", "decision": "Polished third-person text"}],\n'
        '  "action_items": [{"id": "A1", "task": "Polished third-person task description"}]\n'
        "}\n"
    )

    return prompt, prompt_data


def _call_ollama_json(prompt: str, host: str, model: str) -> dict:
    payload = {
        "model": model,
        "prompt": prompt,
        "format": "json",
        "stream": False,
        "options": {"temperature": 0.1, "num_predict": 1200, "top_p": 0.9},
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
            f"Please ensure Ollama is running (`ollama serve`) or use Fast Mode."
        ) from exc
    except Exception as exc:
        raise OllamaPolishError(f"Ollama generation failed: {exc}") from exc

    content = raw.get("response", "").strip()
    if not content:
        raise OllamaPolishError("Ollama returned an empty response.")

    try:
        return json.loads(content)
    except json.JSONDecodeError:
        # Fallback to search inside braces
        first_brace = content.find("{")
        last_brace = content.rfind("}")
        if first_brace != -1 and last_brace > first_brace:
            return json.loads(content[first_brace : last_brace + 1])
        raise OllamaPolishError("Failed to parse valid JSON from Ollama.")


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


def _reassemble_hybrid_mom(
    llm_payload: dict,
    prompt_data: dict,
    base_results: dict,
    attendees: list[str] | None = None,
    active_model: str = "ollama",
) -> dict:
    """Reassembles the MoM anchoring ground-truth timestamps and owners in code, with LLM wording."""
    
    # Map rewritten tasks by ID
    rewritten_actions = {a.get("id"): a.get("task", "") for a in llm_payload.get("action_items", []) if isinstance(a, dict)}
    rewritten_decisions = {d.get("id"): d.get("decision", "") for d in llm_payload.get("decisions", []) if isinstance(d, dict)}
    rewritten_points = {p.get("id"): p.get("point", "") for p in llm_payload.get("discussion_points", []) if isinstance(p, dict)}

    # 1. Final Action Items (Owners & Times anchored in code!)
    final_actions = []
    for item in prompt_data["action_items"]:
        item_id = item["id"]
        orig = item["original"]
        task_text = rewritten_actions.get(item_id) or item["raw_task"]
        # Clean formatting
        task_text = re.sub(r"^(ensure|please|to)\s+", "", task_text, flags=re.IGNORECASE).strip()
        task_text = task_text[0].upper() + task_text[1:] if task_text else item["raw_task"]
        
        final_actions.append({
            "task": task_text,
            "person": item["owner"],
            "deadline": item["deadline"],
            "time": orig.get("time", ""),
            "notes": orig.get("notes", ""),
            "confidence": orig.get("confidence", 0.9),
        })

    # 2. Final Decisions (Speaker & Times anchored in code!)
    final_decisions = []
    for item in prompt_data["decisions"]:
        item_id = item["id"]
        orig = item["original"]
        dec_text = rewritten_decisions.get(item_id) or item["raw_text"]
        dec_text = dec_text[0].upper() + dec_text[1:] if dec_text else item["raw_text"]
        
        time_str = f"[{orig.get('time')}] " if isinstance(orig, dict) and orig.get("time") else ""
        spk_str = f"{item['speaker']}: " if item['speaker'] and item['speaker'] != "Team" else ""
        final_decisions.append(f"{time_str}{spk_str}{dec_text}".strip())

    # 3. Final Discussion Points
    final_points = []
    for item in prompt_data["discussion_points"]:
        item_id = item["id"]
        pt_text = rewritten_points.get(item_id) or item["raw_text"]
        if pt_text.strip():
            final_points.append(pt_text.strip())

    summary_text = llm_payload.get("summary", "").strip() or base_results.get("summary", "")
    title_text = llm_payload.get("title", "").strip() or "VoxIntel Meeting Intelligence Report"

    return {
        "participants": attendees or base_results.get("mom", {}).get("participants", ["Unknown"]),
        "overview": summary_text,
        "discussion_points": final_points[:5],
        "decisions": final_decisions[:4],
        "action_items": final_actions[:5],
        "risks": [r if isinstance(r, str) else str(r) for r in llm_payload.get("risks", [])][:3],
        "next_steps": [n if isinstance(n, str) else str(n) for n in llm_payload.get("next_steps", [])][:3],
        "title": title_text,
        "active_model": active_model,
    }


def polish_results_with_ollama(
    base_results: dict,
    progress_callback=None,
    confidence_threshold: float = None,
    attendees: list[str] | None = None,
    speaker_mapping: dict[str, str] | None = None,
) -> dict:
    """Hybrid synthesis: Rules extract structure (times, owners), local LLM rewrites wording into 3rd person."""
    if progress_callback:
        progress_callback(75, "Synthesizing executive MoM with Ollama LLM...")

    host, active_model = _get_ollama_settings()
    segments = base_results.get("segments", [])
    fast_mom = base_results.get("mom", {})

    # Resolve speaker names before prompting
    resolved_speaker_map = dict(speaker_mapping or {})
    if not resolved_speaker_map and attendees:
        resolved_speaker_map = resolve_speaker_mapping(segments, attendees)

    # Conversational owner resolution on rule-extracted action items
    transcript_text = base_results.get("transcript", "")
    for item in fast_mom.get("action_items", []):
        current_person = item.get("person", "")
        if current_person in resolved_speaker_map:
            item["person"] = resolved_speaker_map[current_person]
        elif (current_person.startswith("Speaker") or current_person in {"Unassigned", "Team"}) and attendees:
            task_words = set(re.findall(r"[a-z]{3,}", item["task"].lower())) - {"and", "the", "for", "with", "about"}
            for att in attendees:
                m = re.findall(rf"\b{att.lower()}\s+(?:will|handles|patches|is going to|takes|releases|completes)\s+([^.,;]+)", transcript_text.lower())
                matched = False
                for mention_context in m:
                    mention_words = set(re.findall(r"[a-z]{3,}", mention_context))
                    if len(task_words & mention_words) >= 1:
                        item["person"] = att
                        matched = True
                        break
                if matched:
                    break

    prompt, prompt_data = _build_hybrid_prompt(segments, fast_mom, attendees=attendees, speaker_map=resolved_speaker_map)
    llm_payload = _call_ollama_json(prompt, host=host, model=active_model)

    if progress_callback:
        progress_callback(95, "Rendering polished reports...")

    polished_mom = _reassemble_hybrid_mom(llm_payload, prompt_data, base_results, attendees=attendees, active_model=active_model)

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
    base_results["summary_engine"] = f"Smart Mode (Ollama: {active_model})"
    base_results["active_model"] = active_model
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

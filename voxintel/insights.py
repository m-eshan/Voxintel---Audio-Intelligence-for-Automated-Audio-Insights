from __future__ import annotations

import re
from collections import Counter

import networkx as nx

from .ml import AISummaryUnavailable, generate_ai_summary
from .nlp import clean_sentences, clean_transcript, split_sentences, tokenize

ACTION_PATTERNS = [
    re.compile(
        r"(?i)^(?P<person>[A-Z][a-z]+(?:\s[A-Z][a-z]+)?)\s+(?:will|should|needs to|is going to)\s+(?P<task>.+?)(?:\s+by\s+(?P<deadline>[^.]+))?[.]?$"
    ),
    re.compile(
        r"(?i)^(?:i|we)\s+(?:will|should|need to|are going to)\s+(?P<task>.+?)(?:\s+by\s+(?P<deadline>[^.]+))?[.]?$"
    ),
    re.compile(
        r"(?i)^action item[:\-]?\s*(?P<person>[A-Z][a-z]+)?\s*(?:will|should|needs to)?\s*(?P<task>.+?)(?:\s+by\s+(?P<deadline>[^.]+))?[.]?$"
    ),
]

DECISION_PATTERN = re.compile(r"(?i)\b(decided|agreed|approved|finalized|confirmed)\b")
DECISION_STRONG_PATTERN = re.compile(r"(?i)\b(decided|approved|finalized|confirmed|moving forward|temporary workaround)\b")
DATE_PATTERN = re.compile(
    r"\b(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|"
    r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{1,2}(?:,\s*\d{4})?)\b",
    re.IGNORECASE,
)
SPEAKER_PATTERN = re.compile(r"(?m)^\s*([A-Z][a-z]+(?:\s[A-Z][a-z]+)?)\s*:")
SPEAKER_INLINE_PATTERN = re.compile(r"\b([A-Z][a-z]+(?:\s[A-Z][a-z]+)?)\s*:")
FULL_NAME_PATTERN = re.compile(r"\b([A-Z][a-z]+ [A-Z][a-z]+)\b")
TOPIC_CUE_PATTERN = re.compile(
    r"(?i)\b(issue|issues|bug|bugs|authentication|ui|design|release|timeline|deadline|demo|support|testing|review|fix|plan|notes|documentation)\b"
)
DEADLINE_PATTERN = re.compile(r"(?i)\b(by tomorrow|tomorrow|next week|next month|this week|today|by [A-Z][a-z]+day)\b")
WEAK_ACTION_PATTERN = re.compile(r"(?i)\b(we'?ll try|we'?ll ensure|sounds good|good idea|good point|maybe|should discuss|let'?s discuss)\b")
VAGUE_DECISION_PATTERN = re.compile(r"(?i)\b(maybe|might|should|let'?s discuss|perhaps|could)\b")
COMMON_FIRST_NAMES = {
    "alex","amy","andrew","anna","asha","ben","chris","christy","daniel","david","dove","eric","fabian",
    "gabe","george","jessica","john","josh","karina","kenny","meera","paul","rahul","scott","sid","virginia"
}


def infer_speaker_activity(transcript: str) -> list[dict[str, int]]:
    speaker_counts = Counter(SPEAKER_PATTERN.findall(transcript))
    return [{"speaker": speaker, "mentions": count} for speaker, count in speaker_counts.most_common()]


def normalize_for_summary(text: str) -> str:
    normalized = re.sub(r"\s+", " ", text).strip()
    normalized = SPEAKER_INLINE_PATTERN.sub("", normalized)
    normalized = re.sub(r"\b(today|hello everyone|good morning team)\b[:,]?", "", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\s+", " ", normalized).strip(" ,")
    return normalized


def _sentence_similarity(sentence_a: str, sentence_b: str) -> float:
    tokens_a = set(tokenize(sentence_a))
    tokens_b = set(tokenize(sentence_b))
    if not tokens_a or not tokens_b:
        return 0.0
    overlap = len(tokens_a & tokens_b)
    return overlap / max((len(tokens_a) * len(tokens_b)) ** 0.5, 1.0)


def _textrank_scores(sentences: list[str]) -> dict[int, float]:
    if len(sentences) <= 1:
        return {0: 1.0} if sentences else {}

    graph = nx.Graph()
    for index in range(len(sentences)):
        graph.add_node(index)
    for left in range(len(sentences)):
        for right in range(left + 1, len(sentences)):
            similarity = _sentence_similarity(sentences[left], sentences[right])
            if similarity > 0:
                graph.add_edge(left, right, weight=similarity)

    if graph.number_of_edges() == 0:
        return {index: 1.0 for index in range(len(sentences))}
    return nx.pagerank(graph, weight="weight")


def _generate_rule_based_summary(sentences: list[str], tokens: list[str]) -> str:
    if not sentences:
        return "No summary available because the transcript did not contain enough content."

    keyword_weights = Counter(tokens)
    textrank_scores = _textrank_scores(sentences)
    scored_sentences = _rank_sentences(_build_sentence_blocks(sentences), keyword_weights, textrank_scores, is_block=True)
    selected = _select_diverse_sentences(scored_sentences, max_sentences=min(4, len(scored_sentences)))
    ordered = [sentence for _, _, sentence, _ in sorted(selected, key=lambda item: item[1])]
    return _final_summary_pass(". ".join(sentence.strip(" .") for sentence in ordered if sentence.strip()))


def _build_sentence_blocks(sentences: list[str], block_size: int = 3) -> list[str]:
    if len(sentences) <= block_size:
        return sentences
    blocks: list[str] = []
    for index in range(0, len(sentences), block_size):
        block = " ".join(sentences[index : index + block_size]).strip()
        if block:
            blocks.append(block)
    return blocks


def _final_summary_pass(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\.\s+([a-z])", lambda m: ". " + m.group(1).upper(), text)
    text = re.sub(r"([A-Za-z])\s+([A-Z][a-z]+ed)\b", r"\1. \2", text)
    parts = split_sentences(text)
    deduped: list[str] = []
    seen = set()
    for part in parts:
        normalized = re.sub(r"\s+", " ", part).strip(" .")
        key = normalized.lower()
        if not normalized or key in seen:
            continue
        seen.add(key)
        normalized = normalized[0].upper() + normalized[1:]
        if normalized[-1] not in ".!?":
            normalized += "."
        deduped.append(normalized)
    return " ".join(deduped[:4])


def _rank_sentences(
    sentences: list[str],
    keyword_weights: Counter[str],
    textrank_scores: dict[int, float] | None = None,
    is_block: bool = False,
) -> list[tuple[float, int, str, set[str]]]:
    scored_sentences: list[tuple[float, int, str, set[str]]] = []

    for index, sentence in enumerate(sentences):
        sentence_tokens = tokenize(sentence)
        if not sentence_tokens:
            continue
        unique_tokens = {token for token in sentence_tokens if token in keyword_weights}
        token_score = sum(keyword_weights.get(token, 0) for token in sentence_tokens)
        position_bonus = max(0, 3 - index) * (1.0 if is_block else 1.5)
        sentence_length_penalty = 0.08 * max(0, len(sentence_tokens) - (42 if is_block else 26))
        cue_bonus = 4 if TOPIC_CUE_PATTERN.search(sentence) else 0
        diversity_bonus = len(unique_tokens) * 0.8
        keyword_component = token_score + position_bonus + cue_bonus + diversity_bonus - sentence_length_penalty
        textrank_component = (textrank_scores or {}).get(index, 0.0) * (12 if is_block else 10)
        score = 0.4 * keyword_component + 0.6 * textrank_component
        scored_sentences.append((score, index, sentence, unique_tokens))
    return scored_sentences


def _select_diverse_sentences(
    ranked_sentences: list[tuple[float, int, str, set[str]]],
    max_sentences: int,
) -> list[tuple[float, int, str, set[str]]]:
    selected: list[tuple[float, int, str, set[str]]] = []
    covered_tokens: set[str] = set()

    for candidate in sorted(ranked_sentences, reverse=True):
        _, _, sentence, tokens = candidate
        new_tokens = tokens - covered_tokens
        if selected and not new_tokens and len(sentence.split()) < 10:
            continue
        selected.append(candidate)
        covered_tokens.update(tokens)
        if len(selected) >= max_sentences:
            break
    return selected


def generate_summary(
    sentences: list[str],
    tokens: list[str],
    transcript: str = "",
    method: str = "rule_based",
) -> tuple[str, str]:
    normalized = normalize_for_summary(transcript) if transcript else ""
    if method == "ai":
        try:
            return generate_ai_summary(normalized), "ai"
        except AISummaryUnavailable:
            pass

    if normalized:
        normalized_sentences = clean_sentences(split_sentences(normalized))
        normalized_tokens = tokenize(normalized)
        return _generate_rule_based_summary(normalized_sentences, normalized_tokens), "rule_based"

    return _generate_rule_based_summary(sentences, tokens), "rule_based"


def extract_action_items(sentences: list[str]) -> list[dict[str, str]]:
    action_items: list[dict[str, str]] = []

    for sentence in sentences:
        stripped = sentence.strip()
        if WEAK_ACTION_PATTERN.search(stripped):
            continue
        if len(stripped.split()) > 24:
            continue
        matched_rule = False
        for pattern in ACTION_PATTERNS:
            match = pattern.match(stripped)
            if not match:
                continue
            task = (match.group("task") or "").strip(" .")
            if not task:
                continue
            if len(task.split()) < 3:
                continue
            matched_rule = True
            detected_person = (match.groupdict().get("person") or "").strip()
            if not detected_person and stripped.lower().startswith("we "):
                detected_person = "Team"
            action_items.append(
                {
                    "task": _clean_task(task),
                    "person": detected_person or "Team",
                    "deadline": _extract_deadline(stripped, match.group("deadline")),
                    "notes": "Rule-based extraction",
                    "confidence": _estimate_action_confidence(stripped, detected_person or "Team", match.group("deadline")),
                }
            )
            break

        if not matched_rule and any(
            trigger in stripped.lower() for trigger in ["follow up", "send", "prepare", "share", "complete"]
        ):
            if len(stripped.split()) <= 14 and not any(item["task"].lower() == stripped.lower().strip(" .") for item in action_items):
                action_items.append(
                    {
                        "task": _clean_task(stripped.strip(" .")),
                        "person": "Team",
                        "deadline": _extract_deadline(stripped, None),
                        "notes": "Detected from action-oriented phrasing",
                        "confidence": _estimate_action_confidence(stripped, "Team", None) - 0.15,
                    }
                )

    deduped: list[dict[str, str]] = []
    seen = set()
    for item in action_items:
        key = (item["task"].lower(), item["person"].lower(), item["deadline"].lower())
        if key not in seen:
            seen.add(key)
            deduped.append(item)
    return deduped


def _clean_task(task: str) -> str:
    task = re.sub(r"(?i)\b(please|just|really|promptly|carefully)\b", "", task)
    task = re.sub(r"\s+", " ", task).strip(" .,-")
    return task[0].upper() + task[1:] if task else ""


def _extract_deadline(sentence: str, fallback: str | None) -> str:
    if fallback:
        return fallback.strip(" .")
    match = DEADLINE_PATTERN.search(sentence)
    return match.group(0).strip(" .") if match else "Unknown"


def _estimate_action_confidence(sentence: str, person: str, deadline: str | None) -> float:
    confidence = 0.55
    if re.search(r"(?i)\bwill\b", sentence):
        confidence += 0.2
    if person and person != "Unknown":
        confidence += 0.1
    if deadline:
        confidence += 0.1
    if len(sentence.split()) > 10:
        confidence += 0.05
    return round(min(confidence, 0.95), 2)


def _validate_name(name: str) -> bool:
    parts = name.split()
    if not parts:
        return False
    return parts[0].lower() in COMMON_FIRST_NAMES


def _extract_participants(transcript: str) -> list[str]:
    participants = set(SPEAKER_PATTERN.findall(transcript))
    participants.update(name for name in FULL_NAME_PATTERN.findall(transcript) if _validate_name(name))
    if re.search(r"(?i)\bwe will\b|\bour team\b", transcript):
        participants.add("Team")
    if re.search(r"(?i)\bi will\b|\bi'll\b", transcript):
        participants.add("Speaker 1")
    participants = {participant.strip() for participant in participants if participant.strip()}
    return sorted(participants)[:8] or ["Unknown"]


def _extract_meeting_date(transcript: str) -> str | None:
    match = DATE_PATTERN.search(transcript)
    return match.group(0) if match else None


def _extract_discussion_points(sentences: list[str], summary: str) -> list[str]:
    keyword_weights = Counter(tokenize(" ".join(sentences)))
    ranked = _rank_sentences(sentences, keyword_weights, _textrank_scores(sentences))
    chosen = _select_diverse_sentences(ranked, max_sentences=5)
    discussion_points = [
        sentence
        for _, _, sentence, _ in sorted(chosen, key=lambda item: item[1])
        if not DECISION_PATTERN.search(sentence) and len(sentence.split()) <= 32
    ]
    if not discussion_points:
        summary_sentences = split_sentences(summary)
        discussion_points = [sentence for sentence in summary_sentences if len(sentence.split()) <= 32]
    return discussion_points[:5] or ["No key discussion points detected."]


def _extract_decisions(sentences: list[str]) -> list[str]:
    decisions = [
        sentence
        for sentence in sentences
        if len(sentence.split()) > 6
        and len(sentence.split()) <= 30
        and DECISION_STRONG_PATTERN.search(sentence)
        and not VAGUE_DECISION_PATTERN.search(sentence)
        and not ACTION_PATTERNS[0].match(sentence.strip())
    ]
    return decisions[:3] or ["No explicit decisions were detected."]


def generate_mom(transcript: str, summary: str) -> dict:
    cleaned_text, sentences, tokens = clean_transcript(transcript)
    _ = tokens
    action_items = extract_action_items(sentences)

    return {
        "participants": _extract_participants(transcript),
        "meeting_date": _extract_meeting_date(transcript),
        "discussion_points": _extract_discussion_points(sentences, summary),
        "decisions": _extract_decisions(sentences),
        "action_items": action_items,
        "cleaned_transcript": cleaned_text,
    }

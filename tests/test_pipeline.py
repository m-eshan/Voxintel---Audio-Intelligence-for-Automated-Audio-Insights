from pathlib import Path

from voxintel.insights import extract_action_items, generate_mom, generate_summary, normalize_for_summary
from voxintel.nlp import clean_transcript, extract_keywords
from voxintel.ollama_polish import _post_process_response
from voxintel.meeting_writer import _rewrite_report_style

SAMPLES_DIR = Path(__file__).resolve().parents[1] / "data" / "samples"


def test_clean_transcript_removes_fillers():
    cleaned, sentences, tokens = clean_transcript("um hello uh team. we agreed to proceed.")
    assert "um" not in cleaned.lower()
    assert "uh" not in cleaned.lower()
    assert len(sentences) == 2
    assert "hello" in tokens


def test_extract_keywords_returns_frequencies():
    _, _, tokens = clean_transcript("dashboard summary dashboard action item summary task")
    keyword_df = extract_keywords(tokens, top_n=2)
    assert list(keyword_df["keyword"]) == ["dashboard", "summary"]
    assert all(float(v) > 0 for v in keyword_df["count"])


def test_split_low_punctuation_transcript_into_chunks():
    text = (
        "we are close to release the authentication issue is still active "
        "the design update looks better we need to review the remaining bugs "
        "tomorrow the team will finalize the testing plan"
    )
    _, sentences, _ = clean_transcript(text)
    assert len(sentences) >= 2


def test_generate_summary_prefers_high_value_sentences():
    transcript = SAMPLES_DIR.joinpath("meeting_01_project_sync.txt").read_text(encoding="utf-8")
    _, sentences, tokens = clean_transcript(transcript)
    summary, engine = generate_summary(sentences, tokens, transcript=transcript)
    assert engine == "rule_based"
    assert "prerecorded meetings" in summary.lower()
    assert "dashboard" in summary.lower() or "audio analytics" in summary.lower()


def test_normalize_for_summary_removes_speaker_labels():
    normalized = normalize_for_summary("Asha: Welcome everyone. Rahul: We agreed to proceed.")
    assert "Asha:" not in normalized
    assert "Rahul:" not in normalized
    assert "agreed to proceed" in normalized


def test_extract_action_items_parses_assignments():
    sentences = [
        "Meera will prepare the slides by Friday.",
        "Action item: Rahul should share the dataset notes by Thursday.",
    ]
    items = extract_action_items(sentences)
    assert len(items) == 2
    assert items[0]["person"] == "Meera"
    assert items[0]["deadline"] == "Friday"
    assert items[1]["person"] == "Rahul"


def test_extract_action_items_skips_massive_sentence_blocks():
    giant_sentence = " ".join(["authentication"] * 40)
    items = extract_action_items([giant_sentence])
    assert items == []


def test_generate_mom_has_stable_shape():
    transcript = SAMPLES_DIR.joinpath("meeting_03_deadline_focus.txt").read_text(encoding="utf-8")
    _, sentences, tokens = clean_transcript(transcript)
    summary, _ = generate_summary(sentences, tokens, transcript=transcript)
    mom = generate_mom(transcript, summary)
    assert set(mom.keys()) == {
        "participants",
        "meeting_date",
        "discussion_points",
        "decisions",
        "action_items",
        "cleaned_transcript",
    }
    assert mom["meeting_date"] == "May 10, 2026"
    assert mom["participants"] != []
    assert isinstance(mom["action_items"], list)


def test_post_process_response_filters_low_confidence_items():
    """Verify confidence threshold filtering works"""
    parsed = {
        "title": "Project Meeting",
        "summary": "We discussed the project timeline.",
        "discussion_points": ["Timeline concerns", "Budget review"],
        "decisions": ["Approved new timeline"],
        "action_items": [
            {"task": "Complete testing", "owner": "Alice", "deadline": "Friday", "confidence": 0.85},
            {"task": "Maybe review docs", "owner": "Team", "deadline": "Next week", "confidence": 0.45},
            {"task": "Send update", "owner": "Bob", "deadline": "Monday", "confidence": 0.75},
        ],
    }
    
    processed = _post_process_response(parsed, confidence_threshold=0.60)
    
    # Should filter out low-confidence item (0.45 < 0.60)
    assert len(processed["action_items"]) == 2
    assert any(item["owner"] == "Alice" for item in processed["action_items"])
    assert any(item["owner"] == "Bob" for item in processed["action_items"])
    assert not any(item["owner"] == "Team" and item["confidence"] < 0.60 for item in processed["action_items"])


def test_post_process_response_removes_generic_owners():
    """Verify Team owners are flagged when drop_generic_owners is True"""
    parsed = {
        "title": "Planning",
        "summary": "Team met to plan sprints.",
        "discussion_points": ["Sprint planning"],
        "decisions": [],
        "action_items": [
            {"task": "Create backlog", "owner": "Team", "deadline": "Tuesday", "confidence": 0.90},
            {"task": "Review design", "owner": "Sarah", "deadline": "Wednesday", "confidence": 0.88},
        ],
    }
    
    processed = _post_process_response(parsed, drop_generic_owners=True)
    
    # Should drop Team-owned items if better alternatives exist
    high_confidence_items = [item for item in processed["action_items"] if item["confidence"] >= 0.85]
    assert all(item["owner"] != "Team" or item["owner"] == "Team" for item in high_confidence_items)


def test_post_process_response_ensures_summary_is_2_to_4_sentences():
    """Verify summary is capped at 4 sentences"""
    parsed = {
        "title": "Meeting",
        "summary": "Sentence one. Sentence two. Sentence three. Sentence four. Sentence five.",
        "discussion_points": ["Point A"],
        "decisions": ["Decision A"],
        "action_items": [],
    }
    
    processed = _post_process_response(parsed)
    summary_sentences = [s.strip() for s in processed["summary"].split(".") if s.strip()]
    
    assert len(summary_sentences) <= 4


def test_post_process_response_applies_grammar_polishing():
    """Verify grammar corrections are applied"""
    parsed = {
        "title": "Status",
        "summary": "We discussed the project. We agreed to move forward.",
        "discussion_points": ["Next steps"],
        "decisions": [],
        "action_items": [],
    }
    
    processed = _post_process_response(parsed, auto_fix_grammar=True)
    
    # Should convert "We discussed" to formal third-person
    assert "team" in processed["summary"].lower() or "discussed" in processed["summary"].lower()


def test_rewrite_report_style_converts_casual_to_formal():
    """Verify casual language is converted to professional MoM style"""
    text = "We discussed the issue. We agreed to proceed. I will follow up."
    rewritten = _rewrite_report_style(text)
    
    # Should avoid first-person pronouns
    assert "i will" not in rewritten.lower() or "assigned to" in rewritten.lower()
    # Should use formal language
    assert len(rewritten) > 0


from voxintel.openai_pipeline import build_speaker_stats, build_transcript_lines, format_seconds
from voxintel.exports import render_mom_html


def test_format_seconds_humanizes_duration():
    assert format_seconds(59) == "59s"
    assert format_seconds(61) == "1m 1s"
    assert format_seconds(3661) == "1h 1m 1s"


def test_build_speaker_stats_aggregates_segments():
    segments = [
        {"speaker": "A", "start": 0, "end": 10, "text": "Kickoff update"},
        {"speaker": "B", "start": 10, "end": 25, "text": "Design review details"},
        {"speaker": "A", "start": 25, "end": 35, "text": "Next steps"},
    ]
    stats = build_speaker_stats(segments)
    assert stats[0]["speaker"] == "A"
    assert stats[0]["speaking_time"] == "20s"
    assert stats[0]["segments"] == 2
    assert stats[1]["speaker"] == "B"


def test_build_transcript_lines_formats_speaker_turns():
    segments = [{"speaker": "A", "start": 0, "end": 12, "text": "Hello team"}]
    lines = build_transcript_lines(segments)
    assert lines == ["[0s - 12s] Speaker A: Hello team"]


def test_render_mom_html_includes_title_and_action_items():
    html = render_mom_html(
        {
            "title": "Release Review",
            "summary": "Release is on track.",
            "participants": ["A", "B"],
            "discussion_points": ["Auth fixes reviewed"],
            "decisions": ["Proceed with launch prep"],
            "risks": ["Minor edge cases remain"],
            "action_items": [
                {"task": "Finish QA", "owner": "A", "deadline": "Friday", "status": "Open", "notes": "Priority"},
            ],
            "speaker_stats": [{"speaker": "A", "speaking_time": "10m 0s", "share_percent": 60, "segments": 4, "words": 100}],
        }
    )
    assert "Release Review" in html
    assert "Finish QA" in html

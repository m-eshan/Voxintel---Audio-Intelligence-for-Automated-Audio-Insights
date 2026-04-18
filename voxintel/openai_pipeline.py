from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from .audio import _find_ffmpeg

MAX_OPENAI_AUDIO_BYTES = 24 * 1024 * 1024
DEFAULT_CHUNK_SECONDS = 12 * 60
MIN_CHUNK_SECONDS = 5 * 60
MAX_CHUNK_SECONDS = 15 * 60
DEFAULT_TRANSCRIBE_MODEL = "gpt-4o-transcribe-diarize"
DEFAULT_SUMMARY_MODEL = "gpt-4o"


class OpenAIPipelineError(RuntimeError):
    """Raised when the OpenAI meeting pipeline cannot continue."""


def _get_openai_client():
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise OpenAIPipelineError("Set OPENAI_API_KEY to enable long-form OpenAI meeting analysis.")

    try:
        from openai import OpenAI
    except ImportError as exc:
        raise OpenAIPipelineError("The OpenAI SDK is not installed. Install requirements to enable this pipeline.") from exc

    return OpenAI(api_key=api_key)


def _find_ffprobe() -> Path | None:
    ffmpeg_path = _find_ffmpeg()
    if ffmpeg_path:
        ffprobe_path = ffmpeg_path.with_name("ffprobe.exe")
        if ffprobe_path.exists():
            return ffprobe_path
    return None


def _run_subprocess(command: list[str], error_message: str) -> subprocess.CompletedProcess:
    try:
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
    except Exception as exc:  # pragma: no cover - environment-specific
        raise OpenAIPipelineError(error_message) from exc

    if completed.returncode != 0:
        stderr = (completed.stderr or "").strip().splitlines()
        detail = f" Details: {stderr[-1]}" if stderr else ""
        raise OpenAIPipelineError(error_message + detail)
    return completed


def get_audio_duration_seconds(audio_path: str | Path) -> float:
    ffprobe_path = _find_ffprobe()
    if not ffprobe_path:
        raise OpenAIPipelineError("ffprobe is required to inspect long audio files, but it was not found.")

    command = [
        str(ffprobe_path),
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "json",
        str(audio_path),
    ]
    completed = _run_subprocess(command, "VoxIntel could not inspect the uploaded audio file.")
    payload = json.loads(completed.stdout or "{}")
    duration = float(payload.get("format", {}).get("duration", 0))
    if duration <= 0:
        raise OpenAIPipelineError("The uploaded audio file did not report a valid duration.")
    return duration


def chunk_audio_for_openai(audio_path: str | Path, working_dir: Path) -> list[Path]:
    path = Path(audio_path)
    if path.stat().st_size <= MAX_OPENAI_AUDIO_BYTES:
        copied = working_dir / path.name
        shutil.copy2(path, copied)
        return [copied]

    ffmpeg_path = _find_ffmpeg()
    if not ffmpeg_path:
        raise OpenAIPipelineError("ffmpeg is required to split large audio files, but VoxIntel could not find it.")

    duration = get_audio_duration_seconds(path)
    bytes_per_second = max(path.stat().st_size / max(duration, 1), 1)
    estimated_chunk_seconds = math.floor((MAX_OPENAI_AUDIO_BYTES * 0.9) / bytes_per_second)
    chunk_seconds = max(MIN_CHUNK_SECONDS, min(MAX_CHUNK_SECONDS, estimated_chunk_seconds or DEFAULT_CHUNK_SECONDS))

    output_pattern = working_dir / "chunk_%03d.mp3"
    command = [
        str(ffmpeg_path),
        "-y",
        "-i",
        str(path),
        "-f",
        "segment",
        "-segment_time",
        str(chunk_seconds),
        "-c:a",
        "libmp3lame",
        "-b:a",
        "96k",
        str(output_pattern),
    ]
    _run_subprocess(command, "VoxIntel could not split the long audio file for OpenAI transcription.")
    chunks = sorted(working_dir.glob("chunk_*.mp3"))
    if not chunks:
        raise OpenAIPipelineError("Audio splitting finished, but no transcription chunks were created.")
    return chunks


def _payload_to_dict(payload) -> dict:
    if hasattr(payload, "model_dump"):
        return payload.model_dump()
    if isinstance(payload, dict):
        return payload
    return json.loads(json.dumps(payload, default=lambda obj: getattr(obj, "__dict__", str(obj))))


def transcribe_audio_chunks(
    audio_path: str | Path,
    progress_callback=None,
    language: str | None = None,
) -> dict:
    client = _get_openai_client()
    all_segments: list[dict] = []
    full_text_parts: list[str] = []
    total_duration = 0.0

    with tempfile.TemporaryDirectory() as temp_dir:
        chunk_paths = chunk_audio_for_openai(audio_path, Path(temp_dir))
        offset = 0.0

        for index, chunk_path in enumerate(chunk_paths, start=1):
            if progress_callback:
                progress_callback(
                    25 + int((index - 1) / max(len(chunk_paths), 1) * 35),
                    f"Transcribing chunk {index} of {len(chunk_paths)} with speaker diarization...",
                )

            with chunk_path.open("rb") as audio_file:
                response = client.audio.transcriptions.create(
                    model=DEFAULT_TRANSCRIBE_MODEL,
                    file=audio_file,
                    response_format="diarized_json",
                    language=language or None,
                )

            payload = _payload_to_dict(response)
            chunk_text = (payload.get("text") or "").strip()
            chunk_duration = float(payload.get("duration") or get_audio_duration_seconds(chunk_path))
            chunk_segments = payload.get("segments") or []

            for segment in chunk_segments:
                start = float(segment.get("start", 0)) + offset
                end = float(segment.get("end", 0)) + offset
                all_segments.append(
                    {
                        "id": segment.get("id", f"{index}-{len(all_segments)}"),
                        "speaker": segment.get("speaker", "Unknown"),
                        "start": round(start, 2),
                        "end": round(end, 2),
                        "text": (segment.get("text") or "").strip(),
                    }
                )

            if chunk_text:
                full_text_parts.append(chunk_text)

            offset += chunk_duration
            total_duration += chunk_duration

    transcript = " ".join(part for part in full_text_parts if part).strip()
    if not transcript:
        raise OpenAIPipelineError("OpenAI transcription completed, but no transcript text was returned.")

    return {
        "transcript": transcript,
        "segments": all_segments,
        "duration_seconds": total_duration,
    }


def format_seconds(total_seconds: float) -> str:
    seconds = max(0, int(round(total_seconds)))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes}m {secs}s"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def build_speaker_stats(segments: list[dict]) -> list[dict]:
    totals: dict[str, dict] = {}
    grand_total = 0.0

    for segment in segments:
        speaker = segment.get("speaker") or "Unknown"
        duration = max(0.0, float(segment.get("end", 0)) - float(segment.get("start", 0)))
        word_count = len((segment.get("text") or "").split())
        grand_total += duration

        speaker_bucket = totals.setdefault(
            speaker,
            {"speaker": speaker, "duration_seconds": 0.0, "segment_count": 0, "word_count": 0},
        )
        speaker_bucket["duration_seconds"] += duration
        speaker_bucket["segment_count"] += 1
        speaker_bucket["word_count"] += word_count

    rows = []
    for speaker, values in totals.items():
        share = (values["duration_seconds"] / grand_total * 100) if grand_total else 0
        rows.append(
            {
                "speaker": speaker,
                "speaking_time": format_seconds(values["duration_seconds"]),
                "duration_seconds": round(values["duration_seconds"], 2),
                "share_percent": round(share, 1),
                "segments": values["segment_count"],
                "words": values["word_count"],
            }
        )

    return sorted(rows, key=lambda item: item["duration_seconds"], reverse=True)


def build_transcript_lines(segments: list[dict], limit: int | None = None) -> list[str]:
    lines = []
    selected_segments = segments[:limit] if limit else segments
    for segment in selected_segments:
        speaker = segment.get("speaker", "Unknown")
        start = format_seconds(float(segment.get("start", 0)))
        end = format_seconds(float(segment.get("end", 0)))
        text = (segment.get("text") or "").strip()
        if text:
            lines.append(f"[{start} - {end}] Speaker {speaker}: {text}")
    return lines


def _chunk_transcript_lines(lines: list[str], max_chars: int = 7000) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []
    current_size = 0

    for line in lines:
        if current and current_size + len(line) + 1 > max_chars:
            chunks.append("\n".join(current))
            current = [line]
            current_size = len(line)
        else:
            current.append(line)
            current_size += len(line) + 1

    if current:
        chunks.append("\n".join(current))
    return chunks


def summarize_transcript_chunks(segments: list[dict], progress_callback=None) -> list[str]:
    client = _get_openai_client()
    transcript_chunks = _chunk_transcript_lines(build_transcript_lines(segments))
    notes: list[str] = []

    for index, chunk_text in enumerate(transcript_chunks, start=1):
        if progress_callback:
            progress_callback(
                62 + int((index - 1) / max(len(transcript_chunks), 1) * 12),
                f"Summarizing transcript chunk {index} of {len(transcript_chunks)}...",
            )

        response = client.responses.create(
            model=DEFAULT_SUMMARY_MODEL,
            input=[
                {
                    "role": "system",
                    "content": (
                        "You summarize meeting transcript excerpts into concise analytical notes. "
                        "Focus on topics, decisions, action items, blockers, and notable speaker contributions. "
                        "Do not restate the full conversation."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        "Summarize this diarized meeting excerpt into 5-8 compact bullet points. "
                        "Keep speaker references when useful.\n\n"
                        f"{chunk_text}"
                    ),
                },
            ],
        )
        notes.append((response.output_text or "").strip())

    return notes


def _meeting_schema() -> dict:
    return {
        "type": "json_schema",
        "name": "voxintel_meeting_analysis",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "title": {"type": "string"},
                "summary": {"type": "string"},
                "participants": {"type": "array", "items": {"type": "string"}},
                "discussion_points": {"type": "array", "items": {"type": "string"}},
                "decisions": {"type": "array", "items": {"type": "string"}},
                "risks": {"type": "array", "items": {"type": "string"}},
                "action_items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "task": {"type": "string"},
                            "owner": {"type": "string"},
                            "deadline": {"type": "string"},
                            "status": {"type": "string"},
                            "notes": {"type": "string"},
                        },
                        "required": ["task", "owner", "deadline", "status", "notes"],
                    },
                },
                "speaker_highlights": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "speaker": {"type": "string"},
                            "highlights": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["speaker", "highlights"],
                    },
                },
                "mom_markdown": {"type": "string"},
            },
            "required": [
                "title",
                "summary",
                "participants",
                "discussion_points",
                "decisions",
                "risks",
                "action_items",
                "speaker_highlights",
                "mom_markdown",
            ],
        },
    }


def generate_meeting_intelligence(
    transcript: str,
    segments: list[dict],
    speaker_stats: list[dict],
    meeting_context: str = "",
    progress_callback=None,
) -> dict:
    client = _get_openai_client()
    chunk_notes = summarize_transcript_chunks(segments, progress_callback=progress_callback)

    if progress_callback:
        progress_callback(78, "Generating executive summary and minutes of meeting...")

    transcript_excerpt = "\n".join(build_transcript_lines(segments, limit=80))
    response = client.responses.create(
        model=DEFAULT_SUMMARY_MODEL,
        input=[
            {
                "role": "system",
                "content": (
                    "You are an expert meeting analyst. Create concise, high-quality meeting intelligence. "
                    "Do not output raw conversation. Produce a polished summary, minutes of meeting, decisions, "
                    "and action items based on the evidence provided. If ownership or deadline is unclear, use 'Unknown'."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Meeting context:\n{meeting_context or 'No extra context provided.'}\n\n"
                    f"Speaker statistics:\n{json.dumps(speaker_stats, indent=2)}\n\n"
                    f"Chunk summaries:\n{json.dumps(chunk_notes, indent=2)}\n\n"
                    f"Transcript excerpt:\n{transcript_excerpt}\n\n"
                    "Generate a concise executive summary, minutes of meeting, decisions, risks, "
                    "speaker highlights, and action items. Keep discussion points short and useful."
                ),
            },
        ],
        text={"format": _meeting_schema()},
    )

    try:
        parsed = json.loads(response.output_text)
    except json.JSONDecodeError as exc:
        raise OpenAIPipelineError("OpenAI returned a meeting summary, but it was not valid JSON.") from exc

    parsed["chunk_notes"] = chunk_notes
    parsed["transcript"] = transcript
    return parsed


def analyze_meeting_audio(
    audio_path: str | Path,
    meeting_context: str = "",
    language: str | None = None,
    progress_callback=None,
) -> dict:
    transcription = transcribe_audio_chunks(audio_path, progress_callback=progress_callback, language=language)
    speaker_stats = build_speaker_stats(transcription["segments"])
    intelligence = generate_meeting_intelligence(
        transcript=transcription["transcript"],
        segments=transcription["segments"],
        speaker_stats=speaker_stats,
        meeting_context=meeting_context,
        progress_callback=progress_callback,
    )

    return {
        "transcript": transcription["transcript"],
        "segments": transcription["segments"],
        "duration_seconds": transcription["duration_seconds"],
        "speaker_stats": speaker_stats,
        "analysis": intelligence,
    }

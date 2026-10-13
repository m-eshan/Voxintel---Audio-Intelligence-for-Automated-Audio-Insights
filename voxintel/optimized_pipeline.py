from __future__ import annotations

import shutil
import subprocess
import tempfile
import wave
from pathlib import Path

import pandas as pd
import webrtcvad

from .audio import TranscriptionError, _find_ffmpeg, _prepare_audio_file, transcribe_local_whisper_segments
from .insights import generate_mom, generate_summary
from .nlp import clean_transcript, extract_keywords
from .openai_pipeline import get_audio_duration_seconds

DEFAULT_CHUNK_SECONDS = 60
MIN_VAD_CHUNK_SECONDS = 20
MAX_VAD_CHUNK_SECONDS = 40


class OptimizedPipelineError(RuntimeError):
    """Raised when the optimized VoxIntel pipeline cannot continue."""


def _run_subprocess(command: list[str], error_message: str) -> subprocess.CompletedProcess:
    try:
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
    except Exception as exc:
        raise OptimizedPipelineError(error_message) from exc
    if completed.returncode != 0:
        stderr = (completed.stderr or "").strip().splitlines()
        detail = f" Details: {stderr[-1]}" if stderr else ""
        raise OptimizedPipelineError(error_message + detail)
    return completed


def _write_wav_chunk(chunk_path: Path, sample_rate: int, audio_bytes: bytes) -> None:
    with wave.open(str(chunk_path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(audio_bytes)


def _vad_chunk_audio(audio_path: Path, working_dir: Path) -> list[Path]:
    vad = webrtcvad.Vad(1)
    frame_ms = 30
    with wave.open(str(audio_path), "rb") as wf:
        sample_rate = wf.getframerate()
        frame_size = int(sample_rate * frame_ms / 1000) * 2
        audio_bytes = wf.readframes(wf.getnframes())

    chunks: list[bytes] = []
    current = bytearray()
    silence_streak = 0
    min_bytes = sample_rate * 2 * MIN_VAD_CHUNK_SECONDS
    max_bytes = sample_rate * 2 * MAX_VAD_CHUNK_SECONDS

    for start in range(0, len(audio_bytes), frame_size):
        frame = audio_bytes[start : start + frame_size]
        if len(frame) < frame_size:
            continue
        is_speech = vad.is_speech(frame, sample_rate)
        current.extend(frame)
        if is_speech:
            silence_streak = 0
        else:
            silence_streak += 1

        if len(current) >= max_bytes or (len(current) >= min_bytes and silence_streak >= 8):
            chunks.append(bytes(current))
            current = bytearray()
            silence_streak = 0

    if current:
        chunks.append(bytes(current))

    written_chunks: list[Path] = []
    for index, chunk_bytes in enumerate(chunks, start=1):
        if len(chunk_bytes) < frame_size * 8:
            continue
        chunk_path = working_dir / f"opt_vad_chunk_{index:03d}.wav"
        _write_wav_chunk(chunk_path, sample_rate, chunk_bytes)
        written_chunks.append(chunk_path)
    return written_chunks


def chunk_audio(audio_path: str | Path, working_dir: Path, chunk_seconds: int = DEFAULT_CHUNK_SECONDS) -> list[Path]:
    path = Path(audio_path)
    duration = get_audio_duration_seconds(path)
    if duration <= chunk_seconds:
        copied = working_dir / path.name
        shutil.copy2(path, copied)
        return [copied]

    vad_chunks = _vad_chunk_audio(path, working_dir)
    if vad_chunks:
        return vad_chunks

    ffmpeg_path = _find_ffmpeg()
    if not ffmpeg_path:
        raise OptimizedPipelineError("ffmpeg is required to split audio in the optimized pipeline.")

    output_pattern = working_dir / "opt_chunk_%03d.wav"
    command = [
        str(ffmpeg_path),
        "-y",
        "-i",
        str(path),
        "-f",
        "segment",
        "-segment_time",
        str(chunk_seconds),
        "-acodec",
        "pcm_s16le",
        "-ar",
        "16000",
        "-ac",
        "1",
        str(output_pattern),
    ]
    _run_subprocess(command, "VoxIntel could not split the audio into optimized chunks.")
    chunks = sorted(working_dir.glob("opt_chunk_*.wav"))
    if not chunks:
        raise OptimizedPipelineError("Optimized chunking finished, but no audio chunks were created.")
    return chunks


def transcribe_chunks(chunk_paths: list[Path], progress_callback=None) -> tuple[str, list[dict]]:
    full_text_parts: list[str] = []
    all_segments: list[dict] = []
    offset = 0.0

    for index, chunk_path in enumerate(chunk_paths, start=1):
        if progress_callback:
            progress_callback(
                28 + int((index - 1) / max(len(chunk_paths), 1) * 34),
                f"Transcribing optimized chunk {index} of {len(chunk_paths)}...",
            )
        segments = transcribe_local_whisper_segments(chunk_path)
        chunk_duration = get_audio_duration_seconds(chunk_path)
        for seg_index, segment in enumerate(segments, start=1):
            text = (segment.get("text") or "").strip()
            if not text:
                continue
            full_text_parts.append(text)
            all_segments.append(
                {
                    "id": f"opt-{index}-{seg_index}",
                    "speaker": "Unknown",
                    "start": round(float(segment.get("start", 0.0)) + offset, 2),
                    "end": round(float(segment.get("end", 0.0)) + offset, 2),
                    "text": text,
                }
            )
        offset += chunk_duration

    transcript = " ".join(full_text_parts).strip()
    if not transcript:
        raise TranscriptionError("Optimized transcription finished, but no speech could be extracted from this file.")
    return transcript, all_segments


def run_optimized_voxintel(audio_file: str | Path, progress_callback=None, attendees: list[str] | None = None) -> dict:
    audio_path = Path(audio_file)
    try:
        prepared_audio = _prepare_audio_file(audio_path)
    except TranscriptionError:
        raise
    except Exception as exc:
        raise OptimizedPipelineError("VoxIntel could not preprocess the uploaded audio file.") from exc

    try:
        prepared_duration = get_audio_duration_seconds(prepared_audio)
        if progress_callback:
            progress_callback(30, "Transcribing audio with faster-whisper (fast whole-file VAD)...")

        # Fast direct transcription without splitting into 25 WAV files on disk
        segments = transcribe_local_whisper_segments(prepared_audio)
        transcript = " ".join(s["text"] for s in segments if s.get("text")).strip()
        if not transcript:
            raise TranscriptionError("Speech transcription finished, but no audible speech could be extracted.")

        if progress_callback:
            progress_callback(65, "Extracting meeting insights and generating MoM...")

        cleaned_text, sentences, tokens = clean_transcript(transcript)
        keyword_df = extract_keywords(cleaned_text)
        summary, _ = generate_summary(sentences, tokens, transcript=cleaned_text, method="rule_based")
        mom = generate_mom(transcript, summary, attendees=attendees)
        action_items = pd.DataFrame(mom["action_items"])

        return {
            "transcript": transcript,
            "segments": segments,
            "duration_seconds": prepared_duration,
            "summary": summary,
            "summary_engine": "optimized-lite-extractive",
            "keywords": keyword_df,
            "mom": {
                **mom,
                "overview": summary,
                "next_steps": [item["task"] for item in mom["action_items"][:4]],
                "title": "VoxIntel Optimized Meeting Report",
            },
            "speaker_activity": pd.DataFrame([{"speaker": "Unknown", "segments": len(segments)}]),
            "chunk_notes": [],
            "html_report": None,
            "pdf_report": None,
            "diarization_engine": "off",
            "action_items_table": action_items,
        }
    finally:
        if prepared_audio != audio_path and prepared_audio.exists():
            prepared_audio.unlink(missing_ok=True)
            try:
                prepared_audio.parent.rmdir()
            except OSError:
                pass

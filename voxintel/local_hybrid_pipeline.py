from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np

from .audio import _find_ffmpeg, transcribe_local_whisper_segments
from .exports import render_mom_html, render_mom_pdf
from .meeting_writer import generate_local_meeting_writeup
from .nlp import clean_transcript, extract_keywords
from .openai_pipeline import build_speaker_stats, get_audio_duration_seconds

DEFAULT_LOCAL_CHUNK_SECONDS = 10 * 60
LITE_LOCAL_CHUNK_SECONDS = 4 * 60
FAST_DIARIZATION_MAX_SEGMENTS = 80


class LocalHybridPipelineError(RuntimeError):
    """Raised when the local hybrid meeting pipeline cannot continue."""


def _run_subprocess(command: list[str], error_message: str) -> subprocess.CompletedProcess:
    try:
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
    except Exception as exc:
        raise LocalHybridPipelineError(error_message) from exc
    if completed.returncode != 0:
        stderr = (completed.stderr or "").strip().splitlines()
        detail = f" Details: {stderr[-1]}" if stderr else ""
        raise LocalHybridPipelineError(error_message + detail)
    return completed


def chunk_audio_for_local(audio_path: str | Path, working_dir: Path, chunk_seconds: int = DEFAULT_LOCAL_CHUNK_SECONDS) -> list[Path]:
    path = Path(audio_path)
    duration = get_audio_duration_seconds(path)
    if duration <= chunk_seconds:
        copied = working_dir / path.name
        shutil.copy2(path, copied)
        return [copied]

    ffmpeg_path = _find_ffmpeg()
    if not ffmpeg_path:
        raise LocalHybridPipelineError("ffmpeg is required to split long local audio files.")

    output_pattern = working_dir / "local_chunk_%03d.wav"
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
    _run_subprocess(command, "VoxIntel could not split the local audio file.")
    chunks = sorted(working_dir.glob("local_chunk_*.wav"))
    if not chunks:
        raise LocalHybridPipelineError("Local chunking completed, but no chunks were created.")
    return chunks


def _segments_from_whisper_chunk(audio_path: Path, offset_seconds: float) -> list[dict]:
    base_segments = transcribe_local_whisper_segments(audio_path)
    adjusted_segments: list[dict] = []
    for index, segment in enumerate(base_segments, start=1):
        adjusted_segments.append(
            {
                "id": f"{segment.get('id', f'whisper-{index}')}-{int(offset_seconds)}",
                "speaker": "Unknown",
                "start": round(float(segment.get("start", 0.0)) + offset_seconds, 2),
                "end": round(float(segment.get("end", 0.0)) + offset_seconds, 2),
                "text": (segment.get("text") or "").strip(),
            }
        )
    return adjusted_segments


def _try_pyannote_diarization(audio_path: Path) -> list[dict] | None:
    hf_token = os.getenv("HUGGINGFACE_TOKEN") or os.getenv("HF_TOKEN")
    if not hf_token:
        return None

    try:
        from pyannote.audio import Pipeline
    except Exception:
        return None

    try:
        pipeline = Pipeline.from_pretrained("pyannote/speaker-diarization-community-1", use_auth_token=hf_token)
        diarization = pipeline(str(audio_path))
    except Exception:
        return None

    segments = []
    for index, (turn, _, speaker) in enumerate(diarization.itertracks(yield_label=True)):
        segments.append(
            {
                "id": f"dia-{index}",
                "speaker": speaker,
                "start": round(float(turn.start), 2),
                "end": round(float(turn.end), 2),
                "text": "",
            }
        )
    return segments or None


def _try_resemblyzer_diarization(audio_path: Path) -> list[dict] | None:
    with contextlib.suppress(Exception):
        from resemblyzer import VoiceEncoder, preprocess_wav  # type: ignore
    return None


def _cluster_speakers_by_audio_features(
    audio_path: Path,
    transcript_segments: list[dict],
    fast_mode: bool = False,
) -> list[dict] | None:
    try:
        import librosa
        from sklearn.cluster import KMeans
        from sklearn.metrics import silhouette_score
    except Exception:
        return None

    try:
        samples, sr = librosa.load(str(audio_path), sr=16000, mono=True)
    except Exception:
        return None

    candidate_segments = transcript_segments[:FAST_DIARIZATION_MAX_SEGMENTS] if fast_mode else transcript_segments
    usable_segments: list[dict] = []
    feature_rows: list[np.ndarray] = []

    for segment in candidate_segments:
        start = max(0.0, float(segment.get("start", 0.0)))
        end = max(start + 0.2, float(segment.get("end", 0.0)))
        start_index = int(start * sr)
        end_index = int(end * sr)
        clip = samples[start_index:end_index]
        if clip.size < sr // 2:
            continue

        try:
            rms = librosa.feature.rms(y=clip)
            zero_cross = librosa.feature.zero_crossing_rate(y=clip)
            spectral_centroid = librosa.feature.spectral_centroid(y=clip, sr=sr)
            if fast_mode:
                pitch_track = librosa.yin(
                    clip,
                    fmin=librosa.note_to_hz("C2"),
                    fmax=librosa.note_to_hz("C5"),
                    frame_length=1024,
                )
                feature_vector = np.array(
                    [
                        float(np.median(pitch_track[np.isfinite(pitch_track)])) if np.isfinite(pitch_track).any() else 0.0,
                        float(np.mean(rms)),
                        float(np.mean(zero_cross)),
                        float(np.mean(spectral_centroid)),
                    ]
                )
            else:
                mfcc = librosa.feature.mfcc(y=clip, sr=sr, n_mfcc=13)
                pitch_track = librosa.yin(
                    clip,
                    fmin=librosa.note_to_hz("C2"),
                    fmax=librosa.note_to_hz("C6"),
                )
                pitch_track = pitch_track[np.isfinite(pitch_track)]
                pitch_value = float(np.median(pitch_track)) if pitch_track.size else 0.0
                feature_vector = np.concatenate(
                    [
                        np.mean(mfcc, axis=1),
                        np.array(
                            [
                                float(np.mean(spectral_centroid)),
                                float(np.mean(rms)),
                                float(np.mean(zero_cross)),
                                pitch_value,
                            ]
                        ),
                    ]
                )
        except Exception:
            continue

        feature_rows.append(feature_vector)
        usable_segments.append(segment)

    if len(usable_segments) < 3 or len(feature_rows) < 3:
        return None

    feature_matrix = np.vstack(feature_rows)
    max_speakers = min(4, len(usable_segments))
    best_labels = None
    best_score = -1.0

    for speaker_count in range(2, max_speakers + 1):
        try:
            model = KMeans(n_clusters=speaker_count, random_state=42, n_init=10)
            labels = model.fit_predict(feature_matrix)
            if len(set(labels)) < 2:
                continue
            score = silhouette_score(feature_matrix, labels)
            if score > best_score:
                best_score = score
                best_labels = labels
        except Exception:
            continue

    if best_labels is None:
        return None

    labeled_segments: list[dict] = []
    segment_to_label = {id(segment): f"Speaker {int(label) + 1}" for segment, label in zip(usable_segments, best_labels)}
    for segment in transcript_segments:
        labeled = dict(segment)
        labeled["speaker"] = segment_to_label.get(id(segment), labeled.get("speaker") or "Speaker 1")
        labeled_segments.append(labeled)
    return labeled_segments


def assign_speakers_to_transcript_segments(transcript_segments: list[dict], diarization_segments: list[dict] | None) -> list[dict]:
    if not diarization_segments:
        for segment in transcript_segments:
            segment["speaker"] = segment.get("speaker") or "Speaker 1"
        return transcript_segments

    assigned: list[dict] = []
    for segment in transcript_segments:
        start = float(segment.get("start", 0))
        end = float(segment.get("end", 0))
        best_speaker = "Unknown"
        best_overlap = 0.0
        for diar in diarization_segments:
            overlap = max(0.0, min(end, float(diar["end"])) - max(start, float(diar["start"])))
            if overlap > best_overlap:
                best_overlap = overlap
                best_speaker = diar.get("speaker", "Unknown")
        updated = dict(segment)
        updated["speaker"] = best_speaker
        assigned.append(updated)
    return assigned


def transcribe_audio_local_hybrid(
    audio_path: str | Path,
    progress_callback=None,
    diarization_mode: str = "off",
    lite_mode: bool = False,
) -> dict:
    path = Path(audio_path)
    total_duration = get_audio_duration_seconds(path)

    diarization_segments = None
    diarization_engine = "disabled"
    enable_diarization = diarization_mode != "off"
    if diarization_mode == "accurate" and (os.getenv("HUGGINGFACE_TOKEN") or os.getenv("HF_TOKEN")):
        diarization_segments = _try_pyannote_diarization(path)
        if diarization_segments:
            diarization_engine = "pyannote"
    if diarization_mode == "accurate" and not diarization_segments:
        diarization_segments = _try_resemblyzer_diarization(path)
        if diarization_segments:
            diarization_engine = "resemblyzer"

    with tempfile.TemporaryDirectory() as temp_dir:
        chunks = chunk_audio_for_local(
            path,
            Path(temp_dir),
            chunk_seconds=LITE_LOCAL_CHUNK_SECONDS if lite_mode else DEFAULT_LOCAL_CHUNK_SECONDS,
        )
        all_segments: list[dict] = []
        full_text_parts: list[str] = []
        offset = 0.0

        for index, chunk in enumerate(chunks, start=1):
            if progress_callback:
                progress_callback(
                    22 + int((index - 1) / max(len(chunks), 1) * 28),
                    f"Locally transcribing chunk {index} of {len(chunks)}...",
                )
            chunk_segments = _segments_from_whisper_chunk(chunk, offset)

            full_text_parts.extend(segment["text"] for segment in chunk_segments if segment.get("text"))
            all_segments.extend(chunk_segments)
            offset += get_audio_duration_seconds(chunk)

    assigned_segments = assign_speakers_to_transcript_segments(all_segments, diarization_segments)
    if diarization_mode == "fast":
        clustered_segments = _cluster_speakers_by_audio_features(path, assigned_segments, fast_mode=True)
        if clustered_segments:
            assigned_segments = clustered_segments
            diarization_engine = "fast-clustering"
    elif enable_diarization and not lite_mode and diarization_engine == "disabled":
        clustered_segments = _cluster_speakers_by_audio_features(path, assigned_segments, fast_mode=False)
        if clustered_segments:
            assigned_segments = clustered_segments
            diarization_engine = "pitch-clustering"
    transcript = " ".join(part for part in full_text_parts if part).strip()
    return {
        "transcript": transcript,
        "segments": assigned_segments,
        "duration_seconds": total_duration,
        "diarization_engine": diarization_engine if enable_diarization else "disabled",
    }


def _build_local_summary(transcript: str, progress_callback=None) -> tuple[dict, str]:
    cleaned_text, sentences, tokens = clean_transcript(transcript)
    return {
        "cleaned_text": cleaned_text,
        "sentences": sentences,
        "tokens": tokens,
        "summary": "",
    }, "local-meeting-writer"


def analyze_local_hybrid_meeting(
    audio_path: str | Path,
    meeting_context: str = "",
    progress_callback=None,
    diarization_mode: str = "off",
    lite_mode: bool = False,
) -> dict:
    transcription = transcribe_audio_local_hybrid(
        audio_path,
        progress_callback=progress_callback,
        diarization_mode=diarization_mode,
        lite_mode=lite_mode,
    )
    speaker_stats = build_speaker_stats(transcription["segments"])
    local_summary_bundle, local_summary_engine = _build_local_summary(transcription["transcript"], progress_callback=progress_callback)
    cleaned_text = local_summary_bundle["cleaned_text"]
    sentences = local_summary_bundle["sentences"]
    tokens = local_summary_bundle["tokens"]
    keyword_df = extract_keywords(tokens)
    if progress_callback:
        progress_callback(62, "Generating polished summary and MoM with fast local writer...")
    ai_writeup = generate_local_meeting_writeup(
        transcription["transcript"],
        speaker_names=[row["speaker"] for row in speaker_stats],
    )
    final_summary = ai_writeup["summary"]
    analysis_engine = "fast-local-polished-writer"
    mom_payload = {
        "title": ai_writeup["title"],
        "summary": final_summary,
        "participants": [row["speaker"] for row in speaker_stats] or ["Unknown"],
        "discussion_points": ai_writeup["discussion_points"],
        "decisions": ai_writeup["decisions"],
        "risks": [],
        "action_items": [
            {
                "task": item["task"],
                "owner": item["owner"],
                "deadline": item["deadline"],
                "status": "Open",
                "notes": item["notes"],
            }
            for item in ai_writeup["action_items"]
        ],
        "speaker_highlights": [
            {
                "speaker": row["speaker"],
                "highlights": [f"Spoke for {row['speaking_time']} across {row['segments']} segments."],
            }
            for row in speaker_stats
        ],
        "mom_markdown": final_summary,
        "chunk_notes": [],
    }
    action_items = mom_payload["action_items"]

    report_context = {
        "title": mom_payload.get("title", "VoxIntel Minutes of Meeting"),
        "summary": final_summary,
        "participants": mom_payload.get("participants", []),
        "discussion_points": mom_payload.get("discussion_points", []),
        "decisions": mom_payload.get("decisions", []),
        "risks": mom_payload.get("risks", []),
        "action_items": action_items,
        "speaker_stats": speaker_stats,
    }

    html_report = render_mom_html(report_context)
    pdf_report = render_mom_pdf(report_context)

    return {
        "transcript": transcription["transcript"],
        "segments": transcription["segments"],
        "duration_seconds": transcription["duration_seconds"],
        "speaker_stats": speaker_stats,
        "summary": final_summary,
        "summary_engine": analysis_engine,
        "keywords": keyword_df,
        "mom": {
            "participants": mom_payload.get("participants", []),
            "meeting_date": None,
            "overview": final_summary,
            "discussion_points": mom_payload.get("discussion_points", []),
            "decisions": mom_payload.get("decisions", []),
            "action_items": [
                {
                    "task": item["task"],
                    "person": item["owner"],
                    "deadline": item["deadline"],
                    "notes": f"{item.get('status', 'Open')}: {item.get('notes', '')}",
                }
                for item in action_items
            ],
            "cleaned_transcript": cleaned_text,
            "risks": mom_payload.get("risks", []),
            "next_steps": [item["task"] for item in action_items[:4]],
            "speaker_highlights": mom_payload.get("speaker_highlights", []),
            "mom_markdown": mom_payload.get("mom_markdown", ""),
            "title": mom_payload.get("title", "VoxIntel Local Meeting Report"),
        },
        "speaker_activity": speaker_stats,
        "chunk_notes": mom_payload.get("chunk_notes", []),
        "html_report": html_report,
        "pdf_report": pdf_report,
        "diarization_engine": transcription["diarization_engine"],
    }

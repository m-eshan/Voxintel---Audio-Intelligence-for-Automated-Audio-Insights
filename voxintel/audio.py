from __future__ import annotations

import contextlib
import json
import shutil
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path

SUPPORTED_AUDIO_EXTENSIONS = {".wav", ".mp3"}
SUPPORTED_TEXT_EXTENSIONS = {".txt"}
VOSK_MODEL_DIR = Path(__file__).resolve().parents[1] / "data" / "models" / "vosk-model-small-en-us-0.15"


class TranscriptionError(RuntimeError):
    """Raised when VoxIntel cannot transcribe an audio file."""


def validate_input_file(file_path: str | Path) -> Path:
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    if path.suffix.lower() not in SUPPORTED_AUDIO_EXTENSIONS | SUPPORTED_TEXT_EXTENSIONS:
        raise ValueError("Unsupported file type. Use .wav, .mp3, or .txt.")
    return path


def load_transcript(file_path: str | Path) -> str:
    path = validate_input_file(file_path)
    if path.suffix.lower() != ".txt":
        raise ValueError("Transcript loading expects a .txt file.")
    return path.read_text(encoding="utf-8").strip()


def _prepare_audio_file(path: Path) -> Path:
    ffmpeg_path = _find_ffmpeg()
    if not ffmpeg_path:
        raise TranscriptionError(
            "Audio preprocessing needs ffmpeg, but VoxIntel could not find it in this environment."
        )

    temp_dir = Path(tempfile.mkdtemp(prefix="voxintel_audio_"))
    temp_path = temp_dir / "decoded.wav"

    try:
        completed = _run_ffmpeg_decode(
            ffmpeg_path=ffmpeg_path,
            source_path=path,
            output_path=temp_path,
            enhance_audio=True,
        )
    except Exception as exc:  # pragma: no cover - environment-specific process failure
        temp_path.unlink(missing_ok=True)
        raise TranscriptionError(
            "VoxIntel could not start ffmpeg to preprocess this audio file."
        ) from exc

    if completed.returncode != 0 or not temp_path.exists() or temp_path.stat().st_size == 0:
        completed = _run_ffmpeg_decode(
            ffmpeg_path=ffmpeg_path,
            source_path=path,
            output_path=temp_path,
            enhance_audio=False,
        )

    if completed.returncode != 0 or not temp_path.exists() or temp_path.stat().st_size == 0:
        temp_path.unlink(missing_ok=True)
        temp_dir.rmdir()
        stderr_tail = (completed.stderr or "").strip().splitlines()[-1:] if completed.stderr else []
        detail = f" Details: {stderr_tail[0]}" if stderr_tail else ""
        raise TranscriptionError(
            "VoxIntel could not preprocess this audio file with ffmpeg." + detail
        )

    return temp_path


def _run_ffmpeg_decode(ffmpeg_path: Path, source_path: Path, output_path: Path, enhance_audio: bool) -> subprocess.CompletedProcess:
    command = [
        str(ffmpeg_path),
        "-y",
        "-i",
        str(source_path),
    ]
    if enhance_audio:
        command.extend(
            [
                "-af",
                "highpass=f=80,lowpass=f=3800,afftdn=nf=-20,dynaudnorm",
            ]
        )
    command.extend(
        [
            "-acodec",
            "pcm_s16le",
            "-ar",
            "16000",
            "-ac",
            "1",
            str(output_path),
        ]
    )
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
    )


def _find_ffmpeg() -> Path | None:
    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg:
        return Path(system_ffmpeg)

    candidate_paths = [
        Path(
            r"C:\Users\eshan\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.1-full_build\bin\ffmpeg.exe"
        ),
        Path.home()
        / "AppData"
        / "Local"
        / "Microsoft"
        / "WinGet"
        / "Packages"
        / "Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe"
        / "ffmpeg-8.1-full_build"
        / "bin"
        / "ffmpeg.exe",
    ]

    for candidate in candidate_paths:
        if candidate.exists():
            return candidate
    return None


def _transcribe_with_faster_whisper(wav_path: Path) -> str:
    segments = _transcribe_with_faster_whisper_segments(wav_path)
    transcript = " ".join(segment["text"] for segment in segments if segment.get("text")).strip()
    if not transcript:
        raise TranscriptionError(
            "Offline transcription finished, but no speech could be extracted from this file."
        )
    return transcript


def _build_meeting_initial_prompt(attendees: list[str] | None = None, custom_prompt: str | None = None) -> str:
    if custom_prompt:
        return custom_prompt
    parts = []
    if attendees:
        parts.append(f"Meeting participants: {', '.join(attendees)}.")
    parts.append(
        "Discussion regarding sprint planning, release readiness review, authentication bug, "
        "QA testing, login patch, workaround, customer support, deployment, and task action items."
    )
    return " ".join(parts)


def _transcribe_with_faster_whisper_segments(
    wav_path: Path,
    attendees: list[str] | None = None,
    initial_prompt: str | None = None,
    model_size: str = "base",
) -> list[dict]:
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise TranscriptionError(
            "Offline transcription is not available because faster-whisper is not installed."
        ) from exc

    try:
        model = _get_faster_whisper_model(model_size)
        prompt = _build_meeting_initial_prompt(attendees, initial_prompt)
        raw_segments, _ = model.transcribe(
            str(wav_path),
            beam_size=1,
            vad_filter=True,
            initial_prompt=prompt,
        )
        segments = [
            {
                "id": f"whisper-{index}",
                "speaker": "Unknown",
                "start": round(float(segment.start), 2),
                "end": round(float(segment.end), 2),
                "text": segment.text.strip(),
            }
            for index, segment in enumerate(raw_segments, start=1)
            if segment.text and segment.text.strip()
        ]
    except Exception as exc:  # pragma: no cover - first-run model download/runtime environment specific
        if "paging file is too small" in str(exc).lower() or "mkl_malloc" in str(exc).lower():
            raise TranscriptionError(
                "Offline Whisper could not start because Windows is low on memory or paging-file space."
            ) from exc
        raise TranscriptionError(
            "Offline speech transcription failed while loading the local Whisper model."
        ) from exc

    if not segments:
        raise TranscriptionError(
            "Offline transcription finished, but no speech could be extracted from this file."
        )

    return segments


@lru_cache(maxsize=4)
def _get_faster_whisper_model(model_size: str = "base"):
    from faster_whisper import WhisperModel

    try:
        return WhisperModel(model_size, device="cpu", compute_type="int8", cpu_threads=4)
    except Exception:
        return WhisperModel("tiny", device="cpu", compute_type="int8")


@lru_cache(maxsize=1)
def _get_openai_whisper_model():
    import whisper

    return whisper.load_model("tiny.en")


def _transcribe_with_openai_whisper_segments(wav_path: Path) -> list[dict]:
    try:
        _get_openai_whisper_model
    except ImportError as exc:
        raise TranscriptionError(
            "Offline transcription is not available because the local Whisper package is not installed."
        ) from exc

    try:
        model = _get_openai_whisper_model()
        result = model.transcribe(str(wav_path), fp16=False, verbose=False)
        raw_segments = result.get("segments") or []
        segments = [
            {
                "id": f"owh-{index}",
                "speaker": "Unknown",
                "start": round(float(segment.get("start", 0.0)), 2),
                "end": round(float(segment.get("end", 0.0)), 2),
                "text": (segment.get("text") or "").strip(),
            }
            for index, segment in enumerate(raw_segments, start=1)
            if (segment.get("text") or "").strip()
        ]
    except Exception as exc:
        if "paging file is too small" in str(exc).lower() or "llvmlite" in str(exc).lower():
            raise TranscriptionError(
                "Offline Whisper fallback could not start because Windows is low on memory or paging-file space."
            ) from exc
        raise TranscriptionError(
            "Offline speech transcription failed while loading the local Whisper fallback model."
        ) from exc

    if not segments:
        raise TranscriptionError(
            "Offline transcription finished, but no speech could be extracted from this file."
        )
    return segments


def _transcribe_with_sphinx_segments(wav_path: Path) -> list[dict]:
    try:
        import speech_recognition as sr
    except ImportError as exc:
        raise TranscriptionError(
            "Offline fallback transcription is not available because SpeechRecognition is not installed."
        ) from exc

    recognizer = sr.Recognizer()
    try:
        with sr.AudioFile(str(wav_path)) as source:
            audio_data = recognizer.record(source)
        transcript = recognizer.recognize_sphinx(audio_data)
    except Exception as exc:
        raise TranscriptionError(
            "The lightweight offline speech fallback could not transcribe this file."
        ) from exc

    transcript = transcript.strip()
    if not transcript:
        raise TranscriptionError(
            "Offline fallback transcription finished, but no speech could be extracted from this file."
        )
    return [
        {
            "id": "sphinx-1",
            "speaker": "Unknown",
            "start": 0.0,
            "end": 0.0,
            "text": transcript,
        }
    ]


def transcribe_local_whisper_only(file_path: str | Path) -> str:
    path = validate_input_file(file_path)
    wav_path = _prepare_audio_file(path)
    try:
        return _transcribe_with_faster_whisper(wav_path).strip()
    finally:
        if wav_path != path and wav_path.exists():
            wav_path.unlink(missing_ok=True)
            with contextlib.suppress(OSError):
                wav_path.parent.rmdir()


def transcribe_local_whisper_segments(
    file_path: str | Path,
    attendees: list[str] | None = None,
    initial_prompt: str | None = None,
) -> list[dict]:
    path = validate_input_file(file_path)
    if path.suffix.lower() == ".wav":
        wav_path = path
        should_cleanup = False
    else:
        wav_path = _prepare_audio_file(path)
        should_cleanup = True

    try:
        try:
            return _transcribe_with_faster_whisper_segments(wav_path, attendees=attendees, initial_prompt=initial_prompt)
        except TranscriptionError:
            try:
                return _transcribe_with_openai_whisper_segments(wav_path)
            except TranscriptionError:
                return _transcribe_with_sphinx_segments(wav_path)
    finally:
        if should_cleanup and wav_path != path and wav_path.exists():
            wav_path.unlink(missing_ok=True)
            with contextlib.suppress(OSError):
                wav_path.parent.rmdir()


def _transcribe_with_vosk(wav_path: Path) -> str:
    try:
        import wave

        from vosk import KaldiRecognizer, Model
    except ImportError as exc:
        raise TranscriptionError(
            "Offline transcription is not available because Vosk is not installed."
        ) from exc

    if not VOSK_MODEL_DIR.exists():
        raise TranscriptionError(
            "Offline transcription is not available because the Vosk model is missing."
        )

    try:
        wf = wave.open(str(wav_path), "rb")
    except Exception as exc:
        raise TranscriptionError(
            "VoxIntel could not open the decoded WAV file for offline transcription."
        ) from exc

    try:
        recognizer = KaldiRecognizer(Model(str(VOSK_MODEL_DIR)), wf.getframerate())
        recognizer.SetWords(True)
        segments: list[str] = []

        while True:
            data = wf.readframes(4000)
            if len(data) == 0:
                break
            if recognizer.AcceptWaveform(data):
                result = json.loads(recognizer.Result())
                text = result.get("text", "").strip()
                if text:
                    segments.append(text)

        final_result = json.loads(recognizer.FinalResult())
        final_text = final_result.get("text", "").strip()
        if final_text:
            segments.append(final_text)
    finally:
        wf.close()

    transcript = " ".join(segments).strip()
    if not transcript:
        raise TranscriptionError(
            "Offline transcription finished, but no speech could be extracted from this file."
        )
    return transcript


def transcribe_local_prefer_whisper(file_path: str | Path) -> str:
    path = validate_input_file(file_path)
    wav_path = _prepare_audio_file(path)
    try:
        try:
            return _transcribe_with_faster_whisper(wav_path).strip()
        except TranscriptionError:
            return _transcribe_with_vosk(wav_path).strip()
    finally:
        if wav_path != path and wav_path.exists():
            wav_path.unlink(missing_ok=True)
            with contextlib.suppress(OSError):
                wav_path.parent.rmdir()


def process_audio(file_path: str | Path) -> str:
    path = validate_input_file(file_path)
    if path.suffix.lower() == ".txt":
        return load_transcript(path)

    try:
        import speech_recognition as sr
    except ImportError as exc:
        raise TranscriptionError(
            "SpeechRecognition is not installed. Install requirements or use a transcript sample."
        ) from exc

    wav_path = _prepare_audio_file(path)
    try:
        try:
            transcript = _transcribe_with_vosk(wav_path)
        except TranscriptionError:
            try:
                transcript = _transcribe_with_faster_whisper(wav_path)
            except TranscriptionError:
                recognizer = sr.Recognizer()
                try:
                    with sr.AudioFile(str(wav_path)) as source:
                        audio_data = recognizer.record(source)
                    transcript = recognizer.recognize_google(audio_data)
                except sr.UnknownValueError as exc:
                    raise TranscriptionError(
                        "VoxIntel could not understand this audio clearly. Try a cleaner recording."
                    ) from exc
                except sr.RequestError as exc:
                    raise TranscriptionError(
                        "Offline Vosk, offline Whisper, and the online Google recognizer were all unavailable for this audio file."
                    ) from exc
                except Exception as exc:
                    raise TranscriptionError(
                        "Audio processing failed after decoding the file. Try a clearer recording."
                    ) from exc
    finally:
        if wav_path != path and wav_path.exists():
            wav_path.unlink(missing_ok=True)
            with contextlib.suppress(OSError):
                wav_path.parent.rmdir()

    return transcript.strip()

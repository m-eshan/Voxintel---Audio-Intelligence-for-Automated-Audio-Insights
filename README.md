# VoxIntel

VoxIntel is a beginner-friendly Streamlit project that turns meeting audio or sample transcripts into structured meeting intelligence.

## Features

- Upload `.wav` / `.mp3` meeting audio for transcription
- Use bundled synthetic meeting samples for deterministic demos
- Use an OpenAI long-meeting pipeline for chunked diarized transcription and structured meeting intelligence
- Clean transcripts and remove filler words
- Extract top keywords and basic speaker activity
- Generate a rule-based summary or an AI-assisted summary
- Produce Minutes of Meeting with action items
- Visualize results in a polished Streamlit dashboard

## Quick start

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
set OPENAI_API_KEY=your_key_here
streamlit run app.py
```

Optional local diarization extras:

```bash
pip install -r requirements-optional.txt
```

## Project structure

- `app.py`: Streamlit dashboard
- `voxintel/audio.py`: audio intake and transcription helpers
- `voxintel/nlp.py`: transcript cleaning and keyword extraction
- `voxintel/insights.py`: summary, MoM, and action-item heuristics
- `voxintel/ml.py`: optional transformer summarization helpers
- `voxintel/openai_pipeline.py`: chunked OpenAI transcription, diarization, speaker analytics, and structured meeting synthesis
- `voxintel/local_hybrid_pipeline.py`: local chunked transcription, optional pyannote diarization, and hybrid report generation
- `voxintel/exports.py`: Jinja2 HTML and PDF export helpers
- `data/samples/`: synthetic meeting transcripts used for demos and tests
- `tests/`: unit tests for core processing

## Notes

- Audio transcription depends on `SpeechRecognition`. `.mp3` files are converted to `.wav` when `pydub` is available.
- The recommended path for real meeting audio is the OpenAI long-meeting pipeline, which uses diarized transcription plus GPT-generated summary and MoM.
- The hybrid local AI pipeline attempts local Whisper-style transcription first, then optional pyannote diarization when a Hugging Face token is available.
- AI summarization uses Hugging Face `transformers` when available locally. If the model or dependency is missing, VoxIntel falls back to the built-in rule-based summary.
- If live transcription fails in your environment, the app still supports transcript-file testing and bundled meeting samples.

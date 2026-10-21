# VoxIntel: Audio Intelligence & Meeting Synthesizer

VoxIntel is an offline-first, local meeting intelligence platform designed to transcribe multi-speaker audio recordings, cluster acoustic speaker turns, and synthesize professional, third-person Minutes of Meeting (MoM) on consumer hardware (such as an 8 GB RAM CPU laptop) without cloud API dependencies or recurring costs.

---

## Architecture Overview

VoxIntel features a streamlined dual-pipeline architecture designed specifically for low-latency, deterministic local execution:

```
                      +-----------------------------+
                      |   Meeting Audio (.mp3/.wav) |
                      +--------------+--------------+
                                     |
                                     v
                 +---------------------------------------+
                 | faster-whisper base (int8 + VAD)     |
                 | Whole-file fast direct transcription  |
                 +-------------------+-------------------+
                                     |
                                     v
                 +---------------------------------------+
                 | Acoustic Feature Clustering           |
                 | MFCC + Spectral Centroid + Yin F0     |
                 | Unsupervised KMeans (<1s on CPU)      |
                 +-------------------+-------------------+
                                     |
               +---------------------+---------------------+
               |                                           |
               v                                           v
    +-----------------------+                 +--------------------------+
    |   FAST MODE           |                 |   SMART MODE             |
    |   (Zero external LLM) |                 |   (Local Ollama LLM)     |
    +-----------------------+                 +--------------------------+
    | - TextRank key moments|                 | - llama3.2:3b / gemma3:1b|
    | - Speaker-attributed  |                 | - Strict 3rd-person MoM  |
    |   action items        |                 | - Timestamp citations    |
    | - Heuristic deadlines |                 | - Attendee verification  |
    +-----------------------+                 +--------------------------+
```

### 1. Fast Mode (Whisper + TextRank)
* **Transcription**: Powered by `faster-whisper` (`base` model, `int8` quantization) with Silero voice activity detection (`vad_filter=True`). Eliminates disk-heavy WAV chunking, processing whole-file audio directly in memory.
* **Speaker Labeling**: Extracts 13 MFCCs, zero-crossing rate, RMS energy, spectral centroid, and Yin fundamental pitch ($F_0$) per speech segment, followed by KMeans clustering ($k$ set by attendee count or silhouette optimization).
* **Extraction**: TextRank sentence graph ranking extracts key moments formatted as `[mm:ss] Speaker: line`. Action items match verbal commitments (`I'll`, `will`, `agreed to`) attributed directly to the segment's speaker with normalized deadlines (`PM`/`AM`).

### 2. Smart Mode (Whisper + Ollama LLM)
* **Engine**: Integrates with a local [Ollama](https://ollama.com/) instance (`llama3.2:3b`, `gemma3:1b`, or `phi3`).
* **Third-Person Synthesis**: Produces formal past-tense minutes (e.g., *"George committed to finalizing the login patch by Friday at 5 PM"*). Prohibits first-person pronouns (`I`, `we`, `our`).
* **Timestamp Grounding**: Every discussion point, decision, and action item cites the exact timestamp (`[mm:ss]`) from the transcript.
* **Attendee List Validation**: Action item owners are strictly validated against user-entered attendees. Any unverified or generic reference is labeled as `"Unassigned"` to prevent false attribution.

---

## Benchmark & Evaluation Summary

VoxIntel was evaluated across a standardized test battery comprising two development meetings and one held-out test meeting. See [`docs/results_tables.md`](docs/results_tables.md) for full raw tables.

### Key Results Summary

| Benchmark Metric | Dev Set: Meeting 1 (50s) | Dev Set: Meeting 2 (193s) | Test Set: Meeting 3 (323s) |
| :--- | :--- | :--- | :--- |
| **ASR WER (`base` + domain prompt)** | **3.48%** (vs 7.83% tiny) | **8.87%** (vs 11.27% tiny) | **5.58%** (vs 10.32% tiny) |
| **ASR Latency (`base` on CPU)** | 6.17s | 14.12s | 19.90s (~0.06x RTF) |
| **Speaker Attribution Accuracy (KMeans)** | 63.00% | 70.73% | 58.11% (Hungarian remap) |
| **Action Items F1 Score (Fast Mode)** | 1.0000 | 1.0000 | 0.7500 (Recall 1.0000) |
| **Action Items F1 Score (Smart Mode)** | 1.0000 | 0.9091 | 0.7500 (Recall 1.0000) |
| **Summary 1st-Person Pronoun Count** | **0** (Smart MoM) | **0** (Smart MoM) | **0** (Smart MoM) |

---

## Known Limitations & Honest Technical Trade-offs

1. **Acoustic Vocal Tract Clustering on Short Turns**:
   Unsupervised clustering using 13 MFCCs and Yin pitch relies on sufficient audio frames. Very short conversational turns (<1.5s, e.g., "Approved", "Agreed", "Looking into it") lack sufficient spectral stability and can occasionally be misclustered.
2. **Zero-Shot Grounding Collapse**:
   Conversational adjacency grounding relies on spoken cues ("This is Sarah", "Thanks, George"). In meetings where participants do not speak attendee names aloud (as evaluated in Meeting 3), automated name grounding collapses, requiring the user to map cluster labels to names in the UI.
3. **Small-Model LLM Drift**:
   Lightweight local LLMs (1B–3B parameters) are prone to subtle drift when summarizing long technical contexts, occasionally merging separate decisions with action item deadlines or hallucinating generic framing. VoxIntel anchors these models using strict JSON schema prompting and post-validation against deterministic Fast Mode extractions.

---

## Installation & Setup

### 1. Prerequisites
* Python 3.10 or higher
* FFmpeg installed and available on system `PATH`
* Optional: [Ollama](https://ollama.com/) for Smart Mode LLM synthesis

### 2. Environment Setup
```bash
# Clone the repository
git clone https://github.com/m-eshan/Voxintel---Audio-Intelligence-for-Automated-Audio-Insights.git
cd Voxintel---Audio-Intelligence-for-Automated-Audio-Insights

# Create virtual environment
python -m venv .venv
.venv\Scripts\activate  # Windows: .venv\Scripts\activate | Unix: source .venv/bin/activate

# Install required packages
pip install -r requirements.txt
```

### 3. (Optional) Ollama Setup for Smart Mode
```bash
# Start Ollama service
ollama serve

# Pull your preferred lightweight model
ollama pull llama3.2:3b
# Or: ollama pull gemma3:1b
```

### 4. Launch the Dashboard
```bash
streamlit run app.py
```
Open `http://localhost:8501` in your browser. The dashboard features:
- Studio console dark theme (`#0E0F12`) with animated 5-bar waveform.
- 3-step pipeline tracker: `Transcribe` -> `Identify speakers` -> `Synthesize`.
- Five organized insight tabs: `Minutes`, `Transcript`, `Speakers`, `Keywords`, and `Export`.
- Interactive speaker cluster renaming widget (`Speaker 1` -> `Sarah`) with live chart updates.
- Export to formatted HTML, PDF, and JSON.

---

## Running Benchmarks & Tests

```bash
# Run unit test suite (31 tests passing)
python -m pytest

# Run the comprehensive evaluation benchmark across all test meetings
python scripts/evaluate_final.py

# Automated dashboard screenshot generation
python scripts/capture_screenshots.py
```

---

## Repository Structure

```
├── app.py                         # Streamlit studio console dashboard
├── assets/
│   ├── style.css                  # Studio console design tokens & typography
│   ├── figures/                   # Confusion matrices & evaluation plots
│   └── screenshots/               # Dashboard screenshots across 5 UI states
├── data/samples/                  # Audio samples, ground-truth scripts & final_metrics.json
├── docs/
│   └── results_tables.md          # Full raw benchmark tables & error analysis
├── scripts/
│   ├── evaluate_final.py          # Comprehensive evaluation & metrics generator
│   ├── generate_meeting_3.py      # Synthetic 4-voice test meeting audio generator
│   └── capture_screenshots.py     # Playwright automated screenshot script
├── tests/
│   ├── test_nlp_eval.py           # Unit tests for NLP evaluation metrics
│   ├── test_openai_pipeline.py    # OpenAI pipeline & duration formatting tests
│   ├── test_pipeline.py           # Fast mode, extraction, and clustering tests
│   └── test_ollama_improvements.py# Ollama prompt, JSON schema & grounding tests
└── voxintel/
    ├── audio.py                   # faster-whisper base int8 ASR with VAD
    ├── exports.py                 # HTML & PDF meeting report generators
    ├── insights.py                # TextRank summarization & action item extraction
    ├── nlp.py                     # Text normalization, tokenization, keywords
    ├── nlp_eval.py                # Evaluation metrics, word clouds & bigram graphs
    ├── ollama_polish.py           # Ollama client & third-person MoM synthesis
    └── optimized_pipeline.py      # Acoustic feature extraction & KMeans clustering
```

---

## License
MIT License.

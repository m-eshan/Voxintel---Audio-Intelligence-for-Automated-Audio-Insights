# VoxIntel: Audio Intelligence for Automated Meeting Insights

VoxIntel is an offline-first, local meeting intelligence platform designed to transcribe audio, cluster speakers, and synthesize professional Minutes of Meeting (MoM) on consumer hardware (such as an 8 GB RAM CPU laptop) without cloud API dependencies or recurring costs.

---

## Architecture Overview

VoxIntel features a streamlined dual-mode architecture:

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
    | - TextRank summary    |                 | - llama3.2:3b / gemma3:1b|
    | - Speaker-attributed  |                 | - Strict 3rd-person MoM  |
    |   action items        |                 | - Timestamp citations    |
    | - Heuristic deadlines |                 | - Attendee verification  |
    +-----------------------+                 +--------------------------+
```

### 1. Fast Mode (Lightweight Extractive)
* **Transcription**: Uses `faster-whisper` (`base` model, `int8` quantization) with Silero VAD filtering. Bypasses disk-heavy WAV chunking, processing audio in a single pass.
* **Speaker Labeling**: Extracts 13 MFCCs, zero-crossing rate, RMS energy, spectral centroid, and Yin fundamental pitch ($F_0$) per speech segment, followed by KMeans clustering ($k$ set by attendee count or silhouette optimization).
* **Extraction**: TextRank sentence graph ranking for extractive summary. Action items match commitments (`I'll`, `will`, `agreed to`) attributed directly to the segment's speaker with normalized deadlines (`PM`/`AM`).

### 2. Smart Mode (Local Offline LLM Synthesis)
* **Engine**: Integrates with a local [Ollama](https://ollama.com/) instance (`llama3.2:3b`, `gemma3:1b`, or `phi:latest`).
* **Third-Person Synthesis**: Produces formal past-tense minutes (e.g., *"George committed to finalizing the login patch by Friday at 5 PM"*). Prohibits first-person pronouns (`I`, `we`, `our`).
* **Timestamp Grounding**: Every discussion point, decision, and action item cites the exact timestamp (`[mm:ss]`) from the transcript.
* **Attendee List Validation**: Action item owners are strictly validated against user-entered attendees. Any unverified or generic reference is labeled as `"Unassigned"` to prevent false attribution.

---

## Benchmark & Evaluation

VoxIntel includes a ground-truth generation and evaluation suite (`scripts/generate_test_meeting.py` and `scripts/evaluate_meeting.py`) utilizing three distinct neural voice models (`en-US-JennyNeural`, `en-US-GuyNeural`, `en-GB-RyanNeural`).

### Synthetic Multi-Speaker Test Results (`test_meeting_3speakers.mp3`, 50s):

| Metric | Fast Mode | Smart Mode (`gemma3:1b`) | Ground Truth |
| :--- | :--- | :--- | :--- |
| **Speaker Clustering Accuracy** | **100.0%** (7/7 turns matched) | Inherited from acoustic pass | 7 distinct speaker turns |
| **George's Patch Commitment** | Detected (`00:23`, Friday at 5 PM) | Detected (`00:23`, Friday at 5 PM) | George, Friday at 5 PM |
| **Ravi's Support Task** | Detected (`00:36`, 2 PM) | Detected (`00:36`, 2 PM) | Ravi, 2 PM today |
| **Narrative Perspective** | Extractive 1st person quotes | **Strict 3rd-person formal past tense** | Formal meeting minutes |
| **Processing Latency** | ~6.8s (transcription + clustering) | ~10.4s (total end-to-end) | Baseline |

> **Acoustic Clustering Limitations (Academic Honesty Note)**:
> While MFCC + Yin $F_0$ clustering achieves 100% turn purity on distinct synthetic neural voices, unsupervised clustering on consumer hardware degrades in real-world human meetings with cross-talk, identical voice pitches, or reverberant microphones. VoxIntel surfaces speaker labels as approximate tags (`Speaker 1`, `Speaker 2`), allowing users to map them to real attendees in the UI.

---

## Quick Start

### 1. Installation
```bash
# Clone the repository
git clone https://github.com/m-eshan/Voxintel---Audio-Intelligence-for-Automated-Audio-Insights.git
cd Voxintel---Audio-Intelligence-for-Automated-Audio-Insights

# Create virtual environment
python -m venv .venv
.venv\Scripts\activate  # Windows: .venv\Scripts\activate | Unix: source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 2. (Optional) Run Local LLM for Smart Mode
Install [Ollama](https://ollama.com/) and pull a lightweight model:
```bash
ollama serve
ollama pull llama3.2:3b
# Or: ollama pull gemma3:1b
```

### 3. Launch Dashboard
```bash
streamlit run app.py
```

### 4. Run Test Suite & Evaluation
```bash
# Run unit tests
python -m pytest

# Run end-to-end evaluation benchmark
python scripts/evaluate_meeting.py
```

---

## Project Structure

```
├── app.py                         # Streamlit web application & UI
├── voxintel/
│   ├── audio.py                   # faster-whisper whole-file transcription with VAD
│   ├── optimized_pipeline.py      # Acoustic feature extraction & KMeans speaker clustering
│   ├── ollama_polish.py           # Local Ollama integration & third-person JSON MoM parsing
│   ├── insights.py                # Rule-based & TextRank extractive summarization heuristics
│   ├── nlp.py                     # Transcript cleaning, time normalization, keyword extraction
│   └── exports.py                 # HTML & PDF meeting intelligence report generators
├── scripts/
│   ├── generate_test_meeting.py   # Multi-voice edge-tts ground truth generator
│   └── evaluate_meeting.py        # Automated benchmark & accuracy scoring script
├── data/samples/                  # Sample audio & ground truth JSON datasets
└── tests/                         # Pytest test suite (transcription, NLP, polishing)
```

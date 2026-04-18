# VoxIntel

Audio Intelligence for Automated Meeting Insights.

VoxIntel is a lightweight Streamlit app that converts meeting audio into structured insights such as transcript summaries, keywords, decisions, action items, and downloadable MoM reports.

## Features
- Upload `.mp3`, `.wav`, or `.txt` meeting input
- Audio preprocessing and local speech-to-text pipeline
- Keyword extraction with TF-IDF
- Extractive summary generation
- Decision and action-item extraction
- Download insights as JSON, HTML, and PDF
- Optional local Ollama polishing path

## Project Structure
- `app.py` - Streamlit application entry point
- `voxintel/` - core processing modules
- `data/samples/` - bundled demo meeting transcripts
- `templates/` - HTML template for report export
- `assets/` - repository assets folder for screenshots or demo media

## Tech Stack
- Python
- Streamlit
- faster-whisper
- ffmpeg
- pandas
- scikit-learn
- librosa
- matplotlib
- Ollama

## Run Locally
```powershell
pip install -r requirements.txt
python -m streamlit run app.py
```

Then open `http://localhost:8501`.

## Recommended Mode
For low-memory laptops, use `Optimized lite pipeline`.

## Notes
- The project is optimized for local execution on modest hardware.
- Output quality depends heavily on transcript quality.
- Ollama polishing is optional and works best with a lightweight local model.

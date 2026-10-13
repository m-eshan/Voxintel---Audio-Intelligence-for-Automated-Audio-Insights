import copy
import hashlib
import json
import tempfile
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

from voxintel.audio import TranscriptionError, process_audio
from voxintel.insights import generate_mom, generate_summary, infer_speaker_activity
from voxintel.local_hybrid_pipeline import LocalHybridPipelineError, analyze_local_hybrid_meeting
from voxintel.nlp import clean_transcript, extract_keywords
from voxintel.openai_pipeline import format_seconds
from voxintel.ollama_polish import OllamaPolishError, polish_with_ollama, polish_results_with_ollama
from voxintel.optimized_pipeline import OptimizedPipelineError, run_optimized_voxintel

BASE_DIR = Path(__file__).parent
SAMPLES_DIR = BASE_DIR / "data" / "samples"
DEFAULT_INFO_TEXT = "Select a bundled sample or upload a meeting file, then click Start Analysis."


def load_sample_transcript(sample_name: str) -> str:
    return (SAMPLES_DIR / sample_name).read_text(encoding="utf-8")


def render_theme() -> None:
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Poppins:wght@500;600;700&family=Roboto:wght@400;500&display=swap');
        :root {
            --vox-blue: #1E3A8A;
            --vox-teal: #14B8A6;
            --vox-yellow: #FACC15;
            --vox-bg: #F9FAFB;
            --vox-text: #0F172A;
            --vox-card: rgba(255,255,255,0.88);
        }
        .stApp {
            background:
                radial-gradient(circle at top left, rgba(20,184,166,0.18), transparent 28%),
                radial-gradient(circle at top right, rgba(250,204,21,0.16), transparent 22%),
                linear-gradient(180deg, #F8FBFF 0%, var(--vox-bg) 100%);
            color: var(--vox-text);
            font-family: 'Roboto', sans-serif;
        }
        h1, h2, h3 {
            font-family: 'Poppins', sans-serif !important;
            color: var(--vox-blue);
        }
        .hero {
            padding: 1.6rem 1.8rem;
            border-radius: 22px;
            background: linear-gradient(135deg, rgba(30,58,138,0.95), rgba(20,184,166,0.86));
            color: white;
            box-shadow: 0 18px 50px rgba(30,58,138,0.18);
            margin-bottom: 1.2rem;
        }
        .metric-card {
            background: var(--vox-card);
            border: 1px solid rgba(148, 163, 184, 0.2);
            border-radius: 18px;
            padding: 1rem 1.1rem;
            box-shadow: 0 12px 35px rgba(15, 23, 42, 0.05);
            min-height: 160px;
        }
        .metric-card h3 {
            margin-top: 0;
            font-size: 1.05rem;
        }
        .tag {
            display: inline-block;
            padding: 0.3rem 0.65rem;
            border-radius: 999px;
            margin: 0.2rem 0.25rem 0.2rem 0;
            background: rgba(20,184,166,0.12);
            color: var(--vox-blue);
            font-weight: 600;
            font-size: 0.85rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_keyword_chart(keyword_df: pd.DataFrame) -> None:
    if keyword_df.empty:
        st.info("No keywords detected yet.")
        return

    fig, ax = plt.subplots(figsize=(7, 4))
    ax.bar(keyword_df["keyword"], keyword_df["count"], color="#14B8A6")
    ax.set_title("Keyword Frequency", color="#1E3A8A", fontsize=14, fontweight="bold")
    ax.set_ylabel("Count")
    ax.set_xlabel("")
    ax.tick_params(axis="x", rotation=35)
    ax.set_facecolor("#FFFFFF")
    fig.patch.set_alpha(0)
    st.pyplot(fig, use_container_width=True)


def save_uploaded_file(uploaded_file) -> Path:
    suffix = Path(uploaded_file.name).suffix
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
        temp_file.write(uploaded_file.getbuffer())
        return Path(temp_file.name)


def build_results(transcript: str, summary_mode: str) -> dict:
    cleaned_text, sentences, tokens = clean_transcript(transcript)
    keyword_df = extract_keywords(tokens)
    summary, summary_engine = generate_summary(
        sentences,
        tokens,
        transcript=cleaned_text,
        method="ai" if summary_mode == "AI-assisted" else "rule_based",
    )
    mom = generate_mom(transcript, summary)
    speaker_activity = pd.DataFrame(infer_speaker_activity(transcript))
    return {
        "transcript": transcript,
        "cleaned_text": cleaned_text,
        "sentences": sentences,
        "tokens": tokens,
        "summary": summary,
        "summary_engine": summary_engine,
        "keywords": keyword_df,
        "mom": mom,
        "speaker_activity": speaker_activity,
    }


def build_hybrid_local_results(
    audio_path: Path,
    meeting_context: str,
    progress_bar,
    status_box,
    diarization_mode: str,
    lite_mode: bool,
) -> dict:
    def progress_callback(value: int, message: str) -> None:
        update_progress(progress_bar, status_box, value, message)

    hybrid_results = analyze_local_hybrid_meeting(
        audio_path=audio_path,
        meeting_context=meeting_context,
        progress_callback=progress_callback,
        diarization_mode=diarization_mode,
        lite_mode=lite_mode,
    )
    return {
        "transcript": hybrid_results["transcript"],
        "cleaned_text": hybrid_results["mom"]["cleaned_transcript"],
        "sentences": clean_transcript(hybrid_results["transcript"])[1],
        "tokens": clean_transcript(hybrid_results["transcript"])[2],
        "summary": hybrid_results["summary"],
        "summary_engine": hybrid_results["summary_engine"],
        "keywords": hybrid_results["keywords"],
        "mom": hybrid_results["mom"],
        "speaker_activity": pd.DataFrame(hybrid_results["speaker_activity"]),
        "segments": hybrid_results["segments"],
        "duration_seconds": hybrid_results["duration_seconds"],
        "chunk_notes": hybrid_results["chunk_notes"],
        "html_report": hybrid_results["html_report"],
        "pdf_report": hybrid_results["pdf_report"],
        "diarization_engine": hybrid_results["diarization_engine"],
    }


def process_meeting_audio(
    audio_path: Path,
    file_bytes: bytes,
    source_label: str,
    is_smart_mode: bool,
    attendees: list[str] | None,
    progress_bar,
    status_box,
) -> dict:
    file_hash = hashlib.sha256(file_bytes).hexdigest()
    audio_cache = st.session_state.get("audio_cache", {})

    def progress_callback(value: int, message: str) -> None:
        update_progress(progress_bar, status_box, value, message)

    if file_hash in audio_cache:
        update_progress(progress_bar, status_box, 30, f"Using cached Whisper transcription for {source_label}...")
        base_results = copy.deepcopy(audio_cache[file_hash])
    else:
        update_progress(progress_bar, status_box, 20, f"Transcribing audio with faster-whisper base (int8)...")
        base_results = run_optimized_voxintel(audio_path, progress_callback=progress_callback, attendees=attendees)
        audio_cache[file_hash] = copy.deepcopy(base_results)
        st.session_state["audio_cache"] = audio_cache

    if is_smart_mode:
        try:
            update_progress(progress_bar, status_box, 75, "Synthesizing executive MoM with Ollama LLM...")
            results = polish_results_with_ollama(base_results, progress_callback=progress_callback, attendees=attendees)
            return results
        except OllamaPolishError as exc:
            status_box.warning(
                f"⚠️ Local Ollama server is offline or unreachable: {exc}. "
                "Switched cleanly to Fast Mode (TextRank). Start Ollama (`ollama serve`) to enable Smart Mode AI synthesis."
            )
            cleaned_text, sentences, tokens = clean_transcript(base_results["transcript"])
            summary, _ = generate_summary(sentences, tokens, transcript=cleaned_text, method="rule_based")
            mom = generate_mom(base_results["transcript"], summary, attendees=attendees)
            base_results["summary"] = summary
            base_results["mom"] = {
                **mom,
                "overview": summary,
                "next_steps": [item["task"] for item in mom["action_items"][:4]],
                "title": f"VoxIntel Meeting Report - {source_label}",
            }
            base_results["summary_engine"] = "ollama-fallback-fast"
            base_results["ollama_polish_used"] = False
            base_results["ollama_polish_error"] = str(exc)
            return base_results
    else:
        cleaned_text, sentences, tokens = clean_transcript(base_results["transcript"])
        summary, _ = generate_summary(sentences, tokens, transcript=cleaned_text, method="rule_based")
        mom = generate_mom(base_results["transcript"], summary, attendees=attendees)
        base_results["summary"] = summary
        base_results["mom"] = {
            **mom,
            "overview": summary,
            "next_steps": [item["task"] for item in mom["action_items"][:4]],
            "title": f"VoxIntel Fast Meeting Report - {source_label}",
        }
        base_results["summary_engine"] = "optimized-lite-extractive"
        return base_results


def initialize_state() -> None:
    st.session_state.setdefault("results", None)
    st.session_state.setdefault("source_label", "")
    st.session_state.setdefault("status_message", DEFAULT_INFO_TEXT)
    st.session_state.setdefault("audio_cache", {})


def classify_upload_for_laptop(uploaded_file) -> tuple[str, str]:
    size_mb = uploaded_file.size / (1024 * 1024)
    if size_mb >= 35:
        return "high", f"Large file detected: {size_mb:.1f} MB. On an 8 GB laptop, this may be slow or memory-heavy."
    if size_mb >= 15:
        return "medium", f"Medium file detected: {size_mb:.1f} MB. Lite mode is recommended for smoother processing."
    return "low", f"File size: {size_mb:.1f} MB. This is within the safer range for Lite mode."


def update_progress(progress_bar, status_box, value: int, message: str) -> None:
    progress_bar.progress(value)
    status_box.info(message)


def analyze_transcript(transcript: str, source_label: str, summary_mode: str, progress_bar, status_box) -> None:
    update_progress(progress_bar, status_box, 55, "Extracting keywords, summary, and action items...")
    results = build_results(transcript, summary_mode)

    if not results["sentences"]:
        st.session_state["results"] = None
        st.session_state["source_label"] = source_label
        st.session_state["status_message"] = "The transcript is too short to analyze. Try a richer sample or a longer recording."
        progress_bar.empty()
        status_box.error(st.session_state["status_message"])
        return

    update_progress(progress_bar, status_box, 90, "Packaging meeting insights for the dashboard...")
    st.session_state["results"] = results
    st.session_state["source_label"] = source_label
    st.session_state["status_message"] = f"Analysis complete for {source_label}."
    progress_bar.progress(100)
    status_box.success(st.session_state["status_message"])


def render_results(results: dict) -> None:
    col1, col2 = st.columns([1.3, 1])
    with col1:
        st.markdown(f"<div class='metric-card'><h3>Summary</h3><p>{results['summary']}</p></div>", unsafe_allow_html=True)
        engine = results["summary_engine"]
        if engine == "optimized-lite-extractive":
            st.caption("Summary mode: Optimized lite extractive summary")
        elif engine == "ollama-polish":
            st.caption("Summary mode: Ollama polish")
            if results.get("ollama_polish_used"):
                st.caption("Ollama polish status: Active")
            else:
                st.caption("Ollama polish status: Not confirmed")
            if results.get("ollama_polish_error"):
                st.caption(f"Ollama polish error: {results['ollama_polish_error']}")
        elif engine == "fast-local-polished-writer":
            st.caption("Summary mode: Fast local polished writer")
        elif engine == "local-meeting-writer":
            st.caption("Summary mode: Local AI meeting writer")
        elif engine == "rule_based":
            st.caption("Summary mode: Rule-based extractive summary")
        elif engine == "ai":
            st.caption("Summary mode: AI-assisted transformer summary")
        else:
            st.caption(f"Summary mode: {engine}")
    with col2:
        st.markdown("<div class='metric-card'><h3>Detected Participants</h3>", unsafe_allow_html=True)
        participants = results["mom"]["participants"]
        st.markdown("".join(f"<span class='tag'>{participant}</span>" for participant in participants), unsafe_allow_html=True)
        if results.get("duration_seconds"):
            st.caption(f"Duration analyzed: {format_seconds(results['duration_seconds'])}")
        else:
            meeting_date = results["mom"]["meeting_date"] or "Unknown"
            st.caption(f"Meeting date: {meeting_date}")
        if results.get("diarization_engine"):
            st.caption(f"Diarization: {results['diarization_engine']}")
    st.markdown("</div>", unsafe_allow_html=True)

    # Interactive Speaker Renaming Widget
    segments = results.get("segments", [])
    unique_speakers = sorted(list({s.get("speaker") for s in segments if s.get("speaker")}))
    if unique_speakers and any("Speaker" in s for s in unique_speakers):
        with st.expander("👤 Map Speaker Labels to Names", expanded=False):
            st.markdown(
                "Assign real attendee names to detected speaker clusters (e.g. `Speaker 1` ➔ `Sarah`). "
                "Updates apply across transcript, MoM, and speaker activity charts immediately without re-transcription."
            )
            cols = st.columns(min(max(len(unique_speakers), 1), 4))
            name_map = {}
            for idx, spk in enumerate(unique_speakers):
                with cols[idx % len(cols)]:
                    current_alias = st.session_state.get(f"alias_{spk}", spk)
                    new_val = st.text_input(f"Label: {spk}", value=current_alias, key=f"alias_input_{spk}")
                    if new_val and new_val.strip() and new_val.strip() != spk:
                        name_map[spk] = new_val.strip()

            if st.button("Apply Speaker Names", key="apply_speaker_names_btn"):
                if name_map:
                    for s in segments:
                        if s.get("speaker") in name_map:
                            s["speaker"] = name_map[s["speaker"]]
                    if "speaker_activity" in results and not results["speaker_activity"].empty:
                        results["speaker_activity"]["speaker"] = results["speaker_activity"]["speaker"].replace(name_map)
                    curr_part = results["mom"].get("participants", [])
                    results["mom"]["participants"] = [name_map.get(p, p) for p in curr_part]
                    for spk, alias in name_map.items():
                        st.session_state[f"alias_{spk}"] = alias
                    st.success("Speaker names updated across transcript and analytics!")
                    st.experimental_rerun()

    st.subheader("Minutes of Meeting")
    mom = results["mom"]
    if mom.get("title"):
        st.markdown(f"**Meeting Title:** {mom['title']}")
    if mom.get("overview"):
        st.markdown("**Overview**")
        st.write(mom["overview"])
    st.markdown("**Discussion Points**")
    for point in mom["discussion_points"]:
        st.markdown(f"- {point}")

    st.markdown("**Decisions**")
    for decision in mom["decisions"]:
        st.markdown(f"- {decision}")

    st.markdown("**Action Items**")
    action_items = pd.DataFrame(mom["action_items"])
    if action_items.empty:
        action_items = pd.DataFrame(
            [{"task": "No action items detected.", "person": "Unknown", "deadline": "Unknown", "notes": ""}]
        )
    st.dataframe(action_items, use_container_width=True, hide_index=True)

    if mom.get("risks"):
        st.markdown("**Risks / Watchouts**")
        for risk in mom["risks"]:
            st.markdown(f"- {risk}")
    if mom.get("next_steps"):
        st.markdown("**Next Steps**")
        for step in mom["next_steps"]:
            st.markdown(f"- {step}")

    left, right = st.columns(2)
    with left:
        st.subheader("Keyword Analytics")
        render_keyword_chart(results["keywords"])
    with right:
        st.subheader("Speaker Activity")
        speaker_activity = results["speaker_activity"]
        if speaker_activity.empty:
            st.info("Speaker labels were not explicitly available in this transcript.")
        else:
            st.dataframe(speaker_activity, use_container_width=True, hide_index=True)

    if mom.get("speaker_highlights"):
        st.subheader("Speaker Highlights")
        for highlight in mom["speaker_highlights"]:
            st.markdown(f"**Speaker {highlight['speaker']}**")
            for point in highlight["highlights"]:
                st.markdown(f"- {point}")

    if mom.get("mom_markdown"):
        with st.expander("Formatted MoM", expanded=False):
            st.markdown(mom["mom_markdown"])

    with st.expander("Transcript Preview", expanded=False):
        if results.get("segments"):
            for segment in results["segments"][:120]:
                st.write(
                    f"[{format_seconds(segment['start'])} - {format_seconds(segment['end'])}] "
                    f"Speaker {segment['speaker']}: {segment['text']}"
                )
        else:
            st.write(results["transcript"])

    if results.get("chunk_notes"):
        with st.expander("Chunk Notes", expanded=False):
            for index, note in enumerate(results["chunk_notes"], start=1):
                st.markdown(f"**Chunk {index}**")
                st.write(note)

    export_payload = {
        "summary": results["summary"],
        "mom": results["mom"],
        "keywords": results["keywords"].to_dict(orient="records"),
    }
    st.download_button(
        "Download Insights as JSON",
        data=json.dumps(export_payload, indent=2),
        file_name="voxintel_insights.json",
        mime="application/json",
    )
    if results.get("html_report"):
        st.download_button(
            "Download MoM as HTML",
            data=results["html_report"],
            file_name="voxintel_mom.html",
            mime="text/html",
        )
    if results.get("pdf_report"):
        st.download_button(
            "Download MoM as PDF",
            data=results["pdf_report"],
            file_name="voxintel_mom.pdf",
            mime="application/pdf",
        )


def main() -> None:
    st.set_page_config(page_title="VoxIntel", page_icon="??", layout="wide")
    initialize_state()
    render_theme()

    st.markdown(
        """
        <div class="hero">
            <h1>VoxIntel</h1>
            <p>Turn meeting chaos into structured intelligence with transcript cleanup, summaries, action items, and a calm analytics dashboard.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.sidebar.header("Input")
    input_mode = st.sidebar.radio("Choose source", ["Bundled sample", "Upload file"])
    pipeline_mode = st.sidebar.selectbox(
        "Processing Mode",
        ["⚡ Fast Mode (Whisper + TextRank)", "🧠 Smart Mode (Whisper + Ollama LLM)"],
        help="Fast Mode runs 100% locally with zero GPU requirements in ~10 seconds. Smart Mode runs Ollama locally to synthesize executive-level Minutes of Meeting.",
    )
    is_smart_mode = "Smart Mode" in pipeline_mode

    attendees_input = st.sidebar.text_input(
        "Expected Attendees (Optional)",
        placeholder="e.g. Eshan, Neeraj, Sarah",
        help="Helps accurately assign action items to real participant names instead of generic entities.",
    )
    attendees = [a.strip() for a in attendees_input.split(",") if a.strip()] if attendees_input else None

    progress_bar = st.progress(0)
    status_box = st.empty()
    status_box.info(st.session_state["status_message"])

    action_col, hint_col = st.columns([1, 2])
    with hint_col:
        if is_smart_mode:
            st.caption("🧠 **Smart Mode**: Whisper base ASR + Ollama (`llama3.2:3b` / `phi3`) for executive MoM, structured decisions, and verified action items. Requires Ollama running.")
        else:
            st.caption("⚡ **Fast Mode**: Faster-Whisper base (int8 CPU) + TextRank summarization. Extremely fast, lightweight, and works offline with zero dependencies.")

    if input_mode == "Bundled sample":
        sample_files = sorted(
            [path.name for path in SAMPLES_DIR.glob("*.txt")]
            + [path.name for path in SAMPLES_DIR.glob("*.mp3")]
            + [path.name for path in SAMPLES_DIR.glob("*.wav")]
        )
        selected_sample = st.sidebar.selectbox("Sample meeting", sample_files)
        sample_path = SAMPLES_DIR / selected_sample
        source_label = selected_sample
        with action_col:
            start_analysis = st.button("Start Analysis", type="primary", use_container_width=True, key="sample_start")
        if start_analysis:
            if sample_path.suffix.lower() == ".txt":
                transcript = load_sample_transcript(selected_sample)
                update_progress(progress_bar, status_box, 15, f"Loading bundled sample: {source_label}")
                analyze_transcript(transcript, source_label, "Rule-based", progress_bar, status_box)
            else:
                try:
                    update_progress(progress_bar, status_box, 15, f"Ingesting bundled audio: {source_label}...")
                    file_bytes = sample_path.read_bytes()
                    results = process_meeting_audio(
                        audio_path=sample_path,
                        file_bytes=file_bytes,
                        source_label=source_label,
                        is_smart_mode=is_smart_mode,
                        attendees=attendees,
                        progress_bar=progress_bar,
                        status_box=status_box,
                    )
                    st.session_state["results"] = results
                    st.session_state["source_label"] = source_label
                    st.session_state["status_message"] = f"Analysis complete for {source_label}."
                    progress_bar.progress(100)
                    status_box.success(st.session_state["status_message"])
                except Exception as exc:
                    st.session_state["results"] = None
                    st.session_state["source_label"] = source_label
                    st.session_state["status_message"] = str(exc)
                    progress_bar.empty()
                    status_box.error(str(exc))
    else:
        uploaded_file = st.sidebar.file_uploader(
            "Upload meeting file",
            type=["wav", "mp3", "txt"],
            help="Audio files (.mp3, .wav) are automatically transcribed. TXT sample transcripts also supported.",
        )
        with action_col:
            start_analysis = st.button(
                "Start Analysis",
                type="primary",
                use_container_width=True,
                key="upload_start",
                disabled=uploaded_file is None,
            )
        if uploaded_file is not None:
            source_label = uploaded_file.name
            st.caption(f"Ready to analyze: {source_label}")
            risk_level, laptop_note = classify_upload_for_laptop(uploaded_file)
            if risk_level == "high":
                st.warning(laptop_note)
            else:
                st.caption(laptop_note)

        if start_analysis and uploaded_file is not None:
            source_label = uploaded_file.name
            file_bytes = uploaded_file.getvalue()
            if uploaded_file.name.lower().endswith(".txt"):
                try:
                    transcript = file_bytes.decode("utf-8", errors="replace")
                    update_progress(progress_bar, status_box, 15, f"Loading uploaded transcript: {source_label}")
                    analyze_transcript(transcript, source_label, "Rule-based", progress_bar, status_box)
                except Exception as exc:
                    st.session_state["status_message"] = str(exc)
                    status_box.error(str(exc))
            else:
                temp_path = save_uploaded_file(uploaded_file)
                try:
                    update_progress(progress_bar, status_box, 15, f"Ingesting {source_label}...")
                    results = process_meeting_audio(
                        audio_path=temp_path,
                        file_bytes=file_bytes,
                        source_label=source_label,
                        is_smart_mode=is_smart_mode,
                        attendees=attendees,
                        progress_bar=progress_bar,
                        status_box=status_box,
                    )
                    st.session_state["results"] = results
                    st.session_state["source_label"] = source_label
                    mode_label = "Smart Mode" if is_smart_mode else "Fast Mode"
                    st.session_state["status_message"] = f"{mode_label} analysis complete for {source_label}."
                    progress_bar.progress(100)
                    status_box.success(st.session_state["status_message"])
                except Exception as exc:
                    st.session_state["results"] = None
                    st.session_state["source_label"] = source_label
                    st.session_state["status_message"] = str(exc)
                    progress_bar.empty()
                    status_box.error(str(exc))
                finally:
                    temp_path.unlink(missing_ok=True)

    st.sidebar.markdown("### Workflow")
    if is_smart_mode:
        st.sidebar.caption("Audio Ingestion -> faster-whisper base (int8 VAD) -> Ollama Local LLM Polish -> HTML / PDF Export")
    else:
        st.sidebar.caption("Audio Ingestion -> faster-whisper base (int8 VAD) -> TextRank Graph Summarization -> Action Extraction -> HTML / PDF Export")

    results = st.session_state.get("results")
    source_label = st.session_state.get("source_label", "")

    if not results:
        st.info(DEFAULT_INFO_TEXT)
        return

    st.caption(f"Source: {source_label}")
    render_results(results)


if __name__ == "__main__":
    main()

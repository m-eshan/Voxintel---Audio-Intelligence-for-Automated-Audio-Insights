from __future__ import annotations

import copy
import hashlib
import html
import json
import re
import tempfile
import time
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

from voxintel.audio import TranscriptionError
from voxintel.exports import render_mom_html, render_mom_pdf
from voxintel.insights import generate_mom, generate_summary, infer_speaker_activity
from voxintel.nlp import clean_transcript, extract_keywords
from voxintel.nlp_eval import make_bigram_graph, make_wordcloud
from voxintel.ollama_polish import OllamaPolishError, _get_ollama_settings, polish_results_with_ollama
from voxintel.openai_pipeline import format_seconds
from voxintel.optimized_pipeline import OptimizedPipelineError, run_optimized_voxintel

BASE_DIR = Path(__file__).resolve().parent
SAMPLES_DIR = BASE_DIR / "data" / "samples"
ASSETS_DIR = BASE_DIR / "assets"

SPEAKER_PALETTE_CLASSES = ["spk-0", "spk-1", "spk-2", "spk-3", "spk-4"]
SPEAKER_PALETTE_HEX = ["#4EA8DE", "#F2A65A", "#7BD389", "#C792EA", "#F07178"]


def load_sample_transcript(sample_name: str) -> str:
    return (SAMPLES_DIR / sample_name).read_text(encoding="utf-8")


def render_theme() -> None:
    css_path = ASSETS_DIR / "style.css"
    if css_path.exists():
        st.markdown(f"<style>{css_path.read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)


def get_speaker_class(speaker: str, speaker_order: list[str]) -> str:
    if not speaker:
        return "spk-0"
    if speaker not in speaker_order:
        speaker_order.append(speaker)
    idx = speaker_order.index(speaker) % len(SPEAKER_PALETTE_CLASSES)
    return SPEAKER_PALETTE_CLASSES[idx]


def get_speaker_hex(speaker: str, speaker_order: list[str]) -> str:
    if not speaker:
        return SPEAKER_PALETTE_HEX[0]
    if speaker not in speaker_order:
        speaker_order.append(speaker)
    idx = speaker_order.index(speaker) % len(SPEAKER_PALETTE_HEX)
    return SPEAKER_PALETTE_HEX[idx]


def render_tracker(step: int, placeholder=None) -> None:
    c1 = "completed" if step > 1 else ("active" if step == 1 else "")
    c2 = "completed" if step > 2 else ("active" if step == 2 else "")
    c3 = "completed" if step > 3 else ("active" if step == 3 else "")
    snippet = f"""
    <div class="tracker-container">
        <div class="tracker-step {c1}"><span class="tracker-dot"></span><span>1. Transcribe</span></div>
        <div class="tracker-step {c2}"><span class="tracker-dot"></span><span>2. Identify speakers</span></div>
        <div class="tracker-step {c3}"><span class="tracker-dot"></span><span>3. Synthesize</span></div>
    </div>
    """
    if placeholder:
        placeholder.markdown(snippet, unsafe_allow_html=True)
    else:
        st.markdown(snippet, unsafe_allow_html=True)


def render_stat_row(results: dict) -> None:
    duration_sec = results.get("duration_seconds", 0)
    dur_str = format_seconds(duration_sec) if duration_sec else "00:00"

    segments = results.get("segments", [])
    unique_spk = list({s.get("speaker") for s in segments if s.get("speaker")})
    if not unique_spk:
        unique_spk = results.get("mom", {}).get("participants", [])
    spk_count = len(unique_spk)

    actions = results.get("mom", {}).get("action_items", [])
    act_count = len(actions)

    latency_sec = results.get("latency_seconds", 0.0)
    lat_str = f"{latency_sec:.1f}s" if latency_sec > 0 else "< 10s"

    snippet = f"""
    <div class="stat-row">
        <div class="stat-item"><span class="stat-label">Duration</span><span class="stat-value">{dur_str}</span></div>
        <div class="stat-item"><span class="stat-label">Speakers</span><span class="stat-value">{spk_count}</span></div>
        <div class="stat-item"><span class="stat-label">Action Items</span><span class="stat-value">{act_count}</span></div>
        <div class="stat-item"><span class="stat-label">Latency</span><span class="stat-value">{lat_str}</span></div>
    </div>
    """
    st.markdown(snippet, unsafe_allow_html=True)


def extract_key_moments(summary_text: str, segments: list[dict]) -> list[dict]:
    moments = []
    if not summary_text:
        return moments

    raw_sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", summary_text) if s.strip()]
    if not segments:
        for s in raw_sentences:
            moments.append({"time": "00:00", "speaker": "Speaker 1", "line": s})
        return moments

    for sent in raw_sentences:
        clean_words = set(re.findall(r"\b[a-zA-Z]{3,}\b", sent.lower()))
        best_seg = None
        best_overlap = 0
        for seg in segments:
            seg_words = set(re.findall(r"\b[a-zA-Z]{3,}\b", (seg.get("text") or "").lower()))
            overlap = len(clean_words & seg_words)
            if overlap > best_overlap:
                best_overlap = overlap
                best_seg = seg
        if best_seg:
            moments.append({
                "time": format_seconds(best_seg.get("start", 0)),
                "speaker": best_seg.get("speaker", "Speaker 1"),
                "line": sent,
            })
        else:
            moments.append({
                "time": "00:00",
                "speaker": "Speaker 1",
                "line": sent,
            })
    return moments


def render_talk_time_bars(segments: list[dict], speaker_order: list[str]) -> plt.Figure:
    durations: dict[str, float] = {}
    for s in segments:
        spk = s.get("speaker", "Unknown")
        dur = max(0.0, float(s.get("end", 0.0)) - float(s.get("start", 0.0)))
        durations[spk] = durations.get(spk, 0.0) + dur

    if not durations:
        durations = {"Speaker 1": 1.0}

    speakers = list(durations.keys())
    times = [durations[s] for s in speakers]
    total_time = sum(times) if sum(times) > 0 else 1.0

    colors = [get_speaker_hex(s, speaker_order) for s in speakers]

    fig, ax = plt.subplots(figsize=(7, max(2.5, len(speakers) * 0.7)), facecolor="#0E0F12")
    ax.set_facecolor("#0E0F12")

    y_pos = range(len(speakers))
    bars = ax.barh(y_pos, times, color=colors, height=0.55, edgecolor="#2A2E37", linewidth=1)
    ax.set_yticks(list(y_pos))
    ax.set_yticklabels(speakers, color="#ECE8E1", fontsize=10, fontfamily="monospace")
    ax.tick_params(axis="x", colors="#9AA0AB")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#2A2E37")
    ax.spines["bottom"].set_color("#2A2E37")
    ax.grid(axis="x", linestyle="--", alpha=0.15, color="#ECE8E1")

    for bar, val in zip(bars, times):
        pct = (val / total_time) * 100
        ax.text(
            bar.get_width() + (max(times) * 0.02),
            bar.get_y() + bar.get_height() / 2,
            f"{val:.1f}s ({pct:.0f}%)",
            va="center",
            color="#ECE8E1",
            fontsize=9,
            fontfamily="monospace",
        )

    ax.set_xlim(0, max(times) * 1.25)
    plt.tight_layout()
    return fig


def save_uploaded_file(uploaded_file) -> Path:
    suffix = Path(uploaded_file.name).suffix
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
        temp_file.write(uploaded_file.getbuffer())
        return Path(temp_file.name)


def process_meeting_pipeline(
    audio_path: Path,
    file_bytes: bytes,
    source_label: str,
    is_smart_mode: bool,
    attendees: list[str] | None,
    tracker_box,
    status_box,
) -> dict:
    file_hash = hashlib.sha256(file_bytes).hexdigest()
    audio_cache = st.session_state.setdefault("audio_cache", {})

    t0 = time.perf_counter()

    if file_hash in audio_cache:
        status_box.info(f"Using cached base transcription for {source_label}...")
        render_tracker(2, tracker_box)
        base_results = copy.deepcopy(audio_cache[file_hash])
    else:
        render_tracker(1, tracker_box)
        status_box.info("Transcribing audio with faster-whisper base (int8)...")
        base_results = run_optimized_voxintel(audio_path, attendees=attendees)
        audio_cache[file_hash] = copy.deepcopy(base_results)

    render_tracker(2, tracker_box)
    status_box.info("Separating speaker turns and acoustic clusters...")
    time.sleep(0.3)

    render_tracker(3, tracker_box)
    if is_smart_mode:
        try:
            status_box.info("Synthesizing executive MoM with local Ollama LLM...")
            results = polish_results_with_ollama(base_results, attendees=attendees)
            results["is_smart_mode"] = True
        except OllamaPolishError as exc:
            status_box.warning(
                f"Local Ollama server is offline or unreachable: {exc}. "
                "Switched cleanly to Fast Mode. Start Ollama (`ollama serve`) to enable Smart Mode AI synthesis."
            )
            cleaned_text, sentences, tokens = clean_transcript(base_results["transcript"])
            summary, _ = generate_summary(sentences, tokens, transcript=cleaned_text, method="rule_based")
            mom = generate_mom(base_results["transcript"], summary, attendees=attendees, segments=base_results.get("segments"))
            base_results["summary"] = summary
            base_results["mom"] = {
                **mom,
                "overview": summary,
                "title": f"VoxIntel Fast Meeting Report - {source_label}",
            }
            base_results["is_smart_mode"] = False
            results = base_results
    else:
        status_box.info("Extracting key moments and action items via Fast Mode...")
        cleaned_text, sentences, tokens = clean_transcript(base_results["transcript"])
        summary, _ = generate_summary(sentences, tokens, transcript=cleaned_text, method="rule_based")
        mom = generate_mom(base_results["transcript"], summary, attendees=attendees, segments=base_results.get("segments"))
        base_results["summary"] = summary
        base_results["mom"] = {
            **mom,
            "overview": summary,
            "title": f"VoxIntel Fast Meeting Report - {source_label}",
        }
        base_results["is_smart_mode"] = False
        results = base_results

    # Generate HTML & PDF reports if missing
    context = {
        "title": results["mom"].get("title", f"VoxIntel Report - {source_label}"),
        "summary": results["summary"],
        "participants": results["mom"].get("participants", []),
        "discussion_points": results["mom"].get("discussion_points", []),
        "decisions": results["mom"].get("decisions", []),
        "action_items": results["mom"].get("action_items", []),
    }
    if not results.get("html_report"):
        try:
            results["html_report"] = render_mom_html(context)
        except Exception:
            results["html_report"] = ""
    if not results.get("pdf_report"):
        try:
            results["pdf_report"] = render_mom_pdf(context)
        except Exception:
            results["pdf_report"] = b""

    elapsed = time.perf_counter() - t0
    results["latency_seconds"] = round(elapsed, 2)
    render_tracker(4, tracker_box)
    status_box.success(f"Analysis complete in {elapsed:.1f}s.")
    return results


def render_dashboard(results: dict, source_label: str) -> None:
    segments = results.get("segments", [])
    speaker_order: list[str] = []
    for s in segments:
        spk = s.get("speaker")
        if spk and spk not in speaker_order:
            speaker_order.append(spk)

    is_smart_mode = results.get("is_smart_mode", True)

    # 1. Inline Mono Stat Row
    render_stat_row(results)

    # 2. Main 5 Tabs
    tab_min, tab_tr, tab_spk, tab_kw, tab_exp = st.tabs(
        ["Minutes", "Transcript", "Speakers", "Keywords", "Export"]
    )

    # --- TAB 1: MINUTES ---
    with tab_min:
        mom = results.get("mom", {})
        title = mom.get("title", f"Meeting Minutes - {source_label}")

        st.markdown(f'<h3 class="brand-title">{html.escape(title)}</h3>', unsafe_allow_html=True)

        if is_smart_mode:
            overview = mom.get("overview") or results.get("summary", "")
            if overview:
                st.markdown(f'<div class="editorial-summary">{html.escape(overview)}</div>', unsafe_allow_html=True)
        else:
            # Fast mode must display "Key moments" as "[mm:ss] Speaker: line" and must NOT be labeled "Summary"
            st.markdown('<h4 class="brand-title" style="color: var(--accent-amber); margin-top: 1rem; margin-bottom: 0.6rem;">Key moments</h4>', unsafe_allow_html=True)
            moments = extract_key_moments(results.get("summary", ""), segments)
            if moments:
                for m in moments:
                    spk_cls = get_speaker_class(m["speaker"], speaker_order)
                    st.markdown(
                        f'<div class="transcript-turn {spk_cls}">'
                        f'<span class="mono-time">[{m["time"]}]</span> '
                        f'<span class="speaker-chip {spk_cls}">{html.escape(m["speaker"])}</span> '
                        f'<span class="transcript-text">{html.escape(m["line"])}</span>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )
            else:
                st.caption("No key moments extracted.")

        # Decisions Table
        st.markdown('<h4 class="brand-title" style="margin-top: 1.5rem; margin-bottom: 0.5rem;">Decisions</h4>', unsafe_allow_html=True)
        decisions = mom.get("decisions", [])
        if decisions:
            rows = []
            for d in decisions:
                if isinstance(d, dict):
                    d_time = d.get("time", "--:--")
                    d_spk = d.get("speaker", "Team")
                    d_text = d.get("decision", "")
                else:
                    d_str = str(d)
                    m = re.match(r"^\[?(\d{2}:\d{2})\]?\s*(?:([A-Za-z0-9 _-]+):)?\s*(.*)", d_str)
                    if m:
                        d_time = m.group(1)
                        d_spk = m.group(2) or "Team"
                        d_text = m.group(3)
                    else:
                        d_time = "--:--"
                        d_spk = "Team"
                        d_text = d_str
                spk_cls = get_speaker_class(d_spk, speaker_order)
                rows.append(
                    f'<tr>'
                    f'<td class="mono-time">[{d_time}]</td>'
                    f'<td><span class="speaker-chip {spk_cls}">{html.escape(d_spk)}</span></td>'
                    f'<td>{html.escape(d_text)}</td>'
                    f'</tr>'
                )
            st.markdown(
                f'<table class="compact-table"><thead><tr>'
                f'<th style="width: 75px;">Time</th>'
                f'<th style="width: 130px;">Speaker</th>'
                f'<th>Decision</th>'
                f'</tr></thead><tbody>{"".join(rows)}</tbody></table>',
                unsafe_allow_html=True,
            )
        else:
            st.caption("No formal decisions recorded.")

        # Action Items Table
        st.markdown('<h4 class="brand-title" style="margin-top: 1.5rem; margin-bottom: 0.5rem;">Action Items</h4>', unsafe_allow_html=True)
        action_items = mom.get("action_items", [])
        if action_items:
            rows = []
            for a in action_items:
                a_time = a.get("time") or a.get("timestamp") or "--:--"
                a_owner = a.get("person") or a.get("owner") or "Unassigned"
                a_task = a.get("task") or ""
                a_deadline = a.get("deadline") or "Not specified"
                spk_cls = get_speaker_class(a_owner, speaker_order)
                rows.append(
                    f'<tr>'
                    f'<td class="mono-time">[{a_time}]</td>'
                    f'<td><span class="speaker-chip {spk_cls}">{html.escape(a_owner)}</span></td>'
                    f'<td>{html.escape(a_task)}</td>'
                    f'<td><span class="muted-deadline-tag">{html.escape(a_deadline)}</span></td>'
                    f'</tr>'
                )
            st.markdown(
                f'<table class="compact-table"><thead><tr>'
                f'<th style="width: 75px;">Time</th>'
                f'<th style="width: 130px;">Owner</th>'
                f'<th>Task</th>'
                f'<th style="width: 120px;">Deadline</th>'
                f'</tr></thead><tbody>{"".join(rows)}</tbody></table>',
                unsafe_allow_html=True,
            )
        else:
            st.caption("No action items detected.")

        # Discussion Points
        disc_points = mom.get("discussion_points", [])
        if disc_points:
            st.markdown('<h4 class="brand-title" style="margin-top: 1.5rem; margin-bottom: 0.5rem;">Discussion Points</h4>', unsafe_allow_html=True)
            for dp in disc_points:
                if isinstance(dp, dict):
                    t = dp.get("time", "--:--")
                    sp = dp.get("speaker", "Speaker")
                    p = dp.get("point", "")
                    spk_cls = get_speaker_class(sp, speaker_order)
                    st.markdown(
                        f'<div class="transcript-turn {spk_cls}">'
                        f'<span class="mono-time">[{t}]</span> '
                        f'<span class="speaker-chip {spk_cls}">{html.escape(sp)}</span> '
                        f'<span class="transcript-text">{html.escape(p)}</span>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown(f"- {html.escape(str(dp))}")

    # --- TAB 2: TRANSCRIPT ---
    with tab_tr:
        st.markdown('<h4 class="brand-title" style="margin-bottom: 0.8rem;">Full Transcript</h4>', unsafe_allow_html=True)
        if segments:
            for s in segments:
                t_str = format_seconds(s.get("start", 0))
                spk = s.get("speaker", "Speaker 1")
                text = s.get("text", "")
                spk_cls = get_speaker_class(spk, speaker_order)
                st.markdown(
                    f'<div class="transcript-turn {spk_cls}">'
                    f'<span class="mono-time">[{t_str}]</span> '
                    f'<span class="speaker-chip {spk_cls}">{html.escape(spk)}</span> '
                    f'<span class="transcript-text">{html.escape(text)}</span>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
        else:
            st.write(results.get("transcript", "No transcript text available."))

    # --- TAB 3: SPEAKERS ---
    with tab_spk:
        st.markdown('<h4 class="brand-title" style="margin-bottom: 0.5rem;">Speaker Attribution & Talk Time</h4>', unsafe_allow_html=True)

        # Interactive Speaker Renaming Widget
        unique_spks = sorted(list({s.get("speaker") for s in segments if s.get("speaker")}))
        if unique_spks and any("Speaker" in s for s in unique_spks):
            st.markdown('<div class="mono-text" style="font-size:0.75rem; color:var(--text-secondary); margin-bottom:0.4rem;">RENAME DETECTED SPEAKER CLUSTERS</div>', unsafe_allow_html=True)
            cols = st.columns(min(max(len(unique_spks), 1), 4))
            name_map = {}
            for idx, spk in enumerate(unique_spks):
                with cols[idx % len(cols)]:
                    curr_alias = st.session_state.get(f"alias_{spk}", spk)
                    new_val = st.text_input(f"Cluster: {spk}", value=curr_alias, key=f"alias_input_{spk}")
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
                    st.rerun()

        # Horizontal Talk-Time Chart
        fig_talk = render_talk_time_bars(segments, speaker_order)
        st.pyplot(fig_talk, use_container_width=True)

        # Speaker activity dataframe
        speaker_activity = results.get("speaker_activity")
        if isinstance(speaker_activity, pd.DataFrame) and not speaker_activity.empty:
            st.dataframe(speaker_activity, use_container_width=True, hide_index=True)

    # --- TAB 4: KEYWORDS & N-GRAMS ---
    with tab_kw:
        transcript_text = results.get("transcript", "")
        kw_tab1, kw_tab2 = st.tabs(["Word cloud", "Bigram graph"])
        with kw_tab1:
            st.markdown('<h4 class="brand-title" style="margin-bottom: 0.5rem;">Lexical Salience</h4>', unsafe_allow_html=True)
            fig_wc = make_wordcloud(transcript_text)
            st.pyplot(fig_wc, use_container_width=True)

        with kw_tab2:
            st.markdown('<h4 class="brand-title" style="margin-bottom: 0.5rem;">Bigram Co-occurrence Network</h4>', unsafe_allow_html=True)
            fig_bg = make_bigram_graph(transcript_text)
            st.pyplot(fig_bg, use_container_width=True)

    # --- TAB 5: EXPORT ---
    with tab_exp:
        st.markdown('<h4 class="brand-title" style="margin-bottom: 0.8rem;">Export Minutes & Analytics</h4>', unsafe_allow_html=True)
        st.caption("Download the synthesized meeting intelligence in your preferred format.")

        col1, col2, col3 = st.columns(3)
        with col1:
            if results.get("html_report"):
                st.download_button(
                    "Download MoM as HTML",
                    data=results["html_report"],
                    file_name="voxintel_mom.html",
                    mime="text/html",
                    use_container_width=True,
                )
        with col2:
            if results.get("pdf_report"):
                st.download_button(
                    "Download MoM as PDF",
                    data=results["pdf_report"],
                    file_name="voxintel_mom.pdf",
                    mime="application/pdf",
                    use_container_width=True,
                )
        with col3:
            export_payload = {
                "summary": results["summary"],
                "mom": results["mom"],
                "keywords": results["keywords"].to_dict(orient="records") if isinstance(results.get("keywords"), pd.DataFrame) else results.get("keywords", []),
                "segments": results.get("segments", []),
            }
            st.download_button(
                "Download Insights as JSON",
                data=json.dumps(export_payload, indent=2),
                file_name="voxintel_insights.json",
                mime="application/json",
                use_container_width=True,
            )


def main() -> None:
    st.set_page_config(page_title="VoxIntel", layout="wide")
    render_theme()

    # Top Brand Header with Fraunces Wordmark & 5-Bar CSS Waveform
    st.markdown(
        """
        <div class="vox-header-bar">
            <div class="vox-wordmark">
                <span>VoxIntel</span>
                <div class="vox-waveform">
                    <span></span><span></span><span></span><span></span><span></span>
                </div>
            </div>
            <div class="mono-text" style="color: var(--text-secondary); font-size: 0.78rem;">
                Audio Intelligence & Executive MoM Synthesizer
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Sidebar: 3 Clean Groups
    # Group 1: Input
    st.sidebar.markdown('<div class="sidebar-group-title">Input</div>', unsafe_allow_html=True)
    input_source = st.sidebar.radio("Input Source", ["Sample meeting", "Upload file"], label_visibility="collapsed")

    selected_sample = None
    uploaded_file = None

    if input_source == "Sample meeting":
        sample_files = sorted(
            [p.name for p in SAMPLES_DIR.glob("*.mp3")]
            + [p.name for p in SAMPLES_DIR.glob("*.wav")]
            + [p.name for p in SAMPLES_DIR.glob("*.txt")]
        )
        default_idx = sample_files.index("test_meeting_3speakers.mp3") if "test_meeting_3speakers.mp3" in sample_files else 0
        selected_sample = st.sidebar.selectbox("Choose Sample", sample_files, index=default_idx)
    else:
        uploaded_file = st.sidebar.file_uploader(
            "Upload Audio / Transcript",
            type=["wav", "mp3", "txt"],
            help="Audio files (.mp3, .wav) are transcribed via faster-whisper base int8. TXT transcripts are directly analyzed.",
        )

    attendees_input = st.sidebar.text_input(
        "Expected Attendees (Optional)",
        value="Sarah, George, Ravi" if (input_source == "Sample meeting" and selected_sample == "test_meeting_3speakers.mp3") else "",
        placeholder="e.g. Sarah, George, Ravi",
        help="Grounds speaker attribution and action item assignments.",
    )
    attendees = [a.strip() for a in attendees_input.split(",") if a.strip()] if attendees_input else None

    # Group 2: Mode
    st.sidebar.markdown('<div class="sidebar-group-title">Mode</div>', unsafe_allow_html=True)
    pipeline_mode = st.sidebar.radio(
        "Processing Mode",
        ["Fast Mode (Whisper + TextRank)", "Smart Mode (Whisper + Ollama LLM)"],
        label_visibility="collapsed",
    )
    is_smart_mode = "Smart Mode" in pipeline_mode

    _, active_model = _get_ollama_settings()
    st.sidebar.markdown(
        f'<div class="mono-text" style="font-size:0.75rem; color:var(--accent-amber); margin-top:0.25rem; margin-bottom:0.75rem;">'
        f'active model: {active_model}</div>',
        unsafe_allow_html=True,
    )

    # Group 3: Options
    st.sidebar.markdown('<div class="sidebar-group-title">Options</div>', unsafe_allow_html=True)
    if is_smart_mode:
        st.sidebar.caption("faster-whisper base int8 ASR + Ollama LLM executive third-person MoM.")
    else:
        st.sidebar.caption("Offline faster-whisper base int8 ASR + TextRank key moments extraction.")

    start_button = st.sidebar.button("Start Analysis", type="primary", use_container_width=True)

    # Progress tracker box & status message box
    tracker_box = st.empty()
    status_box = st.empty()

    trigger_sample = st.session_state.pop("trigger_sample", False)
    if trigger_sample:
        selected_sample = "test_meeting_3speakers.mp3"
        input_source = "Sample meeting"
        start_button = True

    if start_button:
        if input_source == "Sample meeting" and selected_sample:
            sample_path = SAMPLES_DIR / selected_sample
            source_label = selected_sample
            if sample_path.suffix.lower() == ".txt":
                try:
                    render_tracker(1, tracker_box)
                    status_box.info(f"Loading transcript: {source_label}...")
                    transcript = load_sample_transcript(selected_sample)
                    cleaned_text, sentences, tokens = clean_transcript(transcript)
                    summary, _ = generate_summary(sentences, tokens, transcript=cleaned_text, method="rule_based")
                    mom = generate_mom(transcript, summary, attendees=attendees)
                    results = {
                        "transcript": transcript,
                        "segments": [],
                        "duration_seconds": 0,
                        "summary": summary,
                        "mom": mom,
                        "keywords": extract_keywords(cleaned_text),
                        "speaker_activity": pd.DataFrame(infer_speaker_activity(transcript)),
                        "latency_seconds": 0.5,
                        "is_smart_mode": is_smart_mode,
                    }
                    st.session_state["results"] = results
                    st.session_state["source_label"] = source_label
                    render_tracker(4, tracker_box)
                    status_box.success("Analysis complete.")
                except Exception as exc:
                    status_box.error(str(exc))
            else:
                try:
                    file_bytes = sample_path.read_bytes()
                    results = process_meeting_pipeline(
                        audio_path=sample_path,
                        file_bytes=file_bytes,
                        source_label=source_label,
                        is_smart_mode=is_smart_mode,
                        attendees=attendees,
                        tracker_box=tracker_box,
                        status_box=status_box,
                    )
                    st.session_state["results"] = results
                    st.session_state["source_label"] = source_label
                except Exception as exc:
                    status_box.error(str(exc))
        elif input_source == "Upload file" and uploaded_file:
            source_label = uploaded_file.name
            file_bytes = uploaded_file.getvalue()
            if uploaded_file.name.lower().endswith(".txt"):
                try:
                    render_tracker(1, tracker_box)
                    status_box.info(f"Loading transcript: {source_label}...")
                    transcript = file_bytes.decode("utf-8", errors="replace")
                    cleaned_text, sentences, tokens = clean_transcript(transcript)
                    summary, _ = generate_summary(sentences, tokens, transcript=cleaned_text, method="rule_based")
                    mom = generate_mom(transcript, summary, attendees=attendees)
                    results = {
                        "transcript": transcript,
                        "segments": [],
                        "duration_seconds": 0,
                        "summary": summary,
                        "mom": mom,
                        "keywords": extract_keywords(cleaned_text),
                        "speaker_activity": pd.DataFrame(infer_speaker_activity(transcript)),
                        "latency_seconds": 0.5,
                        "is_smart_mode": is_smart_mode,
                    }
                    st.session_state["results"] = results
                    st.session_state["source_label"] = source_label
                    render_tracker(4, tracker_box)
                    status_box.success("Analysis complete.")
                except Exception as exc:
                    status_box.error(str(exc))
            else:
                temp_path = save_uploaded_file(uploaded_file)
                try:
                    results = process_meeting_pipeline(
                        audio_path=temp_path,
                        file_bytes=file_bytes,
                        source_label=source_label,
                        is_smart_mode=is_smart_mode,
                        attendees=attendees,
                        tracker_box=tracker_box,
                        status_box=status_box,
                    )
                    st.session_state["results"] = results
                    st.session_state["source_label"] = source_label
                except Exception as exc:
                    status_box.error(str(exc))
                finally:
                    temp_path.unlink(missing_ok=True)

    results = st.session_state.get("results")
    source_label = st.session_state.get("source_label", "")

    if not results:
        # Empty State: Dashed drop zone with "Try the sample meeting" button
        st.markdown(
            """
            <div class="empty-drop-zone">
                <h3 style="font-family: var(--font-display); margin-bottom: 0.5rem; color: var(--text-primary);">No Audio Analyzed Yet</h3>
                <p style="color: var(--text-secondary); max-width: 55ch; margin: 0 auto 1.25rem auto;">
                    Select a bundled meeting recording or upload an audio file (.wav, .mp3) to generate structured executive minutes, speaker timelines, and keyword graphs.
                </p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        col_c1, col_c2, col_c3 = st.columns([1, 1, 1])
        with col_c2:
            if st.button("Try Sample Meeting", type="secondary", use_container_width=True):
                st.session_state["trigger_sample"] = True
                st.rerun()
    else:
        render_dashboard(results, source_label)


if __name__ == "__main__":
    main()

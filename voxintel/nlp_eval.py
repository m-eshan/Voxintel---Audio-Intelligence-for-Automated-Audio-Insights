from __future__ import annotations

import math
import re
from collections import Counter
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import networkx as nx
import numpy as np
from wordcloud import WordCloud

# Color palette tokens matching the UI theme
DARK_BG = "#0E0F12"
SURFACE_BG = "#16181D"
CARD_BG = "#1E2128"
BORDER_COLOR = "#2A2E37"
TEXT_PRIMARY = "#ECE8E1"
TEXT_MUTED = "#9AA0AB"
ACCENT_AMBER = "#FFB020"
SPEAKER_PALETTE = ["#4EA8DE", "#F2A65A", "#7BD389", "#C792EA", "#F07178"]

STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for", "with", "by", "about",
    "against", "between", "into", "through", "during", "before", "after", "above", "below", "from",
    "up", "down", "in", "out", "off", "over", "under", "again", "further", "then", "once", "here",
    "there", "when", "where", "why", "how", "all", "any", "both", "each", "few", "more", "most",
    "other", "some", "such", "no", "nor", "not", "only", "own", "same", "so", "than", "too", "very",
    "s", "t", "can", "will", "just", "don", "should", "now", "we", "i", "you", "they", "he", "she",
    "it", "our", "my", "your", "their", "his", "her", "its", "us", "me", "him", "them", "re", "ve",
    "ll", "d", "m", "let", "s", "good", "morning", "team", "wrap", "up", "yeah", "okay", "um", "uh"
}


def _clean_tokens(text: str) -> list[str]:
    clean = re.sub(r"\[\d{2}:\d{2}(?::\d{2})?\]|[A-Za-z0-9_-]+:", " ", text)
    tokens = [w.lower() for w in re.findall(r"\b[a-zA-Z]{3,}\b", clean)]
    return [t for t in tokens if t not in STOPWORDS]


def make_wordcloud(transcript: str, width: int = 800, height: int = 400) -> plt.Figure:
    """Generate a word cloud styled to match the dark studio console theme."""
    tokens = _clean_tokens(transcript)
    text = " ".join(tokens) if tokens else "meeting notes discussion"

    def amber_speaker_color_func(word, font_size, position, orientation, random_state=None, **kwargs):
        colors = [ACCENT_AMBER] + SPEAKER_PALETTE
        idx = (hash(word) % len(colors))
        return colors[idx]

    wc = WordCloud(
        width=width,
        height=height,
        background_color=DARK_BG,
        color_func=amber_speaker_color_func,
        max_words=60,
        prefer_horizontal=0.85,
        random_state=42,
    ).generate(text)

    fig, ax = plt.subplots(figsize=(8, 4), facecolor=DARK_BG)
    ax.imshow(wc, interpolation="bilinear")
    ax.axis("off")
    fig.patch.set_facecolor(DARK_BG)
    plt.tight_layout(pad=0)
    return fig


def make_bigram_graph(transcript: str, top_n: int = 14) -> plt.Figure:
    """Generate a bigram network graph with dark editorial styling."""
    tokens = _clean_tokens(transcript)
    bigrams = list(zip(tokens[:-1], tokens[1:]))
    bigram_counts = Counter(bigrams)

    top_bigrams = [item for item in bigram_counts.most_common(top_n) if item[0][0] != item[0][1]]

    fig, ax = plt.subplots(figsize=(8, 4.5), facecolor=DARK_BG)
    fig.patch.set_facecolor(DARK_BG)
    ax.set_facecolor(DARK_BG)

    if not top_bigrams:
        ax.text(0.5, 0.5, "Insufficient bigrams detected", color=TEXT_MUTED, ha="center", va="center")
        ax.axis("off")
        return fig

    G = nx.Graph()
    for (w1, w2), count in top_bigrams:
        G.add_edge(w1, w2, weight=count)

    pos = nx.spring_layout(G, k=1.3, seed=42)

    # Edge weights
    weights = [G[u][v]["weight"] for u, v in G.edges()]
    max_w = max(weights) if weights else 1
    edge_widths = [1.2 + 2.5 * (w / max_w) for w in weights]

    nx.draw_networkx_edges(
        G, pos, ax=ax,
        edge_color=BORDER_COLOR,
        width=edge_widths,
        alpha=0.85,
    )

    # Nodes
    degrees = dict(G.degree())
    node_sizes = [400 + 150 * deg for deg in degrees.values()]
    node_colors = [ACCENT_AMBER if deg >= 3 else CARD_BG for deg in degrees.values()]
    node_edge_colors = [ACCENT_AMBER if deg >= 3 else SPEAKER_PALETTE[i % len(SPEAKER_PALETTE)] for i, deg in enumerate(degrees.values())]

    nx.draw_networkx_nodes(
        G, pos, ax=ax,
        node_size=node_sizes,
        node_color=node_colors,
        edgecolors=node_edge_colors,
        linewidths=1.5,
    )

    nx.draw_networkx_labels(
        G, pos, ax=ax,
        font_size=9,
        font_family="sans-serif",
        font_color=TEXT_PRIMARY,
        font_weight="bold",
    )

    ax.axis("off")
    plt.tight_layout(pad=0.5)
    return fig


# -------------------------------------------------------------------------
# METRIC EVALUATION FUNCTIONS FOR scripts/evaluate_final.py
# -------------------------------------------------------------------------

def compute_wer(ref_text: str, hyp_text: str) -> float:
    """Compute Word Error Rate (WER) using jiwer."""
    import jiwer
    clean_ref = re.sub(r"\[\d{2}:\d{2}\]|\b[A-Z][a-z]+:", " ", ref_text)
    clean_hyp = re.sub(r"\[\d{2}:\d{2}\]|\b[A-Z][a-z]+:", " ", hyp_text)
    clean_ref = re.sub(r"\s+", " ", clean_ref).strip().lower()
    clean_hyp = re.sub(r"\s+", " ", clean_hyp).strip().lower()
    if not clean_ref:
        return 0.0
    return float(jiwer.wer(clean_ref, clean_hyp))


def evaluate_speaker_frame_attribution(
    ref_segments: list[dict],
    hyp_segments: list[dict],
    total_duration: float,
    step: float = 0.5,
    grounding: bool = True,
    remap: bool = True,
    fig_save_path: Path | None = None,
) -> dict[str, Any]:
    """Frame-level speaker attribution evaluation at 0.5s intervals."""
    from sklearn.metrics import accuracy_score, precision_recall_fscore_support, confusion_matrix

    times = np.arange(0.0, total_duration, step)
    y_true: list[str] = []
    y_pred: list[str] = []

    def get_speaker(t: float, segs: list[dict]) -> str:
        for s in segs:
            if s.get("start", 0.0) <= t <= s.get("end", 0.0):
                return s.get("speaker", "Unknown")
        return "Unknown"

    for t in times:
        y_true.append(get_speaker(t, ref_segments))
        y_pred.append(get_speaker(t, hyp_segments))

    # If remap requested (for ungrounded clustering comparison)
    unique_pred = sorted(list(set(y_pred)))
    unique_true = sorted(list(set(y_true) - {"Unknown"}))

    if remap and any(p.startswith("Speaker") for p in unique_pred):
        from itertools import permutations
        best_acc = -1.0
        best_remap = {}
        for p in permutations(unique_true, min(len(unique_true), len(unique_pred))):
            curr_map = dict(zip(unique_pred, p))
            mapped_pred = [curr_map.get(spk, spk) for spk in y_pred]
            acc = accuracy_score(y_true, mapped_pred)
            if acc > best_acc:
                best_acc = acc
                best_remap = curr_map
        y_pred = [best_remap.get(spk, spk) for spk in y_pred]

    labels = sorted(list(set(y_true) | set(y_pred)))
    acc = accuracy_score(y_true, y_pred)
    macro_p, macro_r, macro_f1, _ = precision_recall_fscore_support(y_true, y_pred, average="macro", zero_division=0)
    micro_p, micro_r, micro_f1, _ = precision_recall_fscore_support(y_true, y_pred, average="micro", zero_division=0)
    wt_p, wt_r, wt_f1, _ = precision_recall_fscore_support(y_true, y_pred, average="weighted", zero_division=0)

    cm = confusion_matrix(y_true, y_pred, labels=labels)

    if fig_save_path:
        fig_save_path.parent.mkdir(parents=True, exist_ok=True)
        fig, ax = plt.subplots(figsize=(6, 5), facecolor=DARK_BG)
        fig.patch.set_facecolor(DARK_BG)
        ax.set_facecolor(DARK_BG)
        cax = ax.imshow(cm, interpolation="nearest", cmap="YlOrBr")
        cbar = fig.colorbar(cax, ax=ax)
        cbar.ax.yaxis.set_tick_params(color=TEXT_MUTED)
        plt.setp(plt.getp(cbar.ax.axes, "yticklabels"), color=TEXT_MUTED)

        ax.set_xticks(range(len(labels)))
        ax.set_yticks(range(len(labels)))
        ax.set_xticklabels(labels, color=TEXT_PRIMARY, rotation=45, ha="right")
        ax.set_yticklabels(labels, color=TEXT_PRIMARY)
        ax.set_xlabel("Predicted Speaker", color=TEXT_PRIMARY, fontweight="bold")
        ax.set_ylabel("True Speaker", color=TEXT_PRIMARY, fontweight="bold")
        ax.set_title(f"Speaker Attribution Confusion Matrix ({'Grounding ON' if grounding else 'Clustering Only'})", color=ACCENT_AMBER, fontsize=10)

        for i in range(len(labels)):
            for j in range(len(labels)):
                ax.text(j, i, str(cm[i, j]), ha="center", va="center", color=DARK_BG if cm[i, j] > cm.max()/2 else TEXT_PRIMARY, fontweight="bold")

        plt.tight_layout()
        plt.savefig(fig_save_path, facecolor=DARK_BG, dpi=180)
        plt.close(fig)

    return {
        "accuracy": round(float(acc), 4),
        "macro_precision": round(float(macro_p), 4),
        "macro_recall": round(float(macro_r), 4),
        "macro_f1": round(float(macro_f1), 4),
        "micro_precision": round(float(micro_p), 4),
        "micro_recall": round(float(micro_r), 4),
        "micro_f1": round(float(micro_f1), 4),
        "weighted_precision": round(float(wt_p), 4),
        "weighted_recall": round(float(wt_r), 4),
        "weighted_f1": round(float(wt_f1), 4),
        "labels": labels,
        "confusion_matrix": cm.tolist(),
    }


def evaluate_action_items(ref_actions: list[dict], hyp_actions: list[dict]) -> dict[str, Any]:
    """Compute precision, recall, F1 for action items using keyword overlap."""
    if not ref_actions and not hyp_actions:
        return {"precision": 1.0, "recall": 1.0, "f1": 1.0, "true_positives": 0, "false_positives": 0, "false_negatives": 0}
    if not ref_actions:
        return {"precision": 0.0, "recall": 0.0, "f1": 0.0, "true_positives": 0, "false_positives": len(hyp_actions), "false_negatives": 0}
    if not hyp_actions:
        return {"precision": 0.0, "recall": 0.0, "f1": 0.0, "true_positives": 0, "false_positives": 0, "false_negatives": len(ref_actions)}

    matched_refs = set()
    matched_hyps = set()

    for h_idx, h in enumerate(hyp_actions):
        h_words = set(re.findall(r"[a-z]{3,}", (h.get("task", "") + " " + h.get("item", "")).lower())) - STOPWORDS
        h_owner = str(h.get("owner") or h.get("person", "")).lower()

        best_sim = 0.0
        best_r = -1
        for r_idx, r in enumerate(ref_actions):
            if r_idx in matched_refs:
                continue
            r_words = set(re.findall(r"[a-z]{3,}", r.get("task", "").lower())) - STOPWORDS
            r_owner = str(r.get("speaker") or r.get("person") or r.get("owner", "")).lower()

            overlap = len(h_words & r_words) / max(len(r_words), 1)
            # Give bonus if owners match
            if h_owner and r_owner and (h_owner in r_owner or r_owner in h_owner):
                overlap += 0.2

            if overlap > best_sim:
                best_sim = overlap
                best_r = r_idx

        if best_sim >= 0.35 and best_r != -1:
            matched_hyps.add(h_idx)
            matched_refs.add(best_r)

    tp = len(matched_refs)
    fp = len(hyp_actions) - len(matched_hyps)
    fn = len(ref_actions) - len(matched_refs)

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = (2 * precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0

    return {
        "precision": round(float(precision), 4),
        "recall": round(float(recall), 4),
        "f1": round(float(f1), 4),
        "true_positives": tp,
        "false_positives": fp,
        "false_negatives": fn,
    }


def evaluate_summary_quality(ref_summary: str, cand_summary: str) -> dict[str, Any]:
    """Compute ROUGE, BLEU, METEOR, BERTScore and first-person pronoun count."""
    import nltk
    from nltk.translate.bleu_score import sentence_bleu, SmoothingFunction
    from nltk.translate.meteor_score import meteor_score
    from rouge_score import rouge_scorer

    ref = ref_summary.strip()
    cand = cand_summary.strip()

    # ROUGE
    scorer = rouge_scorer.RougeScorer(["rouge1", "rouge2", "rougeL"], use_stemmer=True)
    r_scores = scorer.score(ref, cand) if ref and cand else None

    rouge1_f = round(r_scores["rouge1"].fmeasure, 4) if r_scores else 0.0
    rouge2_f = round(r_scores["rouge2"].fmeasure, 4) if r_scores else 0.0
    rougeL_f = round(r_scores["rougeL"].fmeasure, 4) if r_scores else 0.0

    # BLEU
    ref_toks = nltk.word_tokenize(ref.lower()) if ref else []
    cand_toks = nltk.word_tokenize(cand.lower()) if cand else []
    smooth = SmoothingFunction().method1
    bleu = round(float(sentence_bleu([ref_toks], cand_toks, smoothing_function=smooth)), 4) if ref_toks and cand_toks else 0.0

    # METEOR
    try:
        meteor = round(float(meteor_score([ref_toks], cand_toks)), 4) if ref_toks and cand_toks else 0.0
    except Exception:
        meteor = 0.0

    # BERTScore
    bertscore_f1 = 0.0
    try:
        from bert_score import score as bert_score_fn
        P, R, F1 = bert_score_fn([cand], [ref], lang="en", rescale_with_baseline=True, verbose=False)
        bertscore_f1 = round(float(F1.mean().item()), 4)
    except Exception:
        bertscore_f1 = 0.0

    # First-person pronoun check
    first_person_matches = re.findall(r"\b(i|we|our|my|me|us)\b", cand, flags=re.IGNORECASE)
    first_person_count = len(first_person_matches)

    return {
        "rouge1": rouge1_f,
        "rouge2": rouge2_f,
        "rougeL": rougeL_f,
        "bleu": bleu,
        "meteor": meteor,
        "bertscore_f1": bertscore_f1,
        "first_person_pronoun_count": first_person_count,
        "first_person_matches": list(set(m.lower() for m in first_person_matches)),
    }


def _time_str_to_seconds(time_str: str) -> float:
    parts = time_str.strip().split(":")
    if len(parts) == 2:
        return float(int(parts[0]) * 60 + int(parts[1]))
    if len(parts) == 3:
        return float(int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2]))
    try:
        return float(time_str)
    except Exception:
        return 0.0


def evaluate_timestamp_error(paired_timestamps: list[tuple[float, float]]) -> dict[str, Any]:
    """Compute MAE, and if >= 3 pairs: MSE, R2, Pearson r, Spearman rho."""
    from scipy.stats import pearsonr, spearmanr
    from sklearn.metrics import mean_squared_error, r2_score

    if not paired_timestamps:
        return {"mae": 0.0, "pairs_count": 0}

    y_true = np.array([p[0] for p in paired_timestamps])
    y_pred = np.array([p[1] for p in paired_timestamps])
    mae = float(np.mean(np.abs(y_true - y_pred)))

    res = {
        "mae": round(mae, 2),
        "pairs_count": len(paired_timestamps),
    }

    if len(paired_timestamps) >= 3:
        mse = float(mean_squared_error(y_true, y_pred))
        r2 = float(r2_score(y_true, y_pred))
        pr, _ = pearsonr(y_true, y_pred) if len(set(y_true)) > 1 and len(set(y_pred)) > 1 else (1.0, 0.0)
        sr, _ = spearmanr(y_true, y_pred) if len(set(y_true)) > 1 and len(set(y_pred)) > 1 else (1.0, 0.0)

        res.update({
            "mse": round(mse, 2),
            "r2": round(r2, 4),
            "pearson_r": round(float(pr), 4) if not math.isnan(pr) else 1.0,
            "spearman_rho": round(float(sr), 4) if not math.isnan(sr) else 1.0,
        })
    else:
        res["note"] = "Fewer than 3 pairs; regression metrics skipped"

    return res


def evaluate_perplexity_proxy(text: str) -> float:
    """Optional fluency proxy using character/word entropy."""
    tokens = text.lower().split()
    if not tokens:
        return 0.0
    counts = Counter(tokens)
    total = len(tokens)
    entropy = -sum((c / total) * math.log2(c / total) for c in counts.values())
    perplexity = 2 ** entropy
    return round(float(perplexity), 2)

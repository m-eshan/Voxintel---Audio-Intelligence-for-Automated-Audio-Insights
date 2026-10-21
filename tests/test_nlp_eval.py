from __future__ import annotations

import matplotlib.pyplot as plt
import numpy as np
import pytest

from voxintel.nlp_eval import (
    compute_wer,
    evaluate_action_items,
    evaluate_speaker_frame_attribution,
    make_bigram_graph,
    make_wordcloud,
)


def test_compute_wer_identical():
    wer = compute_wer("the quick brown fox", "the quick brown fox")
    assert wer == 0.0


def test_compute_wer_difference():
    wer = compute_wer("the fast brown fox", "the quick brown fox")
    assert wer > 0.0


def test_make_wordcloud():
    transcript = "Kubernetes pods deployment Kafka consumer lag Redis caching architecture"
    fig = make_wordcloud(transcript)
    assert isinstance(fig, plt.Figure)
    plt.close(fig)


def test_make_bigram_graph():
    transcript = "Kubernetes pods deployment Kubernetes pods scaling Redis cache Redis cluster"
    fig = make_bigram_graph(transcript)
    assert isinstance(fig, plt.Figure)
    plt.close(fig)


def test_evaluate_action_items():
    ref_items = [
        {"task": "Update Helm charts", "turn": 8},
        {"task": "Publish security spec", "turn": 12},
    ]
    pred_items = [
        {"task": "Update Helm deployment charts", "time": "02:05"},
        {"task": "Unrelated task without match", "time": "03:00"},
    ]
    metrics = evaluate_action_items(pred_items, ref_items)
    assert metrics["true_positives"] == 1
    assert metrics["false_positives"] == 1
    assert metrics["false_negatives"] == 1
    assert metrics["precision"] == 0.5
    assert metrics["recall"] == 0.5
    assert metrics["f1"] == 0.5


def test_evaluate_speaker_frame_attribution():
    ref_segments = [
        {"start": 0.0, "end": 2.0, "speaker": "Speaker 1"},
        {"start": 2.0, "end": 4.0, "speaker": "Speaker 2"},
    ]
    pred_segments = [
        {"start": 0.0, "end": 2.0, "speaker": "Speaker 1"},
        {"start": 2.0, "end": 4.0, "speaker": "Speaker 2"},
    ]
    res = evaluate_speaker_frame_attribution(pred_segments, ref_segments, total_duration=4.0, remap=False)
    assert res["accuracy"] == 1.0
    assert res["macro_f1"] == 1.0

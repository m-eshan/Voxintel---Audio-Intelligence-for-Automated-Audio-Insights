import copy
import json
import os
import sys
import time
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

from voxintel.optimized_pipeline import run_optimized_voxintel
from voxintel.ollama_polish import polish_results_with_ollama, _get_ollama_settings


def evaluate_speaker_clustering(segments: list[dict], gt_segments: list[dict], candidate_speakers: list[str]) -> tuple[float, dict, list[dict]]:
    """Evaluates acoustic turn clustering against time-aligned ground truth segments."""
    segment_eval = []
    for s in segments:
        s_mid = (s["start"] + s["end"]) / 2.0
        matched_gt = None
        for g in gt_segments:
            if g["start"] <= s_mid <= g["end"] + 0.6:
                matched_gt = g
                break
        if not matched_gt:
            matched_gt = min(gt_segments, key=lambda g: abs((g["start"] + g["end"]) / 2.0 - s_mid))

        segment_eval.append({
            "start": round(s["start"], 2),
            "end": round(s["end"], 2),
            "assigned_cluster": s["speaker"],
            "true_speaker": matched_gt["speaker"],
            "text": s["text"][:50],
        })

    # Find optimal cluster-to-speaker 1-to-1 mapping
    from itertools import permutations
    clusters = sorted(list(set(se["assigned_cluster"] for se in segment_eval)))
    best_acc = 0.0
    best_mapping = {}

    for p in permutations(candidate_speakers, min(len(candidate_speakers), len(clusters))):
        mapping = dict(zip(clusters, p))
        correct = sum(1 for se in segment_eval if mapping.get(se["assigned_cluster"]) == se["true_speaker"])
        acc = correct / len(segment_eval) if segment_eval else 0.0
        if acc > best_acc:
            best_acc = acc
            best_mapping = mapping

    return best_acc, best_mapping, segment_eval


def run_benchmark_on_meeting(
    audio_path: Path,
    gt_path: Path,
    meeting_name: str,
) -> dict:
    print("\n" + "=" * 75)
    print(f"BENCHMARKING: {meeting_name}")
    print(f"Audio file: {audio_path.name}")
    print("=" * 75)

    with open(gt_path, "r", encoding="utf-8") as f:
        ground_truth = json.load(f)

    attendees = ground_truth["speakers"]
    print(f"Attendees: {attendees}")

    # 1. Measure Fast Mode
    print("\n[Phase 1] Running Fast Mode (Whisper Base + Acoustic Clustering + Heuristics)...")
    t0 = time.perf_counter()
    fast_results = run_optimized_voxintel(audio_path, attendees=attendees)
    fast_duration = time.perf_counter() - t0
    print(f"[OK] Fast Mode completed in {fast_duration:.2f}s")

    # Fast Mode speaker clustering accuracy
    gt_segs = ground_truth["segments"]
    cluster_acc, cluster_map, seg_eval = evaluate_speaker_clustering(
        fast_results["segments"], gt_segs, attendees
    )
    print(f"[OK] Acoustic Clustering Accuracy: {cluster_acc * 100:.1f}%")
    print(f"  Mapping: {cluster_map}")

    # 2. Measure Smart Mode (Ollama Hybrid Polish)
    print("\n[Phase 2] Running Smart Mode (Hybrid JSON Prompt with Ollama)...")
    host, active_model = _get_ollama_settings()
    print(f"  Active LLM Model: {active_model} at {host}")

    fast_snapshot = copy.deepcopy(fast_results)
    t1 = time.perf_counter()
    smart_results = polish_results_with_ollama(
        copy.deepcopy(fast_results),
        attendees=attendees,
    )
    smart_synthesis_time = time.perf_counter() - t1
    total_smart_duration = fast_duration + smart_synthesis_time
    print(f"[OK] Ollama Synthesis completed in {smart_synthesis_time:.2f}s")
    print(f"[OK] Total Smart Mode End-to-End latency: {total_smart_duration:.2f}s")

    smart_mom = smart_results["mom"]

    return {
        "meeting_name": meeting_name,
        "audio_file": audio_path.name,
        "attendees": attendees,
        "latencies": {
            "fast_mode_seconds": round(fast_duration, 2),
            "smart_synthesis_seconds": round(smart_synthesis_time, 2),
            "smart_mode_total_seconds": round(total_smart_duration, 2),
        },
        "acoustic_clustering": {
            "accuracy_percent": round(cluster_acc * 100, 1),
            "cluster_mapping": cluster_map,
            "turns_evaluated": len(seg_eval),
            "segment_eval": seg_eval,
        },
        "active_model": active_model,
        "fast_mom": fast_snapshot["mom"],
        "smart_mom": smart_mom,
        "ground_truth": ground_truth.get("ground_truth_mom", ground_truth),
    }


def main():
    m1_audio = Path("data/samples/test_meeting_3speakers.mp3")
    m1_gt = Path("data/samples/test_meeting_3speakers_ground_truth.json")

    m2_audio = Path("data/samples/test_meeting_long_4speakers.mp3")
    m2_gt = Path("data/samples/test_meeting_long_4speakers_ground_truth.json")

    results = {}
    if m1_audio.exists() and m1_gt.exists():
        results["meeting_1_short"] = run_benchmark_on_meeting(
            m1_audio, m1_gt, "Meeting 1: Sprint Sync (3 Speakers, ~50s)"
        )

    if m2_audio.exists() and m2_gt.exists():
        results["meeting_2_heldout"] = run_benchmark_on_meeting(
            m2_audio, m2_gt, "Meeting 2: Held-Out Platform Sync (4 Speakers, ~3.2m)"
        )

    # Save to JSON
    out_path = Path("data/samples/comprehensive_benchmark_results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    print("\n" + "=" * 75)
    print("ALL BENCHMARKS COMPLETE. Output saved to:", out_path)
    print("=" * 75)


if __name__ == "__main__":
    main()

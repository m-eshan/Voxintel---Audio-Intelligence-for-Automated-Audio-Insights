import json
import sys
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from voxintel.optimized_pipeline import run_optimized_voxintel
from voxintel.ollama_polish import polish_results_with_ollama

def evaluate():
    audio_path = Path("data/samples/test_meeting_3speakers.mp3")
    gt_path = Path("data/samples/test_meeting_3speakers_ground_truth.json")
    
    with open(gt_path, "r", encoding="utf-8") as f:
        ground_truth = json.load(f)

    attendees = ground_truth["speakers"]  # ["Sarah", "George", "Ravi"]
    
    print("=" * 60)
    print("RUNNING FAST MODE PIPELINE...")
    print("=" * 60)
    fast_results = run_optimized_voxintel(audio_path, attendees=attendees)
    
    print("\n--- FAST MODE SEGMENTS & CLUSTERING ---")
    for i, s in enumerate(fast_results["segments"]):
        start = s.get("start", 0)
        end = s.get("end", 0)
        spk = s.get("speaker", "Unknown")
        text = s.get("text", "")
        print(f"[{start:05.2f}s - {end:05.2f}s] {spk}: {text}")

    print("\n--- FAST MODE EXTRACTED ACTION ITEMS ---")
    for item in fast_results["mom"]["action_items"]:
        print(f"Owner: {item.get('person')} | Task: {item.get('task')} | Deadline: {item.get('deadline')} | Time: {item.get('time', 'N/A')}")

    print("\n--- FAST MODE SUMMARY ---")
    print(fast_results["summary"])

    print("\n--- SPEAKER CLUSTERING ACCURACY EVALUATION ---")
    # Ground truth mapping: check overlap between whisper segments and GT segments
    gt_segs = ground_truth["segments"]
    segment_eval = []
    
    for s in fast_results["segments"]:
        s_mid = (s["start"] + s["end"]) / 2.0
        # Find which GT segment contains midpoint
        matched_gt = None
        for g in gt_segs:
            if g["start"] <= s_mid <= g["end"] + 0.5:
                matched_gt = g
                break
        if not matched_gt:
            # find closest
            matched_gt = min(gt_segs, key=lambda g: abs((g["start"] + g["end"])/2.0 - s_mid))
        
        segment_eval.append({
            "whisper_time": f"{s['start']:.1f}s - {s['end']:.1f}s",
            "whisper_text": s["text"][:35] + "...",
            "assigned_cluster": s["speaker"],
            "true_speaker": matched_gt["speaker"]
        })
        print(f"[{s['start']:05.2f}s - {s['end']:05.2f}s] Assigned: {s['speaker']} | True: {matched_gt['speaker']} | Text: {s['text'][:35]}...")

    # Calculate cluster purity / alignment
    # Find mapping from assigned_cluster -> true_speaker that maximizes accuracy
    clusters = list(set(se["assigned_cluster"] for se in segment_eval))
    from itertools import permutations
    best_acc = 0.0
    best_mapping = {}
    candidate_speakers = ["Sarah", "George", "Ravi"]
    for p in permutations(candidate_speakers, min(len(candidate_speakers), len(clusters))):
        mapping = dict(zip(clusters, p))
        correct = sum(1 for se in segment_eval if mapping.get(se["assigned_cluster"]) == se["true_speaker"])
        acc = correct / len(segment_eval) if segment_eval else 0
        if acc > best_acc:
            best_acc = acc
            best_mapping = mapping
            
    print(f"\nOptimal Cluster-to-Speaker Mapping: {best_mapping}")
    print(f"Speaker Clustering Turn Purity / Accuracy: {best_acc * 100:.1f}% ({int(best_acc * len(segment_eval))}/{len(segment_eval)} turns matched)")

    print("\n" + "=" * 60)
    print("RUNNING SMART MODE (OLLAMA) ON PRE-COMPUTED RESULTS...")
    print("=" * 60)
    import copy
    fast_snapshot = copy.deepcopy(fast_results)
    smart_results = polish_results_with_ollama(copy.deepcopy(fast_results), attendees=attendees)
    
    print("\n--- SMART MODE POLISHED MOM ---")
    smart_mom = smart_results["mom"]
    print(f"Title: {smart_mom.get('title')}")
    print(f"\nExecutive Summary:\n{smart_mom.get('overview')}")
    print("\nDiscussion Points:")
    for dp in smart_mom.get("discussion_points", []):
        print(f"  • {dp}")
    print("\nDecisions:")
    for dec in smart_mom.get("decisions", []):
        print(f"  • {dec}")
    print("\nAction Items:")
    for ai in smart_mom.get("action_items", []):
        print(f"  • Task: {ai.get('task')} | Owner: {ai.get('person')} | Deadline: {ai.get('deadline')} | Time: {ai.get('notes')}")

    # Save complete evaluation output
    out_file = Path("data/samples/evaluation_comparison_output.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump({
            "ground_truth": ground_truth,
            "fast_mode": {
                "summary": fast_snapshot["summary"],
                "action_items": fast_snapshot["mom"]["action_items"],
                "segments": fast_snapshot["segments"],
            },
            "clustering_accuracy": {
                "turn_purity_percent": round(best_acc * 100, 1),
                "mapping": best_mapping,
                "segment_eval": segment_eval
            },
            "smart_mode": smart_mom
        }, f, indent=2)
    print(f"\nSaved evaluation comparison to {out_file}")

if __name__ == "__main__":
    evaluate()

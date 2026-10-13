import asyncio
import subprocess
import shutil
from pathlib import Path
import edge_tts

# Realistic 3-speaker sprint review script with clear ground truth
SCRIPT = [
    ("Sarah", "en-US-JennyNeural", "Good morning team. Let's do our release readiness review. What is the status of the authentication bug?"),
    ("George", "en-US-GuyNeural", "I've been looking into it. Users are experiencing login failures due to an expired token management issue."),
    ("Ravi", "en-GB-RyanNeural", "I confirmed the issue during QA testing. We have a temporary workaround, but the permanent fix will take two days."),
    ("George", "en-US-GuyNeural", "I'll take ownership of the permanent login patch and complete it by Friday at 5 PM."),
    ("Sarah", "en-US-JennyNeural", "Approved. We decide to deploy the temporary workaround today, and George will release the permanent patch Friday."),
    ("Ravi", "en-GB-RyanNeural", "I will notify the customer support team about the known issue by 2 PM today."),
    ("Sarah", "en-US-JennyNeural", "Excellent. Ravi handles support notifications, George patches login by Friday. Let's wrap up."),
]

async def build_audio():
    import json
    import librosa
    output_dir = Path("data/samples")
    output_dir.mkdir(parents=True, exist_ok=True)
    temp_files = []
    ground_truth_segments = []

    print("Generating distinct neural voice segments with edge-tts...")
    current_time = 0.0
    for i, (speaker, voice, text) in enumerate(SCRIPT):
        part_name = f"_temp_part_{i:02d}.mp3"
        temp_files.append(part_name)
        communicator = edge_tts.Communicate(text, voice)
        await communicator.save(part_name)
        dur = float(librosa.get_duration(path=part_name))
        ground_truth_segments.append({
            "segment_id": i + 1,
            "speaker": speaker,
            "voice": voice,
            "start": round(current_time, 2),
            "end": round(current_time + dur, 2),
            "duration": round(dur, 2),
            "text": text,
        })
        current_time += dur
        print(f"  [{speaker}] ({round(current_time - dur, 2)}s - {round(current_time, 2)}s) using {voice}")

    concat_list_file = Path("_temp_concat_list.txt")
    with concat_list_file.open("w", encoding="utf-8") as f:
        for p in temp_files:
            f.write(f"file '{p}'\n")

    ffmpeg_bin = shutil.which("ffmpeg") or "ffmpeg"
    final_output = output_dir / "test_meeting_3speakers.mp3"

    print(f"\nConcatenating segments into {final_output}...")
    subprocess.run(
        [ffmpeg_bin, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list_file), "-c", "copy", str(final_output)],
        check=True
    )

    # Cleanup temporary parts
    concat_list_file.unlink(missing_ok=True)
    for p in temp_files:
        Path(p).unlink(missing_ok=True)

    ground_truth_meta = {
        "audio_file": "test_meeting_3speakers.mp3",
        "total_duration": round(current_time, 2),
        "speakers": ["Sarah", "George", "Ravi"],
        "segments": ground_truth_segments,
        "ground_truth_mom": {
            "decisions": [
                "Deploy the temporary authentication workaround today",
                "Release the permanent login patch on Friday",
            ],
            "action_items": [
                {
                    "speaker": "George",
                    "task": "Take ownership of the permanent login patch and complete it",
                    "deadline": "Friday at 5 PM",
                },
                {
                    "speaker": "Ravi",
                    "task": "Notify the customer support team about the known issue",
                    "deadline": "2 PM today",
                },
            ],
        },
    }

    gt_file = output_dir / "test_meeting_3speakers_ground_truth.json"
    with open(gt_file, "w", encoding="utf-8") as f:
        json.dump(ground_truth_meta, f, indent=2)

    print(f"\nSuccessfully created: {final_output}")
    print(f"Ground truth saved to: {gt_file}")
    print("Ground truth: 3 distinct voices (Sarah: en-US-Jenny, George: en-US-Guy, Ravi: en-GB-Ryan).")

if __name__ == "__main__":
    asyncio.run(build_audio())

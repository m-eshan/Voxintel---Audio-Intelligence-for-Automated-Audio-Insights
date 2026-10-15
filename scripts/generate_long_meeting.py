import asyncio
import json
import shutil
import subprocess
from pathlib import Path
import edge_tts
import librosa

# 18-turn realistic engineering sprint and architecture planning meeting (~5 minutes)
# Speakers: Elena (PM), Marcus (Frontend), Kavita (Backend/DevOps), David (Security/QA)
LONG_SCRIPT = [
    ("Elena", "en-IE-EmilyNeural", "Good morning everyone. Welcome to our quarterly platform synchronization meeting. Today we need to address database query latency, the customer dashboard redesign, and the new OAuth two security migration. Let's start with the database performance issues reported in production."),
    ("Kavita", "en-IN-NeerjaNeural", "Thanks Elena. Over the weekend, query latency spiked to eight hundred milliseconds during peak traffic. The root cause is missing indexes on the audit log table and inefficient connection pooling in our microservices."),
    ("Marcus", "en-AU-WilliamMultilingualNeural", "That latency directly impacted the web dashboard. User sessions were timing out while loading recent order histories, causing multiple client complaints."),
    ("David", "en-CA-LiamNeural", "From the QA perspective, we reproduced the timeout on the staging environment under a simulated load of two thousand concurrent requests. We need both an immediate database index patch and query optimization."),
    ("Elena", "en-IE-EmilyNeural", "Understood. Kavita, what is your proposed timeline for deploying the database fix to production?"),
    ("Kavita", "en-IN-NeerjaNeural", "I will add the composite database indexes and optimize connection pool parameters by Wednesday at 3 PM."),
    ("Elena", "en-IE-EmilyNeural", "Approved. We decide to schedule the database maintenance window for Wednesday night at 11 PM to minimize user impact."),
    ("Marcus", "en-AU-WilliamMultilingualNeural", "Regarding the customer dashboard redesign, our frontend team has finished the initial mockups and responsive layout components. However, we are waiting for the updated API schemas from backend."),
    ("Kavita", "en-IN-NeerjaNeural", "The GraphQL schema definition is ready. I will publish the updated API schema documentation to the developer portal by Thursday at 12 PM."),
    ("Marcus", "en-AU-WilliamMultilingualNeural", "Perfect. Once that schema is published, I'll integrate the new dashboard widgets and finalize frontend responsive testing by next Monday at 5 PM."),
    ("David", "en-CA-LiamNeural", "Before we push the new dashboard to production, security must review the third-party charting libraries. We detected two outdated dependencies with reported vulnerabilities."),
    ("Elena", "en-IE-EmilyNeural", "Good catch, David. What is needed to clear those vulnerabilities?"),
    ("David", "en-CA-LiamNeural", "I will run a full security vulnerability audit on frontend dependencies and share the remediation report by Friday at 2 PM."),
    ("Marcus", "en-AU-WilliamMultilingualNeural", "I will upgrade the vulnerable charting dependencies to their latest patched versions as soon as David shares the audit report."),
    ("Elena", "en-IE-EmilyNeural", "Excellent. Let's address our third topic, OAuth two migration. David, what is our status on deprecating legacy basic authentication?"),
    ("David", "en-CA-LiamNeural", "Legacy authentication has already been deprecated on staging. We decide to enforce mandatory OAuth two authentication on all production endpoints starting the first of next month."),
    ("Elena", "en-IE-EmilyNeural", "Agreed. I will draft the official customer migration announcement and publish it to the product blog by Friday at 4 PM."),
    ("Elena", "en-IE-EmilyNeural", "Great progress today team. Database maintenance is set for Wednesday, API schemas on Thursday, security audit and blog post on Friday, and dashboard integration by Monday. Let's adjourn."),
]

async def build_long_meeting():
    output_dir = Path("data/samples")
    output_dir.mkdir(parents=True, exist_ok=True)
    temp_files = []
    ground_truth_segments = []

    print("Generating 18 distinct neural voice segments for ~5-minute meeting...")
    current_time = 0.0
    for i, (speaker, voice, text) in enumerate(LONG_SCRIPT):
        part_name = f"_temp_long_{i:02d}.mp3"
        temp_files.append(part_name)
        communicator = edge_tts.Communicate(text, voice)
        await communicator.save(part_name)
        dur = float(librosa.get_duration(path=part_name))
        ground_truth_segments.append({
            "segment_id": f"L{i+1}",
            "turn_index": i + 1,
            "speaker": speaker,
            "voice": voice,
            "start": round(current_time, 2),
            "end": round(current_time + dur, 2),
            "duration": round(dur, 2),
            "text": text,
        })
        current_time += dur
        print(f"  [{speaker}] ({round(current_time - dur, 1)}s - {round(current_time, 1)}s) using {voice}")

    concat_list_file = Path("_temp_long_concat_list.txt")
    with concat_list_file.open("w", encoding="utf-8") as f:
        for p in temp_files:
            f.write(f"file '{p}'\n")

    ffmpeg_bin = shutil.which("ffmpeg") or "ffmpeg"
    final_output = output_dir / "test_meeting_long_4speakers.mp3"

    print(f"\nConcatenating segments into {final_output} (Total: {current_time/60:.1f} minutes)...")
    subprocess.run(
        [ffmpeg_bin, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list_file), "-c", "copy", str(final_output)],
        check=True
    )

    # Cleanup temporary parts
    concat_list_file.unlink(missing_ok=True)
    for p in temp_files:
        Path(p).unlink(missing_ok=True)

    ground_truth_meta = {
        "audio_file": "test_meeting_long_4speakers.mp3",
        "total_duration_seconds": round(current_time, 2),
        "total_duration_minutes": round(current_time / 60.0, 2),
        "speakers": ["Elena", "Marcus", "Kavita", "David"],
        "segments": ground_truth_segments,
        "ground_truth_mom": {
            "decisions": [
                {
                    "speaker": "Elena",
                    "decision": "Schedule the database maintenance window for Wednesday night at 11 PM",
                    "turn": 7
                },
                {
                    "speaker": "David",
                    "decision": "Enforce mandatory OAuth two authentication on all production endpoints starting the first of next month",
                    "turn": 16
                }
            ],
            "action_items": [
                {
                    "speaker": "Kavita",
                    "task": "Add composite database indexes and optimize connection pool parameters",
                    "deadline": "Wednesday at 3 PM",
                    "turn": 6
                },
                {
                    "speaker": "Kavita",
                    "task": "Publish the updated API schema documentation to the developer portal",
                    "deadline": "Thursday at 12 PM",
                    "turn": 9
                },
                {
                    "speaker": "Marcus",
                    "task": "Integrate the new dashboard widgets and finalize frontend responsive testing",
                    "deadline": "next Monday at 5 PM",
                    "turn": 10
                },
                {
                    "speaker": "David",
                    "task": "Run a full security vulnerability audit on frontend dependencies and share the remediation report",
                    "deadline": "Friday at 2 PM",
                    "turn": 13
                },
                {
                    "speaker": "Marcus",
                    "task": "Upgrade the vulnerable charting dependencies to their latest patched versions",
                    "deadline": "as soon as David shares the audit report",
                    "turn": 14
                },
                {
                    "speaker": "Elena",
                    "task": "Draft the official customer migration announcement and publish it to the product blog",
                    "deadline": "Friday at 4 PM",
                    "turn": 17
                }
            ]
        }
    }

    gt_file = output_dir / "test_meeting_long_4speakers_ground_truth.json"
    with open(gt_file, "w", encoding="utf-8") as f:
        json.dump(ground_truth_meta, f, indent=2)

    print(f"\nSuccessfully generated held-out benchmark: {final_output}")
    print(f"Ground truth saved to: {gt_file}")

if __name__ == "__main__":
    asyncio.run(build_long_meeting())

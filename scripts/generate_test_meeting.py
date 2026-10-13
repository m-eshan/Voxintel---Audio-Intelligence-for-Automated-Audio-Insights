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
    output_dir = Path("data/samples")
    output_dir.mkdir(parents=True, exist_ok=True)
    temp_files = []

    print("Generating distinct neural voice segments with edge-tts...")
    for i, (speaker, voice, text) in enumerate(SCRIPT):
        part_name = f"_temp_part_{i:02d}.mp3"
        temp_files.append(part_name)
        communicator = edge_tts.Communicate(text, voice)
        await communicator.save(part_name)
        print(f"  [{speaker}] using {voice}")

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

    print(f"\nSuccessfully created: {final_output}")
    print("Ground truth: 3 distinct voices (Sarah: en-US-Jenny, George: en-US-Guy, Ravi: en-GB-Ryan).")

if __name__ == "__main__":
    asyncio.run(build_audio())

import asyncio
import json
import os
import subprocess
from pathlib import Path
from pydub import AudioSegment
import edge_tts

# Audio & ground-truth target paths
OUTPUT_AUDIO = Path("data/samples/test_meeting_3_unnamed.mp3")
OUTPUT_JSON = Path("data/samples/test_meeting_3_unnamed_ground_truth.json")
TEMP_DIR = Path("data/samples/_tmp_m3")

# 4 distinct international neural voices
VOICES = {
    "Speaker 1": "en-US-GuyNeural",               # American Male
    "Speaker 2": "en-GB-SoniaNeural",             # British Female
    "Speaker 3": "en-US-JennyNeural",             # American Female
    "Speaker 4": "en-IN-PrabhatNeural",           # Indian Male
}

# The dialogue script: 5+ minutes, 20 turns, high density of technical terms
# ABSOLUTE RULE: NO NAMES ARE SPOKEN ANYWHERE IN THE TEXT. NO SELF-NAMES, NO ADDRESSED NAMES.
TURNS = [
    {
        "turn": 1,
        "speaker": "Speaker 1",
        "text": "Good morning everyone. Let us begin our platform architecture review. Today we are addressing infrastructure stability issues, specifically Kubernetes pod crash loops in production, OAuth 2.0 token expiration mismatches, and severe Kafka consumer lag during peak transaction hours."
    },
    {
        "turn": 2,
        "speaker": "Speaker 3",
        "text": "Looking at the monitoring dashboards from yesterday's stress testing, memory usage on the ingress gateway exceeded ninety-two percent. The ingress controllers failed health probes because traffic spiked during the flash sale event, causing cascading connection resets."
    },
    {
        "turn": 3,
        "speaker": "Speaker 2",
        "text": "That gateway failure also exposed a vulnerability in our authentication layer. Multiple API clients triggered concurrent token refresh requests. Because the redis cluster was saturated, several microservices fell back to slow database queries, which completely exhausted our database connection pool."
    },
    {
        "turn": 4,
        "speaker": "Speaker 4",
        "text": "From the data streaming perspective, Kafka partition rebalancing took nearly four minutes to settle after the broker restart. Three consumer groups lost their partition offsets, leading to duplicate transaction processing in the ledger service."
    },
    {
        "turn": 5,
        "speaker": "Speaker 1",
        "text": "The root cause in the Kubernetes cluster appears to be improper CPU request limits on the payment processing pods. When burst traffic arrived, the Linux kernel throttled the containers, preventing timely keepalive pings."
    },
    {
        "turn": 6,
        "speaker": "Speaker 3",
        "text": "We ran a replica scaling experiment on the staging environment this morning with synthetic traffic. Scaling the pod replicas from three to eight maintained ninety-ninth percentile latency below one hundred and twenty milliseconds, even under three thousand concurrent requests per second."
    },
    {
        "turn": 7,
        "speaker": "Speaker 1",
        "text": "Approved. We decide to scale the Kubernetes cluster replicas from three to eight before the traffic surge."
    },
    {
        "turn": 8,
        "speaker": "Speaker 1",
        "text": "I will refactor the Kubernetes deployment manifests and update the Helm charts by Tuesday at 4 PM."
    },
    {
        "turn": 9,
        "speaker": "Speaker 2",
        "text": "Regarding authentication protocols, our legacy microservices are still accepting deprecated bearer tokens without cryptographically signed proof keys. This creates a security risk where stale access tokens can be replayed across different tenant boundaries."
    },
    {
        "turn": 10,
        "speaker": "Speaker 3",
        "text": "The mobile application engineering team already integrated the authorization code flow with PKCE on the staging build. However, the legacy backend proxy services lack the cryptographic verification filter needed to validate the code challenge."
    },
    {
        "turn": 11,
        "speaker": "Speaker 2",
        "text": "Approved. We decide to enforce strict OAuth 2.0 PKCE authentication across all external microservice gateways."
    },
    {
        "turn": 12,
        "speaker": "Speaker 2",
        "text": "I will audit the OAuth 2.0 token expiration policies and publish the revised security spec by Wednesday at 2 PM."
    },
    {
        "turn": 13,
        "speaker": "Speaker 4",
        "text": "On the messaging side, our Kafka brokers are currently configured with a default session timeout of forty-five seconds. When garbage collection pauses occur in our Java workers, the coordinator assumes the consumer died and triggers an expensive partition rebalance."
    },
    {
        "turn": 14,
        "speaker": "Speaker 3",
        "text": "Additionally, our Redis cache cluster is using an all-keys LRU eviction policy. When the session data spikes, critical static configuration keys are evicted prematurely, forcing unnecessary remote procedure calls."
    },
    {
        "turn": 15,
        "speaker": "Speaker 4",
        "text": "We need to switch Redis to volatile LRU and extend the Kafka heartbeat interval to fifteen seconds to prevent spurious group rebalances."
    },
    {
        "turn": 16,
        "speaker": "Speaker 4",
        "text": "I will configure the Kafka consumer partition rebalancing and optimize Redis cache eviction thresholds by Thursday at 5 PM."
    },
    {
        "turn": 17,
        "speaker": "Speaker 1",
        "text": "Excellent. What is our rollback strategy if the new Helm charts fail during the staging deployment?"
    },
    {
        "turn": 18,
        "speaker": "Speaker 3",
        "text": "The continuous integration pipeline maintains automated rollback hooks. If Prometheus reports an HTTP error rate exceeding one percent over a three-minute window, ArgoCD automatically reverts to the previous stable container image tag."
    },
    {
        "turn": 19,
        "speaker": "Speaker 2",
        "text": "That gives us confidence for staging validation. Once the security audit is published, we can schedule the production rollout window."
    },
    {
        "turn": 20,
        "speaker": "Speaker 4",
        "text": "We will monitor the Kafka consumer lag metrics and Redis memory consumption in real time through our centralized Prometheus and Grafana dashboards once the changes land."
    },
    {
        "turn": 21,
        "speaker": "Speaker 1",
        "text": "Agreed. To summarize our roadmap: Kubernetes scaling manifests are scheduled for Tuesday, OAuth 2.0 security policies for Wednesday, and Kafka and Redis optimization for Thursday. Let us adjourn and execute."
    }
]

# HAND-WRITTEN REFERENCE SUMMARY (WRITTEN BEFORE PIPELINE EXECUTION)
REFERENCE_SUMMARY = (
    "The engineering team reviewed infrastructure bottlenecks, focusing on Kubernetes cluster stability, "
    "OAuth 2.0 security protocols, Kafka consumer lag, and Redis caching. Two primary decisions were established: "
    "scaling Kubernetes pod replicas from three to eight and mandating OAuth 2.0 PKCE across external microservice gateways. "
    "Three commitments were confirmed: updating Helm deployment manifests by Tuesday at 4 PM, publishing the revised "
    "token expiration spec by Wednesday at 2 PM, and tuning Kafka partition rebalancing alongside Redis cache thresholds by Thursday at 5 PM."
)

GROUND_TRUTH_MOM = {
    "decisions": [
        {
            "speaker": "Speaker 1",
            "decision": "Scale the Kubernetes cluster replicas from three to eight before the traffic surge",
            "turn": 7
        },
        {
            "speaker": "Speaker 2",
            "decision": "Enforce strict OAuth 2.0 PKCE authentication across all external microservice gateways",
            "turn": 11
        }
    ],
    "action_items": [
        {
            "speaker": "Speaker 1",
            "task": "Refactor the Kubernetes deployment manifests and update the Helm charts",
            "deadline": "Tuesday at 4 PM",
            "turn": 8
        },
        {
            "speaker": "Speaker 2",
            "task": "Audit the OAuth 2.0 token expiration policies and publish the revised security spec",
            "deadline": "Wednesday at 2 PM",
            "turn": 12
        },
        {
            "speaker": "Speaker 4",
            "task": "Configure the Kafka consumer partition rebalancing and optimize Redis cache eviction thresholds",
            "deadline": "Thursday at 5 PM",
            "turn": 16
        }
    ]
}


async def generate_turn_audio(turn_data: dict, out_wav: Path):
    voice = VOICES[turn_data["speaker"]]
    text = turn_data["text"]
    communicate = edge_tts.Communicate(text, voice, rate="-6%")
    await communicate.save(str(out_wav))


async def build_meeting_3():
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_AUDIO.parent.mkdir(parents=True, exist_ok=True)

    print("Generating audio turns for Meeting 3 (5+ minutes, no spoken names)...")
    segments_metadata = []
    combined_audio = AudioSegment.silent(duration=1000)  # Initial pause

    current_time_ms = 1000

    for idx, turn in enumerate(TURNS, start=1):
        turn_file = TEMP_DIR / f"turn_{idx:02d}.mp3"
        print(f"  [Turn {idx:02d}/{len(TURNS)}] {turn['speaker']} ({VOICES[turn['speaker']]}): {turn['text'][:45]}...")
        await generate_turn_audio(turn, turn_file)

        turn_audio = AudioSegment.from_file(turn_file)
        start_sec = current_time_ms / 1000.0
        duration_ms = len(turn_audio)
        current_time_ms += duration_ms
        end_sec = current_time_ms / 1000.0

        segments_metadata.append({
            "segment_id": f"M3_{idx:02d}",
            "turn_index": idx,
            "speaker": turn["speaker"],
            "voice": VOICES[turn["speaker"]],
            "start": round(start_sec, 2),
            "end": round(end_sec, 2),
            "duration": round(duration_ms / 1000.0, 2),
            "text": turn["text"],
        })

        combined_audio += turn_audio
        # 1.3s natural pause between turns
        pause_ms = 1300
        combined_audio += AudioSegment.silent(duration=pause_ms)
        current_time_ms += pause_ms

    # Final padding
    combined_audio += AudioSegment.silent(duration=1000)

    total_duration_sec = len(combined_audio) / 1000.0
    print(f"\nExporting combined meeting audio: {OUTPUT_AUDIO}")
    combined_audio.export(OUTPUT_AUDIO, format="mp3", bitrate="192k")
    print(f"Total Audio Duration: {total_duration_sec:.2f} seconds ({total_duration_sec / 60.0:.2f} minutes)")

    # Cleanup temp
    for p in TEMP_DIR.glob("*.mp3"):
        p.unlink(missing_ok=True)
    TEMP_DIR.rmdir()

    # Save Ground Truth JSON
    gt_data = {
        "meeting_id": "meeting_3_unnamed_test_set",
        "audio_file": OUTPUT_AUDIO.name,
        "dataset_type": "test set",
        "total_duration_seconds": round(total_duration_sec, 2),
        "total_duration_minutes": round(total_duration_sec / 60.0, 2),
        "speakers": ["Speaker 1", "Speaker 2", "Speaker 3", "Speaker 4"],
        "segments": segments_metadata,
        "reference_summary": REFERENCE_SUMMARY,
        "ground_truth_mom": GROUND_TRUTH_MOM,
    }

    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(gt_data, f, indent=2)

    print(f"Ground-truth JSON with pre-written reference summary saved: {OUTPUT_JSON}")


if __name__ == "__main__":
    asyncio.run(build_meeting_3())

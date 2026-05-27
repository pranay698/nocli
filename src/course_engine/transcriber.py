from __future__ import annotations

import json
import re
import tempfile
from dataclasses import dataclass
from hashlib import sha1
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from google.cloud import speech
from google.cloud import storage

from . import gcs
from .media import extract_audio, require_ffmpeg


@dataclass(frozen=True)
class TranscriptionConfig:
    project_id: str
    input_prefix: str
    audio_prefix: str
    transcript_prefix: str
    language_code: str = "en-IN"
    limit: int | None = None
    skip_existing: bool = True
    dry_run: bool = False


def safe_stem(video_uri: str) -> str:
    if video_uri.startswith("gs://"):
        parsed = gcs.GcsUri.parse(video_uri)
        path = Path(parsed.blob)
        stem = path.with_suffix("").as_posix().replace("/", "__")
    else:
        stem = source_stem(video_uri)
    return "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in stem)


def source_stem(source_uri: str) -> str:
    parsed = urlparse(source_uri)
    drive_match = re.search(r"/file/d/([^/]+)", source_uri)
    query_id = parse_qs(parsed.query).get("id", [""])[0]
    if drive_match:
        base = f"google_drive_{drive_match.group(1)}"
    elif query_id:
        base = f"remote_{query_id}"
    else:
        path_name = Path(unquote(parsed.path)).stem
        base = path_name or parsed.netloc or "remote_source"
    digest = sha1(source_uri.encode("utf-8")).hexdigest()[:10]
    return f"{base}_{digest}"


def transcript_uris(config: TranscriptionConfig, video_uri: str) -> tuple[str, str]:
    stem = safe_stem(video_uri)
    prefix = gcs.GcsUri.parse(config.transcript_prefix)
    return prefix.join(f"{stem}.json"), prefix.join(f"{stem}.txt")


def audio_uri(config: TranscriptionConfig, video_uri: str) -> str:
    stem = safe_stem(video_uri)
    return gcs.GcsUri.parse(config.audio_prefix).join(f"{stem}.flac")


def run_transcription(config: TranscriptionConfig) -> None:
    storage_client = storage.Client(project=config.project_id)
    speech_client = speech.SpeechClient()
    if not config.dry_run:
        require_ffmpeg()

    video_uris = gcs.list_video_uris(storage_client, config.input_prefix)
    if config.limit is not None:
        video_uris = video_uris[: config.limit]

    print(f"Found {len(video_uris)} video(s).")
    for index, video_uri in enumerate(video_uris, start=1):
        json_uri, txt_uri = transcript_uris(config, video_uri)
        if config.skip_existing and gcs.exists(storage_client, json_uri):
            print(f"[{index}/{len(video_uris)}] Skipping existing transcript: {video_uri}")
            continue

        print(f"[{index}/{len(video_uris)}] Processing {video_uri}")
        if config.dry_run:
            print(f"  would write audio: {audio_uri(config, video_uri)}")
            print(f"  would write transcript: {json_uri}")
            continue

        result = transcribe_one(storage_client, speech_client, config, video_uri)
        gcs.upload_text(storage_client, json.dumps(result, indent=2), json_uri, "application/json")
        gcs.upload_text(storage_client, result["transcript"], txt_uri, "text/plain")
        print(f"  saved {json_uri}")


def transcribe_one(
    storage_client: storage.Client,
    speech_client: speech.SpeechClient,
    config: TranscriptionConfig,
    video_uri: str,
) -> dict:
    target_audio_uri = audio_uri(config, video_uri)
    with tempfile.TemporaryDirectory() as temp_dir:
        temp = Path(temp_dir)
        video_path = temp / Path(gcs.GcsUri.parse(video_uri).blob).name
        audio_path = temp / f"{safe_stem(video_uri)}.flac"
        gcs.download(storage_client, video_uri, video_path)
        extract_audio(video_path, audio_path)
        gcs.upload(storage_client, audio_path, target_audio_uri, "audio/flac")

    audio = speech.RecognitionAudio(uri=target_audio_uri)
    recognition_config = speech.RecognitionConfig(
        encoding=speech.RecognitionConfig.AudioEncoding.FLAC,
        sample_rate_hertz=16000,
        language_code=config.language_code,
        enable_automatic_punctuation=True,
        enable_word_time_offsets=True,
        audio_channel_count=1,
    )
    operation = speech_client.long_running_recognize(config=recognition_config, audio=audio)
    response = operation.result(timeout=7200)

    segments = []
    transcript_parts = []
    for result in response.results:
        if not result.alternatives:
            continue
        alternative = result.alternatives[0]
        text = alternative.transcript.strip()
        if not text:
            continue
        transcript_parts.append(text)
        start_seconds = None
        end_seconds = None
        if alternative.words:
            start_seconds = alternative.words[0].start_time.total_seconds()
            end_seconds = alternative.words[-1].end_time.total_seconds()
        segments.append(
            {
                "start_seconds": start_seconds,
                "end_seconds": end_seconds,
                "start": format_timestamp(start_seconds),
                "end": format_timestamp(end_seconds),
                "text": text,
                "confidence": result.alternatives[0].confidence,
            }
        )

    return {
        "video_id": safe_stem(video_uri),
        "source_video_url": video_uri,
        "audio_url": target_audio_uri,
        "language_code": config.language_code,
        "transcript": " ".join(transcript_parts),
        "segments": segments,
    }


def format_timestamp(seconds: float | None) -> str | None:
    if seconds is None:
        return None
    seconds = int(seconds)
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"

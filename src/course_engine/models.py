from __future__ import annotations

from dataclasses import dataclass


TASK_STATUSES = {"queued", "running", "done", "failed", "canceled"}


@dataclass(frozen=True)
class TaskRequest:
    source_type: str
    source_value: str
    engine: str
    transcript_prefix: str
    audio_prefix: str
    language_code: str = "en-IN"
    save_mp3: bool = True
    chunk_minutes: int = 0


ENGINES = {
    "download_only": "Download to GCS",
    "convert_mp3": "Convert to MP3 only",
    "transcript_import": "Import existing transcript",
    "google_speech": "Google Speech-to-Text",
    "whisper_tiny": "Whisper tiny",
    "whisper_small": "Whisper small",
    "whisper_large_turbo": "Whisper large-v3-turbo",
}


SOURCE_TYPES = {
    "google_drive": "Google Drive public file",
    "google_drive_folder": "Google Drive public folder",
    "drive_ytdlp_mp3": "Google Drive video to MP3 with yt-dlp",
    "mp3_drive": "Google Drive MP3 file",
    "transcript_drive_doc": "Google Drive Doc transcript",
    "transcript_drive_txt": "Google Drive TXT transcript",
    "gcs": "Google Cloud Storage file",
    "gcs_folder": "Google Cloud Storage folder",
    "mp3_gcs": "Google Cloud Storage MP3 file",
    "transcript_gcs": "Google Cloud Storage TXT transcript",
    "upload": "Uploaded video",
    "mp3_upload": "Uploaded MP3",
    "transcript_upload": "Uploaded transcript",
    "public_url": "Public video/audio URL",
    "mp3_public": "Public MP3 URL",
    "transcript_public": "Public TXT transcript URL",
    "r2": "Cloudflare R2 public file",
    "mp3_r2": "Cloudflare R2 public MP3",
}

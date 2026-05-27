from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def require_ffmpeg() -> None:
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg is required. Install it before running transcription.")


def extract_audio(video_path: Path, audio_path: Path) -> None:
    audio_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "ffmpeg",
        "-y",
        "-i",
        str(video_path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-c:a",
        "flac",
        str(audio_path),
    ]
    completed = subprocess.run(command, check=False, capture_output=True, text=True)
    if completed.returncode != 0:
        raise RuntimeError(f"ffmpeg failed for {video_path.name}: {completed.stderr[-2000:]}")


def convert_to_mp3(video_path: Path, mp3_path: Path) -> None:
    mp3_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "ffmpeg",
        "-y",
        "-i",
        str(video_path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "44100",
        "-b:a",
        "96k",
        str(mp3_path),
    ]
    completed = subprocess.run(command, check=False, capture_output=True, text=True)
    if completed.returncode != 0:
        raise RuntimeError(f"ffmpeg mp3 conversion failed for {video_path.name}: {_clean_ffmpeg_error(completed.stderr)}")


def split_audio(audio_path: Path, output_dir: Path, chunk_minutes: int) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    pattern = output_dir / "chunk_%04d.mp3"
    command = [
        "ffmpeg",
        "-y",
        "-i",
        str(audio_path),
        "-f",
        "segment",
        "-segment_time",
        str(chunk_minutes * 60),
        "-c",
        "copy",
        str(pattern),
    ]
    completed = subprocess.run(command, check=False, capture_output=True, text=True)
    if completed.returncode != 0:
        raise RuntimeError(f"ffmpeg chunk split failed for {audio_path.name}: {_clean_ffmpeg_error(completed.stderr)}")
    return sorted(output_dir.glob("chunk_*.mp3"))


def _clean_ffmpeg_error(stderr: str) -> str:
    compact = " ".join(stderr.split())
    lower = compact.lower()
    if "moov atom not found" in lower or "invalid data found when processing input" in lower:
        return (
            "Input is not a valid playable media file. For Google Drive links, confirm the file is shared as "
            "'Anyone with the link: Viewer', then use the Downloader tab to import it into GCS before transcription."
        )
    return compact[-1000:]

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import requests
import google.auth
from google.auth.transport.requests import AuthorizedSession
from google.cloud import storage

from . import gcs


MP3_SOURCE_TYPES = {"drive_ytdlp_mp3", "mp3_drive", "mp3_gcs", "mp3_upload", "mp3_public", "mp3_r2"}
TRANSCRIPT_SOURCE_TYPES = {"transcript_drive_doc", "transcript_drive_txt", "transcript_gcs", "transcript_upload", "transcript_public"}


def filename_from_url(url: str, fallback: str = "video") -> str:
    parsed = urlparse(url)
    name = Path(unquote(parsed.path)).name
    return name or fallback


def google_drive_file_id(url: str) -> str | None:
    patterns = [
        r"/file/d/([^/]+)",
        r"/document/d/([^/]+)",
        r"[?&]id=([^&]+)",
        r"/d/([^/]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def google_drive_folder_id(url: str) -> str | None:
    match = re.search(r"/folders/([^/?]+)", url)
    if match:
        return match.group(1)
    query_id = parse_qs(urlparse(url).query).get("id")
    return query_id[0] if query_id else None


def download_http(url: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url, stream=True, timeout=60) as response:
        response.raise_for_status()
        with path.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    handle.write(chunk)
    validate_download(path, source_label=url)


def download_http_text(url: str) -> str:
    response = requests.get(url, timeout=60)
    response.raise_for_status()
    text = response.text
    validate_text_content(text, url)
    return text


def download_source(storage_client: storage.Client, source_type: str, source_value: str, target_dir: Path) -> Path:
    if source_type in {"gcs", "upload", "mp3_gcs", "mp3_upload"}:
        name = Path(gcs.GcsUri.parse(source_value).blob).name
        target = target_dir / name
        gcs.download(storage_client, source_value, target)
        if source_type in MP3_SOURCE_TYPES:
            validate_download(target, source_label=source_value, require_playable=True)
        return target

    if source_type == "drive_ytdlp_mp3":
        file_id = google_drive_file_id(source_value)
        if not file_id:
            raise ValueError("Could not find a Google Drive file id in the link.")
        target = target_dir / f"google-drive-{file_id}.mp3"
        download_google_drive_audio_with_ytdlp(source_value, target)
        return target

    if source_type in {"google_drive", "mp3_drive"}:
        file_id = google_drive_file_id(source_value)
        if not file_id:
            raise ValueError("Could not find a Google Drive file id in the link.")
        extension = ".mp3" if source_type == "mp3_drive" else ".mp4"
        target = target_dir / f"google-drive-{file_id}{extension}"
        download_google_drive(file_id, source_value, target, media_label="audio file" if source_type == "mp3_drive" else "video file")
        return target

    if source_type in {"r2", "public_url", "mp3_public", "mp3_r2"}:
        target = target_dir / filename_from_url(source_value, "r2-video")
        download_http(source_value, target)
        if source_type in MP3_SOURCE_TYPES:
            validate_download(target, source_label=source_value, require_playable=True)
        return target

    if source_type.startswith("http"):
        target = target_dir / filename_from_url(source_value, "remote-video")
        download_http(source_value, target)
        return target

    raise ValueError(f"Unsupported source type: {source_type}")


def read_transcript_source(storage_client: storage.Client, source_type: str, source_value: str, target_dir: Path) -> tuple[str, str]:
    if source_type in {"transcript_gcs", "transcript_upload"}:
        text = gcs.download_text(storage_client, source_value)
        validate_text_content(text, source_value)
        return text, source_value

    if source_type == "transcript_public":
        return download_http_text(source_value), source_value

    if source_type == "transcript_drive_doc":
        file_id = google_drive_file_id(source_value)
        if not file_id:
            raise ValueError("Could not find a Google Drive document id in the link.")
        export_url = f"https://docs.google.com/document/d/{file_id}/export?format=txt"
        return download_http_text(export_url), source_value

    if source_type == "transcript_drive_txt":
        file_id = google_drive_file_id(source_value)
        if not file_id:
            raise ValueError("Could not find a Google Drive file id in the link.")
        target = target_dir / f"google-drive-{file_id}.txt"
        download_google_drive(file_id, source_value, target, media_label="text transcript", require_playable=False, min_bytes=1)
        text = target.read_text(encoding="utf-8", errors="replace")
        validate_text_content(text, source_value)
        return text, source_value

    raise ValueError(f"Unsupported transcript source type: {source_type}")


def validate_text_content(text: str, source_label: str) -> None:
    if not text.strip():
        raise ValueError(f"Transcript file is empty: {source_label}")
    head = text[:4096].lower()
    html_markers = ["<!doctype html", "<html", "accounts.google.com", "access denied", "quota exceeded"]
    if any(marker in head for marker in html_markers):
        raise ValueError(f"Downloaded content is not a plain transcript file. {source_label}")


def download_google_drive(
    file_id: str,
    source_url: str,
    target: Path,
    media_label: str = "video file",
    require_playable: bool = True,
    min_bytes: int = 1024 * 32,
) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    source_label = (
        f"Google Drive did not return a valid {media_label}. "
        "Set sharing to 'Anyone with the link: Viewer'. If it still fails, use the app Downloader tab "
        "to import the Drive file into GCS first, then transcribe the saved gs:// file."
    )
    attempts = [
        ("gdown-url", lambda: _download_google_drive_with_gdown(source_url, file_id, target)),
        ("drive-confirm", lambda: _download_google_drive_with_confirm_token(file_id, target)),
        ("yt-dlp", lambda: _download_google_drive_with_ytdlp(source_url, target)),
    ]
    errors = []
    for name, downloader in attempts:
        if target.exists():
            target.unlink()
        try:
            downloader()
            validate_download(target, source_label=source_label, require_playable=require_playable, min_bytes=min_bytes)
            return
        except Exception as exc:
            errors.append(f"{name}: {exc}")
    raise ValueError(f"{source_label} Attempts failed: {' | '.join(errors)}")


def download_google_drive_audio_with_ytdlp(source_url: str, target: Path) -> None:
    source_label = (
        "yt-dlp could not extract MP3 from this Google Drive video link. "
        "Set sharing to 'Anyone with the link: Viewer', or import the file into GCS first."
    )
    if target.exists():
        target.unlink()
    _download_google_drive_with_ytdlp(source_url, target)
    validate_download(target, source_label=source_label, require_playable=True)


def _download_google_drive_with_gdown(source_url: str, file_id: str, target: Path) -> None:
    import gdown

    result = gdown.download(url=source_url, output=str(target), quiet=True, fuzzy=True)
    if result is None:
        result = gdown.download(id=file_id, output=str(target), quiet=True, fuzzy=True)
    if result is None:
        raise RuntimeError("gdown did not return a downloaded file")


def _download_google_drive_with_ytdlp(source_url: str, target: Path) -> None:
    from yt_dlp import YoutubeDL

    target.parent.mkdir(parents=True, exist_ok=True)
    scratch_template = str(target.with_name(f"{target.stem}.yt-dlp.%(ext)s"))
    options = {
        "outtmpl": scratch_template,
        "quiet": True,
        "noplaylist": True,
        "retries": 3,
        "fragment_retries": 3,
        "windowsfilenames": True,
    }
    if target.suffix.lower() == ".mp3":
        options["format"] = "bestaudio/best"
        options["postprocessors"] = [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "128",
            }
        ]
    else:
        options["format"] = "best[ext=mp4]/best"
        options["merge_output_format"] = target.suffix.lstrip(".") or "mp4"

    before = set(target.parent.glob(f"{target.stem}.yt-dlp.*"))
    with YoutubeDL(options) as downloader:
        downloader.download([source_url])
    after = set(target.parent.glob(f"{target.stem}.yt-dlp.*"))
    created = sorted(after - before, key=lambda path: path.stat().st_mtime, reverse=True)
    if not created:
        created = sorted(target.parent.glob(f"{target.stem}.yt-dlp.*"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not created:
        raise RuntimeError("yt-dlp did not create a downloaded file")
    created[0].replace(target)


def _download_google_drive_with_confirm_token(file_id: str, target: Path) -> None:
    session = requests.Session()
    response = session.get("https://drive.google.com/uc", params={"export": "download", "id": file_id}, stream=True, timeout=60)
    response.raise_for_status()
    token = _drive_confirm_token(response)
    if token:
        response.close()
        response = session.get(
            "https://drive.google.com/uc",
            params={"export": "download", "confirm": token, "id": file_id},
            stream=True,
            timeout=60,
        )
        response.raise_for_status()
    else:
        response.close()
        response = session.get(f"https://drive.usercontent.google.com/download", params={"id": file_id, "export": "download"}, stream=True, timeout=60)
        response.raise_for_status()
    _write_stream(response, target)


def _drive_confirm_token(response: requests.Response) -> str | None:
    for key, value in response.cookies.items():
        if key.startswith("download_warning"):
            return value
    content_type = response.headers.get("content-type", "")
    if "text/html" not in content_type:
        return None
    text = response.text
    match = re.search(r"confirm=([0-9A-Za-z_\\-]+)", text)
    return match.group(1) if match else None


def _write_stream(response: requests.Response, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with response:
        with target.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    handle.write(chunk)


def validate_download(path: Path, source_label: str, require_playable: bool = False, min_bytes: int = 1024 * 32) -> None:
    if not path.exists() or path.stat().st_size == 0:
        raise ValueError(f"Downloaded file is empty: {source_label}")
    if min_bytes and path.stat().st_size < min_bytes:
        raise ValueError(f"Downloaded file is too small to be a valid media file. {source_label}")
    head = path.read_bytes()[:65536].lower()
    html_markers = [
        b"<!doctype html",
        b"<html",
        b"accounts.google.com",
        b"drive.google.com",
        b"google drive - virus scan warning",
        b"quota exceeded",
        b"access denied",
    ]
    if any(marker in head for marker in html_markers):
        raise ValueError(f"Downloaded content is not a media file. {source_label}")
    if require_playable:
        validate_playable_media(path, source_label)


def validate_playable_media(path: Path, source_label: str) -> None:
    if shutil.which("ffprobe") is None:
        return
    completed = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
        check=False,
        capture_output=True,
        text=True,
        timeout=90,
    )
    if completed.returncode != 0:
        stderr = " ".join(completed.stderr.split())[:500]
        raise ValueError(f"Downloaded file is not a playable media file. {source_label} ffprobe: {stderr}")


VIDEO_MIME_PREFIXES = ("video/",)
VIDEO_MIME_TYPES = {"application/vnd.google-apps.video"}


def expand_folder_source(storage_client: storage.Client | None, source_type: str, source_value: str) -> list[tuple[str, str] | tuple[str, str, str]]:
    if source_type == "gcs_folder":
        if storage_client is None:
            raise ValueError("A Google Cloud Storage client is required for GCS folders.")
        return [("gcs", uri) for uri in gcs.list_video_uris(storage_client, source_value)]

    if source_type == "google_drive_folder":
        api_key = os.getenv("GOOGLE_DRIVE_API_KEY")
        folder_id = google_drive_folder_id(source_value)
        if not folder_id:
            raise ValueError("Could not find a Google Drive folder id in the link.")
        course_name = _google_drive_folder_name(api_key, folder_id) or "Google Drive course folder"
        return _list_google_drive_folder_videos(api_key, folder_id, course_name)

    return [(source_type, source_value)]


def _drive_get(api_key: str | None, url: str, params: dict) -> requests.Response:
    request_params = {key: value for key, value in params.items() if value is not None}
    if api_key:
        request_params["key"] = api_key
        return requests.get(url, params=request_params, timeout=30)
    credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/drive.readonly"])
    session = AuthorizedSession(credentials)
    return session.get(url, params=request_params, timeout=30)


def _google_drive_folder_name(api_key: str | None, folder_id: str) -> str | None:
    response = _drive_get(
        api_key,
        f"https://www.googleapis.com/drive/v3/files/{folder_id}",
        {"fields": "name"},
    )
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.json().get("name")


def _list_google_drive_folder_videos(api_key: str | None, folder_id: str, path: str) -> list[tuple[str, str, str]]:
    results: list[tuple[str, str, str]] = []
    page_token = None
    while True:
        response = _drive_get(
            api_key,
            "https://www.googleapis.com/drive/v3/files",
            {
                "q": f"'{folder_id}' in parents and trashed = false",
                "fields": "nextPageToken,files(id,name,mimeType)",
                "pageSize": 1000,
                "pageToken": page_token,
            },
        )
        response.raise_for_status()
        payload = response.json()
        for item in payload.get("files", []):
            name = item.get("name") or item["id"]
            mime_type = item.get("mimeType", "")
            child_path = f"{path}/{name}"
            if mime_type == "application/vnd.google-apps.folder":
                results.extend(_list_google_drive_folder_videos(api_key, item["id"], child_path))
            elif mime_type.startswith(VIDEO_MIME_PREFIXES) or mime_type in VIDEO_MIME_TYPES:
                results.append(("google_drive", f"https://drive.google.com/file/d/{item['id']}/view", child_path))
        page_token = payload.get("nextPageToken")
        if not page_token:
            break
    return results

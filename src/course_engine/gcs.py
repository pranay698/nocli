from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable

if TYPE_CHECKING:
    from google.cloud import storage


@dataclass(frozen=True)
class GcsUri:
    bucket: str
    blob: str

    @classmethod
    def parse(cls, uri: str) -> "GcsUri":
        if not uri.startswith("gs://"):
            raise ValueError(f"Expected a GCS URI starting with gs://, got {uri!r}")
        without_scheme = uri[5:]
        bucket, _, blob = without_scheme.partition("/")
        if not bucket:
            raise ValueError(f"Missing bucket name in {uri!r}")
        return cls(bucket=bucket, blob=blob)

    def join(self, *parts: str) -> str:
        prefix = self.blob.rstrip("/")
        suffix = "/".join(part.strip("/") for part in parts if part)
        blob = f"{prefix}/{suffix}" if prefix and suffix else prefix or suffix
        return f"gs://{self.bucket}/{blob}"

    @property
    def uri(self) -> str:
        return f"gs://{self.bucket}/{self.blob}"


VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi"}


def list_video_uris(client: Any, input_prefix: str) -> list[str]:
    parsed = GcsUri.parse(input_prefix)
    blobs = client.list_blobs(parsed.bucket, prefix=parsed.blob)
    videos = []
    for blob in blobs:
        if blob.name.endswith("/"):
            continue
        if Path(blob.name).suffix.lower() in VIDEO_EXTENSIONS:
            videos.append(f"gs://{parsed.bucket}/{blob.name}")
    return sorted(videos)


def exists(client: Any, uri: str) -> bool:
    parsed = GcsUri.parse(uri)
    return client.bucket(parsed.bucket).blob(parsed.blob).exists()


def download(client: Any, uri: str, path: Path) -> None:
    parsed = GcsUri.parse(uri)
    path.parent.mkdir(parents=True, exist_ok=True)
    client.bucket(parsed.bucket).blob(parsed.blob).download_to_filename(path)


def upload(client: Any, path: Path, uri: str, content_type: str | None = None) -> None:
    parsed = GcsUri.parse(uri)
    blob = client.bucket(parsed.bucket).blob(parsed.blob)
    blob.upload_from_filename(path, content_type=content_type)


def upload_text(client: Any, text: str, uri: str, content_type: str = "text/plain") -> None:
    parsed = GcsUri.parse(uri)
    blob = client.bucket(parsed.bucket).blob(parsed.blob)
    blob.upload_from_string(text, content_type=content_type)


def download_text(client: Any, uri: str) -> str:
    parsed = GcsUri.parse(uri)
    return client.bucket(parsed.bucket).blob(parsed.blob).download_as_text()


def list_json_uris(client: Any, prefix: str) -> Iterable[str]:
    parsed = GcsUri.parse(prefix)
    for blob in client.list_blobs(parsed.bucket, prefix=parsed.blob):
        if blob.name.endswith(".json"):
            yield f"gs://{parsed.bucket}/{blob.name}"

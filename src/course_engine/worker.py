from __future__ import annotations

import json
import tempfile
import threading
import time
from pathlib import Path

from google.cloud import storage

from . import gcs
from .engines import combine_transcript_results, offset_transcript_result, transcribe_with_google, transcribe_with_whisper
from .job_store import JobStore, task_log_payload
from .media import convert_to_mp3, require_ffmpeg, split_audio
from .sources import MP3_SOURCE_TYPES, TRANSCRIPT_SOURCE_TYPES, download_source, read_transcript_source
from .transcriber import safe_stem


class TaskCanceled(RuntimeError):
    pass


class QueueWorker:
    def __init__(self, store: JobStore, poll_seconds: int = 3, worker_count: int = 1):
        self.store = store
        self.poll_seconds = poll_seconds
        self.worker_count = max(1, worker_count)
        self._threads: list[threading.Thread] = []
        self._stop = threading.Event()

    def start(self) -> None:
        if any(thread.is_alive() for thread in self._threads):
            return
        self._threads = [
            threading.Thread(target=self._run, name=f"transcription-worker-{index + 1}", daemon=True)
            for index in range(self.worker_count)
        ]
        for thread in self._threads:
            thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            task = self.store.next_queued()
            if task is None:
                time.sleep(self.poll_seconds)
                continue
            try:
                self._process(task)
            except TaskCanceled:
                self.store.update_task(
                    task["id"],
                    status="canceled",
                    progress=100,
                    stage="canceled",
                    message="Canceled by user",
                )
            except Exception as exc:
                self.store.update_task(
                    task["id"],
                    status="failed",
                    progress=100,
                    stage="failed",
                    error=str(exc),
                    message=f"Failed: {exc}",
                )
                try:
                    self._write_task_log(storage.Client(), task["id"])
                except Exception:
                    pass

    def _process(self, task: dict) -> None:
        storage_client = storage.Client()
        task_id = task["id"]
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            stem = safe_stem(task["source_value"])

            if task["source_type"] in TRANSCRIPT_SOURCE_TYPES or task["engine"] == "transcript_import":
                self._import_transcript(storage_client, task, task_id, stem, temp)
                return

            require_ffmpeg()

            if task["engine"] == "download_only":
                self._ensure_not_canceled(task_id)
                self.store.update_task(task_id, progress=15, stage="downloading_source", message="Downloading source")
                video_path = download_source(storage_client, task["source_type"], task["source_value"], temp)
                self._ensure_not_canceled(task_id)
                destination_uri = gcs.GcsUri.parse(task["transcript_prefix"]).join(video_path.name)
                self.store.update_task(task_id, progress=75, stage="uploading_source", message="Uploading source to GCS")
                gcs.upload(storage_client, video_path, destination_uri)
                self._ensure_not_canceled(task_id)
                self.store.update_task(
                    task_id,
                    status="done",
                    progress=100,
                    stage="download_saved",
                    saved_source_uri=destination_uri,
                    transcript_uri=destination_uri,
                    message="Downloaded to GCS",
                )
                self._write_task_log(storage_client, task_id)
                return

            mp3_path = temp / f"{stem}.mp3"
            mp3_uri = task.get("mp3_uri")
            if mp3_uri:
                self._ensure_not_canceled(task_id)
                self.store.update_task(task_id, progress=50, stage="mp3_reused", message="Reusing saved MP3 from GCS")
                if task["engine"] != "google_speech":
                    gcs.download(storage_client, mp3_uri, mp3_path)
            elif task["source_type"] in MP3_SOURCE_TYPES:
                self._ensure_not_canceled(task_id)
                self.store.update_task(task_id, progress=15, stage="downloading_mp3", message="Downloading MP3 source")
                mp3_path = download_source(storage_client, task["source_type"], task["source_value"], temp)
                self._ensure_not_canceled(task_id)
                if task["source_type"] == "mp3_gcs":
                    mp3_uri = task["source_value"]
                    self.store.update_task(task_id, progress=50, stage="mp3_reused", mp3_uri=mp3_uri, message="Using existing GCS MP3")
                else:
                    mp3_uri = gcs.GcsUri.parse(task["audio_prefix"]).join(f"{stem}.mp3")
                    self.store.update_task(task_id, progress=35, stage="uploading_mp3", message="Saving MP3 to GCS")
                    gcs.upload(storage_client, mp3_path, mp3_uri, "audio/mpeg")
                    self.store.update_task(task_id, progress=50, stage="mp3_saved", mp3_uri=mp3_uri, message="MP3 saved to GCS")
            else:
                self._ensure_not_canceled(task_id)
                self.store.update_task(task_id, progress=15, stage="downloading_source", message="Downloading source")
                video_path = download_source(storage_client, task["source_type"], task["source_value"], temp)
                self._ensure_not_canceled(task_id)
                self.store.update_task(task_id, progress=35, stage="converting_mp3", message="Converting video to MP3")
                convert_to_mp3(video_path, mp3_path)
                self._ensure_not_canceled(task_id)

                mp3_uri = gcs.GcsUri.parse(task["audio_prefix"]).join(f"{stem}.mp3")
                gcs.upload(storage_client, mp3_path, mp3_uri, "audio/mpeg")
                self.store.update_task(task_id, progress=50, stage="mp3_saved", mp3_uri=mp3_uri, message="MP3 saved to GCS")

            if task["engine"] == "convert_mp3":
                self._ensure_not_canceled(task_id)
                self.store.update_task(
                    task_id,
                    status="done",
                    progress=100,
                    stage="mp3_conversion_done",
                    mp3_uri=mp3_uri,
                    message="MP3 conversion done",
                )
                self._write_task_log(storage_client, task_id)
                return

            chunk_minutes = int(task.get("chunk_minutes") or 0)
            transcript_result = self._transcribe_audio(
                storage_client=storage_client,
                task=task,
                task_id=task_id,
                stem=stem,
                mp3_path=mp3_path,
                mp3_uri=mp3_uri,
                chunk_minutes=chunk_minutes,
                temp=temp,
            )

            payload = {
                "task_id": task_id,
                "video_id": stem,
                "source_type": task["source_type"],
                "source_video_url": task["source_value"],
                "audio_url": mp3_uri,
                "engine": task["engine"],
                "language_code": task["language_code"],
                "chunk_minutes": chunk_minutes,
                "chunked": chunk_minutes > 0,
                **transcript_result,
            }
            transcript_uri = gcs.GcsUri.parse(task["transcript_prefix"]).join(f"{stem}.json")
            text_uri = gcs.GcsUri.parse(task["transcript_prefix"]).join(f"{stem}.txt")
            self._ensure_not_canceled(task_id)
            self.store.update_task(task_id, progress=90, stage="saving_transcript", message="Saving transcript")
            gcs.upload_text(storage_client, json.dumps(payload, indent=2), transcript_uri, "application/json")
            gcs.upload_text(storage_client, payload["transcript"], text_uri, "text/plain")
            self.store.update_task(
                task_id,
                status="done",
                progress=100,
                stage="transcript_saved",
                transcript_uri=transcript_uri,
                text_uri=text_uri,
                message="Done",
            )
            self._write_task_log(storage_client, task_id)

    def _import_transcript(self, storage_client: storage.Client, task: dict, task_id: str, stem: str, temp: Path) -> None:
        self._ensure_not_canceled(task_id)
        self.store.update_task(task_id, progress=20, stage="reading_transcript", message="Reading transcript source")
        transcript_text, source_reference = read_transcript_source(storage_client, task["source_type"], task["source_value"], temp)
        payload = {
            "task_id": task_id,
            "video_id": stem,
            "source_type": task["source_type"],
            "source_video_url": "",
            "source_transcript_url": source_reference,
            "audio_url": task.get("mp3_uri") or "",
            "engine": "transcript_import",
            "language_code": task.get("language_code") or "",
            "chunk_minutes": 0,
            "chunked": False,
            "transcript": transcript_text,
            "segments": [],
        }
        transcript_uri = gcs.GcsUri.parse(task["transcript_prefix"]).join(f"{stem}.json")
        text_uri = gcs.GcsUri.parse(task["transcript_prefix"]).join(f"{stem}.txt")
        self._ensure_not_canceled(task_id)
        self.store.update_task(task_id, progress=75, stage="saving_imported_transcript", message="Saving imported transcript")
        gcs.upload_text(storage_client, json.dumps(payload, indent=2), transcript_uri, "application/json")
        gcs.upload_text(storage_client, transcript_text, text_uri, "text/plain")
        self.store.update_task(
            task_id,
            status="done",
            progress=100,
            stage="transcript_imported",
            transcript_uri=transcript_uri,
            text_uri=text_uri,
            message="Imported transcript saved",
        )
        self._write_task_log(storage_client, task_id)

    def _transcribe_audio(
        self,
        storage_client: storage.Client,
        task: dict,
        task_id: str,
        stem: str,
        mp3_path: Path,
        mp3_uri: str,
        chunk_minutes: int,
        temp: Path,
    ) -> dict:
        if chunk_minutes <= 0:
            if task["engine"] == "google_speech":
                self._ensure_not_canceled(task_id)
                self.store.update_task(task_id, progress=60, stage="google_speech_started", message="Calling Google Speech-to-Text")
                result = transcribe_with_google(mp3_uri, task["language_code"])
                self._ensure_not_canceled(task_id)
                self.store.update_task(task_id, progress=85, stage="google_speech_finished", message="Google Speech-to-Text finished")
                return result
            self._ensure_not_canceled(task_id)
            self.store.update_task(task_id, progress=60, stage="whisper_started", message="Whisper starting")
            result = transcribe_with_whisper(mp3_path, task["engine"], task["language_code"])
            self._ensure_not_canceled(task_id)
            self.store.update_task(task_id, progress=85, stage="whisper_finished", message="Whisper finished")
            return result

        if not mp3_path.exists():
            self._ensure_not_canceled(task_id)
            gcs.download(storage_client, mp3_uri, mp3_path)

        self._ensure_not_canceled(task_id)
        self.store.update_task(task_id, progress=55, stage="splitting_chunks", message=f"Splitting MP3 into {chunk_minutes}-minute chunks")
        chunks = split_audio(mp3_path, temp / "chunks", chunk_minutes)
        if not chunks:
            raise RuntimeError("No audio chunks were created.")

        results = []
        total = len(chunks)
        for index, chunk_path in enumerate(chunks, start=1):
            self._ensure_not_canceled(task_id)
            offset_seconds = (index - 1) * chunk_minutes * 60
            chunk_uri = gcs.GcsUri.parse(task["audio_prefix"]).join("chunks", stem, chunk_path.name)
            progress = 55 + int((index - 1) / total * 30)
            stage = "google_speech_running" if task["engine"] == "google_speech" else "whisper_running"
            self.store.update_task(
                task_id,
                progress=progress,
                stage=stage,
                message=f"Transcribing chunk {index}/{total}",
            )
            gcs.upload(storage_client, chunk_path, chunk_uri, "audio/mpeg")
            self.store.update_task(
                task_id,
                progress=progress,
                stage="calling_google_speech" if task["engine"] == "google_speech" else "calling_whisper",
                message=f"Calling engine for chunk {index}/{total}",
            )
            if task["engine"] == "google_speech":
                chunk_result = transcribe_with_google(chunk_uri, task["language_code"])
            else:
                chunk_result = transcribe_with_whisper(chunk_path, task["engine"], task["language_code"])
            self._ensure_not_canceled(task_id)
            results.append(offset_transcript_result(chunk_result, offset_seconds))

        self.store.update_task(task_id, progress=88, stage="chunks_finished", message=f"Finished {total} chunk(s)")
        return combine_transcript_results(results)

    def _write_task_log(self, storage_client: storage.Client, task_id: str) -> None:
        task = self.store.get_task(task_id)
        if not task:
            return
        base_prefix = task.get("transcript_prefix") or task.get("audio_prefix")
        if not base_prefix or not str(base_prefix).startswith("gs://"):
            return
        log_uri = gcs.GcsUri.parse(base_prefix).join("_task-logs", f"{task_id}.json")
        gcs.upload_text(storage_client, json.dumps(task_log_payload(task), indent=2), log_uri, "application/json")
        self.store.update_task(task_id, task_log_uri=log_uri)

    def _ensure_not_canceled(self, task_id: str) -> None:
        if self.store.is_canceled(task_id):
            raise TaskCanceled("Task canceled by user")

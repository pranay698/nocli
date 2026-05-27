from __future__ import annotations

import json
import os
import re
import zipfile
from pathlib import Path
from typing import Annotated
from xml.etree import ElementTree

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from google.cloud import storage
from pydantic import BaseModel

from . import gcs
from .course_ai import build_demo_landing_prompt, generate_course_data_with_vertex, generate_landing_page_with_vertex
from .job_store import JobStore, tasks_to_csv
from .models import ENGINES, SOURCE_TYPES, TaskRequest
from .sources import TRANSCRIPT_SOURCE_TYPES, expand_folder_source
from .worker import QueueWorker


APP_DIR = Path(__file__).parent
STATIC_DIR = APP_DIR / "static"
DATA_DIR = Path(os.getenv("COURSE_ENGINE_DATA_DIR", "/tmp/course-engine"))
DB_PATH = os.getenv("COURSE_ENGINE_DB", str(DATA_DIR / "tasks.sqlite3"))
RAW_UPLOAD_PREFIX = os.getenv("RAW_UPLOAD_PREFIX", "")
DEFAULT_AUDIO_PREFIX = os.getenv("DEFAULT_AUDIO_PREFIX", "")
DEFAULT_TRANSCRIPT_PREFIX = os.getenv("DEFAULT_TRANSCRIPT_PREFIX", "")
SERVICE_ACCOUNT_EMAIL = os.getenv("SERVICE_ACCOUNT_EMAIL", "")
WORKER_COUNT = int(os.getenv("COURSE_ENGINE_WORKERS", "1"))

app = FastAPI(title="Transcription Course Engine")
store = JobStore(DB_PATH)
worker = QueueWorker(store, worker_count=WORKER_COUNT)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class CreateTasksPayload(BaseModel):
    source_type: str
    source_values: list[str]
    engine: str
    transcript_prefix: str
    audio_prefix: str
    language_code: str = "en-IN"
    save_mp3: bool = True
    chunk_minutes: int = 0


class DownloadPayload(BaseModel):
    source_type: str
    source_values: list[str]
    destination_prefix: str


class AccountPayload(BaseModel):
    name: str
    provider: str
    auth_method: str
    status: str = "pending"
    notes: str = ""


class CourseDataPayload(BaseModel):
    force: bool = False


@app.on_event("startup")
def startup() -> None:
    worker.start()


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/config")
def config() -> dict:
    return {
        "engines": ENGINES,
        "source_types": SOURCE_TYPES,
        "defaults": {
            "raw_upload_prefix": RAW_UPLOAD_PREFIX,
            "audio_prefix": DEFAULT_AUDIO_PREFIX,
            "transcript_prefix": DEFAULT_TRANSCRIPT_PREFIX,
            "service_account_email": SERVICE_ACCOUNT_EMAIL,
        },
    }


@app.post("/api/tasks")
def create_tasks(payload: CreateTasksPayload) -> dict:
    if payload.engine not in ENGINES:
        raise HTTPException(status_code=400, detail="Unsupported engine")
    if not payload.transcript_prefix.startswith("gs://") or not payload.audio_prefix.startswith("gs://"):
        raise HTTPException(status_code=400, detail="Save locations must be GCS prefixes.")

    task_ids = []
    for source_value in payload.source_values:
        if not source_value.strip():
            continue
        storage_client = storage.Client() if payload.source_type == "gcs_folder" else None
        try:
            expanded = expand_folder_source(storage_client, payload.source_type, source_value.strip())
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        for item in expanded:
            source_type, value = item[0], item[1]
            source_folder_uri = item[2] if len(item) > 2 else source_value.strip() if payload.source_type.endswith("_folder") else None
            task_engine = "transcript_import" if source_type in TRANSCRIPT_SOURCE_TYPES else payload.engine
            task_ids.append(
                store.create_task(
                    TaskRequest(
                        source_type=source_type,
                        source_value=value,
                        engine=task_engine,
                        transcript_prefix=payload.transcript_prefix,
                        audio_prefix=payload.audio_prefix,
                        language_code=payload.language_code,
                        save_mp3=payload.save_mp3,
                        chunk_minutes=payload.chunk_minutes,
                    ),
                    source_folder_uri=source_folder_uri,
                )
            )
    return {"task_ids": task_ids}


@app.post("/api/downloads")
def create_downloads(payload: DownloadPayload) -> dict:
    if not payload.destination_prefix.startswith("gs://"):
        raise HTTPException(status_code=400, detail="Destination must be a GCS prefix.")

    task_ids = []
    for source_value in payload.source_values:
        if not source_value.strip():
            continue
        storage_client = storage.Client() if payload.source_type == "gcs_folder" else None
        try:
            expanded = expand_folder_source(storage_client, payload.source_type, source_value.strip())
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        for item in expanded:
            source_type, value = item[0], item[1]
            source_folder_uri = item[2] if len(item) > 2 else source_value.strip() if payload.source_type.endswith("_folder") else None
            task_ids.append(
                store.create_task(
                    TaskRequest(
                        source_type=source_type,
                        source_value=value,
                        engine="download_only",
                        transcript_prefix=payload.destination_prefix,
                        audio_prefix=payload.destination_prefix,
                        language_code="",
                        save_mp3=False,
                    ),
                    source_folder_uri=source_folder_uri,
                )
            )
    return {"task_ids": task_ids}


@app.post("/api/uploads")
async def upload_tasks(
    files: Annotated[list[UploadFile], File()],
    engine: Annotated[str, Form()],
    transcript_prefix: Annotated[str, Form()],
    audio_prefix: Annotated[str, Form()],
    source_type: Annotated[str, Form()] = "upload",
    language_code: Annotated[str, Form()] = "en-IN",
    save_mp3: Annotated[bool, Form()] = True,
    chunk_minutes: Annotated[int, Form()] = 0,
) -> dict:
    if source_type not in {"upload", "mp3_upload", "transcript_upload"}:
        raise HTTPException(status_code=400, detail="Unsupported upload source type.")
    if source_type == "upload" and not RAW_UPLOAD_PREFIX:
        raise HTTPException(status_code=400, detail="Set RAW_UPLOAD_PREFIX to enable video uploads.")
    if engine not in ENGINES:
        raise HTTPException(status_code=400, detail="Unsupported engine")
    if not transcript_prefix.startswith("gs://") or not audio_prefix.startswith("gs://"):
        raise HTTPException(status_code=400, detail="Save locations must be GCS prefixes.")

    storage_client = storage.Client()
    task_ids = []
    if source_type == "mp3_upload":
        upload_prefix = gcs.GcsUri.parse(audio_prefix).join("imports")
        queued_source_type = "mp3_upload"
        content_type = "audio/mpeg"
        task_engine = engine
    elif source_type == "transcript_upload":
        upload_prefix = gcs.GcsUri.parse(transcript_prefix).join("imports")
        queued_source_type = "transcript_upload"
        content_type = "text/plain"
        task_engine = "transcript_import"
    else:
        upload_prefix = RAW_UPLOAD_PREFIX
        queued_source_type = "upload"
        content_type = None
        task_engine = engine
    upload_prefix_uri = gcs.GcsUri.parse(upload_prefix)
    for upload in files:
        safe_name = Path(upload.filename or "uploaded-file").name
        target_uri = upload_prefix_uri.join(safe_name)
        parsed = gcs.GcsUri.parse(target_uri)
        blob = storage_client.bucket(parsed.bucket).blob(parsed.blob)
        blob.upload_from_file(upload.file, content_type=upload.content_type or content_type)
        task_ids.append(
            store.create_task(
                TaskRequest(
                    source_type=queued_source_type,
                    source_value=target_uri,
                    engine=task_engine,
                    transcript_prefix=transcript_prefix,
                    audio_prefix=audio_prefix,
                    language_code=language_code,
                    save_mp3=save_mp3,
                    chunk_minutes=chunk_minutes,
                )
            )
        )
    return {"task_ids": task_ids}


@app.get("/api/tasks")
def list_tasks() -> dict:
    return {"counts": store.counts(), "tasks": store.list_tasks()}


@app.get("/api/accounts")
def list_accounts() -> dict:
    return {"accounts": store.list_accounts()}


@app.post("/api/accounts")
def create_account(payload: AccountPayload) -> dict:
    account_id = store.create_account(
        name=payload.name,
        provider=payload.provider,
        auth_method=payload.auth_method,
        status=payload.status,
        notes=payload.notes,
    )
    return {"account_id": account_id}


@app.delete("/api/accounts/{account_id}")
def delete_account(account_id: str) -> dict:
    store.delete_account(account_id)
    return {"ok": True}


@app.get("/api/tasks.csv")
def export_tasks_csv() -> StreamingResponse:
    csv_text = tasks_to_csv(store.list_tasks(limit=5000))
    return StreamingResponse(
        iter([csv_text]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=transcription-task-log.csv"},
    )


@app.get("/api/tasks/{task_id}")
def get_task(task_id: str) -> dict:
    task = store.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@app.get("/api/tasks/{task_id}/transcript")
def view_transcript(task_id: str) -> Response:
    task = store.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    transcript_uri = task.get("text_uri") or task.get("transcript_uri")
    if not transcript_uri:
        raise HTTPException(status_code=404, detail="Transcript is not available yet")
    if not str(transcript_uri).startswith("gs://"):
        return Response(str(transcript_uri), media_type="text/plain")
    parsed = gcs.GcsUri.parse(transcript_uri)
    blob = storage.Client().bucket(parsed.bucket).blob(parsed.blob)
    if not blob.exists():
        raise HTTPException(status_code=404, detail="Transcript file was not found in GCS")
    media_type = "application/json" if str(transcript_uri).endswith(".json") else "text/plain"
    return Response(blob.download_as_bytes(), media_type=media_type)


@app.get("/api/tasks/{task_id}/audio")
def listen_audio(task_id: str) -> StreamingResponse:
    task = store.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    mp3_uri = task.get("mp3_uri")
    if not mp3_uri:
        raise HTTPException(status_code=404, detail="MP3 is not available yet")
    parsed = gcs.GcsUri.parse(mp3_uri)
    blob = storage.Client().bucket(parsed.bucket).blob(parsed.blob)
    if not blob.exists():
        raise HTTPException(status_code=404, detail="MP3 file was not found in GCS")
    return StreamingResponse(blob.open("rb"), media_type="audio/mpeg")


@app.post("/api/tasks/{task_id}/course-data")
def generate_course_data(task_id: str, payload: CourseDataPayload | None = None) -> dict:
    task = store.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.get("course_data_uri") and not (payload and payload.force):
        return {
            "course_data_uri": task.get("course_data_uri"),
            "course_title": task.get("course_title"),
            "course_description": task.get("course_description"),
        }
    transcript_uri = task.get("text_uri") or task.get("transcript_uri")
    if not transcript_uri:
        raise HTTPException(status_code=400, detail="Transcript must exist before generating course data.")

    store.update_task(task_id, stage="generating_course_data", message="Generating course data with Vertex AI Gemini")
    transcript = _download_text(transcript_uri)
    if transcript_uri == task.get("transcript_uri"):
        try:
            transcript_payload = json.loads(transcript)
            transcript = transcript_payload.get("transcript", transcript)
        except json.JSONDecodeError:
            pass
    try:
        course_data = generate_course_data_with_vertex(
            transcript,
            video_url=task.get("source_value") or task.get("saved_source_uri") or "",
            mp3_url=task.get("mp3_uri") or "",
            transcript_url=transcript_uri,
        )
    except Exception as exc:
        store.update_task(task_id, stage="course_data_failed", error=str(exc), message=f"Course data failed: {exc}")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    refined_transcript = course_data.pop("refined_transcript", "")
    course_data.setdefault("source_reference", {})
    course_data["source_reference"].update(
        {
            "video_url": task.get("source_value") or task.get("saved_source_uri") or "",
            "mp3_url": task.get("mp3_uri") or "",
            "transcript_url": transcript_uri,
        }
    )
    title = course_data.get("core_identity", {}).get("primary_title") or course_data.get("course_title", "")
    description = course_data.get("hook", {}).get("short_description") or course_data.get("course_description", "")
    metadata_prefix = gcs.GcsUri.parse(task["transcript_prefix"]).join("metadata")
    course_uri = gcs.GcsUri.parse(metadata_prefix).join(f"{task_id}_meta.json")
    refined_uri = gcs.GcsUri.parse(metadata_prefix).join(f"{task_id}_refined.txt")
    if refined_transcript:
        gcs.upload_text(storage.Client(), refined_transcript, refined_uri, "text/plain")
    gcs.upload_text(storage.Client(), json.dumps(course_data, indent=2), course_uri, "application/json")
    store.update_task(
        task_id,
        course_title=title,
        course_description=description,
        course_data_uri=course_uri,
        refined_transcript_uri=refined_uri if refined_transcript else None,
        stage="course_data_saved",
        message="Refined transcript and metadata saved",
    )
    return {
        "course_data_uri": course_uri,
        "refined_transcript_uri": refined_uri if refined_transcript else None,
        "course_title": title,
        "course_description": description,
    }


@app.get("/api/tasks/{task_id}/course-data")
def view_course_data(task_id: str) -> Response:
    task = store.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    course_data_uri = task.get("course_data_uri")
    if not course_data_uri:
        raise HTTPException(status_code=404, detail="Course data is not available yet")
    return Response(_download_bytes(course_data_uri), media_type="application/json")


@app.get("/api/tasks/{task_id}/refined-transcript")
def view_refined_transcript(task_id: str) -> Response:
    task = store.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    refined_transcript_uri = task.get("refined_transcript_uri")
    if not refined_transcript_uri:
        raise HTTPException(status_code=404, detail="Refined transcript is not available yet")
    return Response(_download_bytes(refined_transcript_uri), media_type="text/plain")


@app.post("/api/tasks/{task_id}/landing-page")
def generate_landing_page(
    task_id: str,
    force: Annotated[bool, Form()] = False,
    use_demo_prompt: Annotated[bool, Form()] = False,
    landing_vibe: Annotated[str, Form()] = "luxury",
    prompt_file: Annotated[UploadFile | None, File()] = None,
) -> dict:
    task = store.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.get("landing_page_uri") and not force:
        return {"landing_page_uri": task.get("landing_page_uri")}
    course_data_uri = task.get("course_data_uri")
    if not course_data_uri:
        raise HTTPException(status_code=400, detail="Generate course metadata before creating a landing page.")
    custom_prompt = None
    prompt_uri = None
    prompt_name = None
    uploaded_prompt = None
    if prompt_file and prompt_file.filename:
        prompt_bytes = prompt_file.file.read()
        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(prompt_file.filename).name).strip("-") or "landing-prompt.txt"
        uploaded_prompt = _extract_prompt_text(prompt_file.filename, prompt_bytes)
        custom_prompt = uploaded_prompt
        prompt_name = safe_name
    if use_demo_prompt:
        custom_prompt = build_demo_landing_prompt(landing_vibe, uploaded_prompt=uploaded_prompt)
        prompt_name = f"demo-prompt-{landing_vibe}.txt"
    if custom_prompt:
        prompt_uri = gcs.GcsUri.parse(task["transcript_prefix"]).join("metadata", "prompts", f"{task_id}_{prompt_name or 'landing-prompt.txt'}")
        gcs.upload_text(storage.Client(), custom_prompt, prompt_uri, "text/plain")
    try:
        metadata = json.loads(_download_text(course_data_uri))
        store.update_task(task_id, stage="generating_landing_page", message="Generating Acadma landing page with Vertex AI Gemini")
        landing_component = generate_landing_page_with_vertex(metadata, custom_prompt=custom_prompt)
    except Exception as exc:
        store.update_task(task_id, stage="landing_page_failed", error=str(exc), message=f"Landing page failed: {exc}")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    landing_uri = gcs.GcsUri.parse(task["transcript_prefix"]).join("landing-pages", f"{task_id}_landing.tsx")
    gcs.upload_text(storage.Client(), landing_component, landing_uri, "text/plain")
    store.update_task(
        task_id,
        landing_prompt_uri=prompt_uri or task.get("landing_prompt_uri"),
        landing_page_uri=landing_uri,
        stage="landing_page_saved",
        message="Landing page component saved",
    )
    return {"landing_page_uri": landing_uri}


@app.get("/api/tasks/{task_id}/landing-page")
def view_landing_page(task_id: str) -> Response:
    task = store.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    landing_page_uri = task.get("landing_page_uri")
    if not landing_page_uri:
        raise HTTPException(status_code=404, detail="Landing page is not available yet")
    return Response(_download_bytes(landing_page_uri), media_type="text/plain")


@app.post("/api/tasks/{task_id}/cancel")
def cancel_task(task_id: str) -> dict:
    try:
        store.cancel(task_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Task not found") from None
    return {"ok": True}


@app.post("/api/tasks/{task_id}/retry")
def retry_task(task_id: str) -> dict:
    try:
        store.retry(task_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Task not found") from None
    return {"ok": True}


def _download_text(uri: str) -> str:
    return _download_bytes(uri).decode("utf-8", errors="replace")


def _download_bytes(uri: str) -> bytes:
    if not str(uri).startswith("gs://"):
        return str(uri).encode("utf-8")
    parsed = gcs.GcsUri.parse(uri)
    blob = storage.Client().bucket(parsed.bucket).blob(parsed.blob)
    if not blob.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {uri}")
    return blob.download_as_bytes()


def _extract_prompt_text(filename: str, content: bytes) -> str:
    if filename.lower().endswith(".docx"):
        return _extract_docx_text(content)
    return content.decode("utf-8", errors="replace")


def _extract_docx_text(content: bytes) -> str:
    from io import BytesIO

    with zipfile.ZipFile(BytesIO(content)) as docx:
        xml = docx.read("word/document.xml")
    root = ElementTree.fromstring(xml)
    namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    paragraphs = []
    for paragraph in root.findall(".//w:p", namespace):
        parts = []
        for node in paragraph.iter():
            tag = node.tag.rsplit("}", 1)[-1]
            if tag == "t" and node.text:
                parts.append(node.text)
            elif tag == "tab":
                parts.append("\t")
            elif tag == "br":
                parts.append("\n")
        text = "".join(parts).strip()
        if text:
            paragraphs.append(text)
    return "\n\n".join(paragraphs)

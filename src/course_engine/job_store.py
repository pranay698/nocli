from __future__ import annotations

import json
import csv
import io
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import TaskRequest


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                create table if not exists tasks (
                    id text primary key,
                    created_at text not null,
                    updated_at text not null,
                    status text not null,
                    progress integer not null,
                    source_type text not null,
                    source_value text not null,
                    engine text not null,
                    transcript_prefix text not null,
                    audio_prefix text not null,
                    language_code text not null,
                    save_mp3 integer not null,
                    message text not null default '',
                    transcript_uri text,
                    text_uri text,
                    mp3_uri text,
                    saved_source_uri text,
                    source_folder_uri text,
                    task_log_uri text,
                    course_title text,
                    course_description text,
                    course_data_uri text,
                    refined_transcript_uri text,
                    landing_prompt_uri text,
                    landing_page_uri text,
                    started_at text,
                    completed_at text,
                    chunk_minutes integer not null default 0,
                    stage text not null default '',
                    error text
                )
                """
            )
            columns = {row["name"] for row in conn.execute("pragma table_info(tasks)").fetchall()}
            if "saved_source_uri" not in columns:
                conn.execute("alter table tasks add column saved_source_uri text")
            if "source_folder_uri" not in columns:
                conn.execute("alter table tasks add column source_folder_uri text")
            if "task_log_uri" not in columns:
                conn.execute("alter table tasks add column task_log_uri text")
            if "course_title" not in columns:
                conn.execute("alter table tasks add column course_title text")
            if "course_description" not in columns:
                conn.execute("alter table tasks add column course_description text")
            if "course_data_uri" not in columns:
                conn.execute("alter table tasks add column course_data_uri text")
            if "refined_transcript_uri" not in columns:
                conn.execute("alter table tasks add column refined_transcript_uri text")
            if "landing_prompt_uri" not in columns:
                conn.execute("alter table tasks add column landing_prompt_uri text")
            if "landing_page_uri" not in columns:
                conn.execute("alter table tasks add column landing_page_uri text")
            if "started_at" not in columns:
                conn.execute("alter table tasks add column started_at text")
            if "completed_at" not in columns:
                conn.execute("alter table tasks add column completed_at text")
            if "chunk_minutes" not in columns:
                conn.execute("alter table tasks add column chunk_minutes integer not null default 0")
            if "stage" not in columns:
                conn.execute("alter table tasks add column stage text not null default ''")
            conn.execute(
                """
                create table if not exists task_events (
                    id integer primary key autoincrement,
                    task_id text not null,
                    created_at text not null,
                    message text not null
                )
                """
            )
            conn.execute(
                """
                create table if not exists accounts (
                    id text primary key,
                    created_at text not null,
                    updated_at text not null,
                    name text not null,
                    provider text not null,
                    auth_method text not null,
                    status text not null,
                    notes text not null default ''
                )
                """
            )

    def create_task(self, request: TaskRequest, source_folder_uri: str | None = None) -> str:
        task_id = uuid.uuid4().hex
        now = utc_now()
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                insert into tasks (
                    id, created_at, updated_at, status, progress, source_type, source_value,
                    engine, transcript_prefix, audio_prefix, language_code, save_mp3, message, source_folder_uri,
                    chunk_minutes, stage
                ) values (?, ?, ?, 'queued', 0, ?, ?, ?, ?, ?, ?, ?, 'Waiting', ?, ?, 'queued')
                """,
                (
                    task_id,
                    now,
                    now,
                    request.source_type,
                    request.source_value,
                    request.engine,
                    request.transcript_prefix,
                    request.audio_prefix,
                    request.language_code,
                    int(request.save_mp3),
                    source_folder_uri,
                    request.chunk_minutes,
                ),
            )
            conn.execute(
                "insert into task_events (task_id, created_at, message) values (?, ?, ?)",
                (task_id, now, "Task queued"),
            )
        return task_id

    def next_queued(self) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "select * from tasks where status = 'queued' order by created_at limit 1"
            ).fetchone()
            if row is None:
                return None
            now = utc_now()
            conn.execute(
                "update tasks set status = 'running', progress = 5, updated_at = ?, started_at = ?, message = ? where id = ?",
                (now, now, "Starting", row["id"]),
            )
            conn.execute(
                "insert into task_events (task_id, created_at, message) values (?, ?, ?)",
                (row["id"], now, "Task started"),
            )
            updated = conn.execute("select * from tasks where id = ?", (row["id"],)).fetchone()
            return dict(updated)

    def update_task(self, task_id: str, **fields: Any) -> None:
        if not fields:
            return
        fields["updated_at"] = utc_now()
        if fields.get("status") in {"done", "failed", "canceled"} and "completed_at" not in fields:
            fields["completed_at"] = fields["updated_at"]
        columns = ", ".join(f"{key} = ?" for key in fields)
        values = list(fields.values())
        values.append(task_id)
        with self._lock, self._connect() as conn:
            conn.execute(f"update tasks set {columns} where id = ?", values)
            if "message" in fields:
                conn.execute(
                    "insert into task_events (task_id, created_at, message) values (?, ?, ?)",
                    (task_id, fields["updated_at"], str(fields["message"])),
                )

    def list_tasks(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "select * from tasks order by created_at desc limit ?", (limit,)
            ).fetchall()
            return [dict(row) for row in rows]

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("select * from tasks where id = ?", (task_id,)).fetchone()
            if row is None:
                return None
            task = dict(row)
            events = conn.execute(
                "select created_at, message from task_events where task_id = ? order by id",
                (task_id,),
            ).fetchall()
            task["events"] = [dict(event) for event in events]
            return task

    def counts(self) -> dict[str, int]:
        with self._connect() as conn:
            rows = conn.execute("select status, count(*) count from tasks group by status").fetchall()
            return {row["status"]: row["count"] for row in rows}

    def is_canceled(self, task_id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute("select status from tasks where id = ?", (task_id,)).fetchone()
            return bool(row and row["status"] == "canceled")

    def cancel(self, task_id: str) -> None:
        with self._lock, self._connect() as conn:
            row = conn.execute("select status from tasks where id = ?", (task_id,)).fetchone()
            if row is None:
                raise KeyError(task_id)
            if row["status"] in {"done", "failed", "canceled"}:
                return
            now = utc_now()
            conn.execute(
                """
                update tasks set status = 'canceled', progress = 100, updated_at = ?,
                completed_at = ?, stage = 'canceled', message = 'Canceled by user' where id = ?
                """,
                (now, now, task_id),
            )
            conn.execute(
                "insert into task_events (task_id, created_at, message) values (?, ?, ?)",
                (task_id, now, "Canceled by user"),
            )

    def retry(self, task_id: str) -> None:
        with self._lock, self._connect() as conn:
            row = conn.execute("select * from tasks where id = ?", (task_id,)).fetchone()
            if row is None:
                raise KeyError(task_id)
            now = utc_now()
            conn.execute(
                """
                update tasks set status = 'queued', progress = 0, updated_at = ?, error = null,
                started_at = null, completed_at = null, message = 'Queued for retry' where id = ?
                """,
                (now, task_id),
            )
            conn.execute(
                "insert into task_events (task_id, created_at, message) values (?, ?, ?)",
                (task_id, now, "Queued for retry"),
            )

    def export_json(self) -> str:
        return json.dumps(self.list_tasks(limit=1000), indent=2)

    def create_account(self, name: str, provider: str, auth_method: str, status: str, notes: str = "") -> str:
        account_id = uuid.uuid4().hex
        now = utc_now()
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                insert into accounts (id, created_at, updated_at, name, provider, auth_method, status, notes)
                values (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (account_id, now, now, name, provider, auth_method, status, notes),
            )
        return account_id

    def list_accounts(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("select * from accounts order by created_at desc").fetchall()
            return [dict(row) for row in rows]

    def delete_account(self, account_id: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("delete from accounts where id = ?", (account_id,))


def task_log_payload(task: dict[str, Any]) -> dict[str, Any]:
    return {
        "task_id": task.get("id"),
        "status": task.get("status"),
        "progress": task.get("progress"),
        "source_type": task.get("source_type"),
        "source_value": task.get("source_value"),
        "source_folder_uri": task.get("source_folder_uri"),
        "engine": task.get("engine"),
        "saved_source_uri": task.get("saved_source_uri"),
        "mp3_uri": task.get("mp3_uri"),
        "transcript_uri": task.get("transcript_uri"),
        "text_uri": task.get("text_uri"),
        "task_log_uri": task.get("task_log_uri"),
        "course_title": task.get("course_title"),
        "course_description": task.get("course_description"),
        "course_data_uri": task.get("course_data_uri"),
        "refined_transcript_uri": task.get("refined_transcript_uri"),
        "landing_prompt_uri": task.get("landing_prompt_uri"),
        "landing_page_uri": task.get("landing_page_uri"),
        "chunk_minutes": task.get("chunk_minutes"),
        "stage": task.get("stage"),
        "error": task.get("error"),
        "message": task.get("message"),
        "created_at": task.get("created_at"),
        "started_at": task.get("started_at"),
        "completed_at": task.get("completed_at"),
        "updated_at": task.get("updated_at"),
        "events": task.get("events", []),
    }


def tasks_to_csv(tasks: list[dict[str, Any]]) -> str:
    output = io.StringIO()
    fieldnames = [
        "id",
        "status",
        "progress",
        "source_type",
        "source_value",
        "source_folder_uri",
        "engine",
        "saved_source_uri",
        "mp3_uri",
        "transcript_uri",
        "text_uri",
        "task_log_uri",
        "course_title",
        "course_description",
        "course_data_uri",
        "refined_transcript_uri",
        "landing_prompt_uri",
        "landing_page_uri",
        "chunk_minutes",
        "stage",
        "error",
        "message",
        "created_at",
        "started_at",
        "completed_at",
        "updated_at",
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for task in tasks:
        writer.writerow({field: task.get(field, "") for field in fieldnames})
    return output.getvalue()

from __future__ import annotations

import argparse
import uvicorn

from .course_sheet import CourseSheetConfig, build_course_sheet
from .job_store import JobStore, tasks_to_csv
from .models import TaskRequest
from .sources import expand_folder_source
from .transcriber import TranscriptionConfig, run_transcription


def main() -> None:
    parser = argparse.ArgumentParser(prog="course_engine")
    subparsers = parser.add_subparsers(dest="command", required=True)

    transcribe = subparsers.add_parser("transcribe", help="Transcribe videos from a GCS prefix")
    transcribe.add_argument("--project-id", required=True)
    transcribe.add_argument("--input-prefix", required=True)
    transcribe.add_argument("--audio-prefix", required=True)
    transcribe.add_argument("--transcript-prefix", required=True)
    transcribe.add_argument("--language-code", default="en-IN")
    transcribe.add_argument("--limit", type=int)
    transcribe.add_argument("--include-existing", action="store_true")
    transcribe.add_argument("--dry-run", action="store_true")

    sheet = subparsers.add_parser("build-course-sheet", help="Create a course CSV from transcript JSON files")
    sheet.add_argument("--transcript-prefix", required=True)
    sheet.add_argument("--output-uri", required=True)
    sheet.add_argument("--max-words-per-lesson", type=int, default=900)

    serve = subparsers.add_parser("serve", help="Run the transcription control-center web app")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8080)

    queue_folder = subparsers.add_parser("queue-gcs-folder", help="Queue all videos in a GCS folder recursively")
    queue_folder.add_argument("--folder-uri", required=True)
    queue_folder.add_argument("--audio-prefix", required=True)
    queue_folder.add_argument("--transcript-prefix", required=True)
    queue_folder.add_argument("--engine", default="google_speech")
    queue_folder.add_argument("--language-code", default="en-IN")
    queue_folder.add_argument("--db", default="/data/course-engine/tasks.sqlite3")
    queue_folder.add_argument("--limit", type=int)

    export_log = subparsers.add_parser("export-task-log", help="Export queued task history as CSV")
    export_log.add_argument("--db", default="/data/course-engine/tasks.sqlite3")
    export_log.add_argument("--output", required=True)

    args = parser.parse_args()
    if args.command == "transcribe":
        run_transcription(
            TranscriptionConfig(
                project_id=args.project_id,
                input_prefix=args.input_prefix,
                audio_prefix=args.audio_prefix,
                transcript_prefix=args.transcript_prefix,
                language_code=args.language_code,
                limit=args.limit,
                skip_existing=not args.include_existing,
                dry_run=args.dry_run,
            )
        )
    elif args.command == "build-course-sheet":
        build_course_sheet(
            CourseSheetConfig(
                transcript_prefix=args.transcript_prefix,
                output_uri=args.output_uri,
                max_words_per_lesson=args.max_words_per_lesson,
            )
        )
    elif args.command == "serve":
        uvicorn.run("course_engine.app:app", host=args.host, port=args.port)
    elif args.command == "queue-gcs-folder":
        from google.cloud import storage

        store = JobStore(args.db)
        client = storage.Client()
        expanded = expand_folder_source(client, "gcs_folder", args.folder_uri)
        if args.limit is not None:
            expanded = expanded[: args.limit]
        task_ids = []
        for item in expanded:
            source_type, value = item[0], item[1]
            task_ids.append(
                store.create_task(
                    TaskRequest(
                        source_type=source_type,
                        source_value=value,
                        engine=args.engine,
                        transcript_prefix=args.transcript_prefix,
                        audio_prefix=args.audio_prefix,
                        language_code=args.language_code,
                        save_mp3=True,
                    ),
                    source_folder_uri=item[2] if len(item) > 2 else args.folder_uri,
                )
            )
        print(f"Queued {len(task_ids)} task(s).")
    elif args.command == "export-task-log":
        store = JobStore(args.db)
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(tasks_to_csv(store.list_tasks(limit=100000)))
        print(f"Wrote {args.output}")

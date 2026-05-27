from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass

from . import gcs


@dataclass(frozen=True)
class CourseSheetConfig:
    transcript_prefix: str
    output_uri: str
    max_words_per_lesson: int = 900


CSV_FIELDS = [
    "course_name",
    "module_name",
    "lesson_title",
    "lesson_summary",
    "lesson_text",
    "source_video_url",
    "transcript_url",
    "start_time",
    "end_time",
    "suggested_quiz_questions",
]


def build_course_sheet(config: CourseSheetConfig) -> None:
    from google.cloud import storage

    client = storage.Client()
    rows = []
    transcript_uris = sorted(gcs.list_json_uris(client, config.transcript_prefix))
    for transcript_uri in transcript_uris:
        payload = json.loads(gcs.download_text(client, transcript_uri))
        rows.extend(transcript_to_rows(payload, transcript_uri, config.max_words_per_lesson))

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=CSV_FIELDS)
    writer.writeheader()
    writer.writerows(rows)
    gcs.upload_text(client, output.getvalue(), config.output_uri, "text/csv")
    print(f"Wrote {len(rows)} lesson row(s) to {config.output_uri}")


def transcript_to_rows(payload: dict, transcript_uri: str, max_words_per_lesson: int) -> list[dict]:
    segments = payload.get("segments") or []
    source_video_url = payload.get("source_video_url", "")
    video_id = payload.get("video_id", "Untitled Video")
    chunks = chunk_segments(segments, max_words_per_lesson)

    if not chunks and payload.get("transcript"):
        chunks = [
            {
                "start_time": "",
                "end_time": "",
                "text": payload["transcript"],
            }
        ]

    rows = []
    for index, chunk in enumerate(chunks, start=1):
        text = normalize_space(chunk["text"])
        rows.append(
            {
                "course_name": "",
                "module_name": humanize_title(video_id),
                "lesson_title": make_lesson_title(text, index),
                "lesson_summary": summarize(text),
                "lesson_text": text,
                "source_video_url": source_video_url,
                "transcript_url": transcript_uri,
                "start_time": chunk["start_time"],
                "end_time": chunk["end_time"],
                "suggested_quiz_questions": make_quiz_questions(text),
            }
        )
    return rows


def chunk_segments(segments: list[dict], max_words: int) -> list[dict]:
    chunks = []
    current_text = []
    current_words = 0
    start_time = ""
    end_time = ""

    for segment in segments:
        text = normalize_space(segment.get("text", ""))
        if not text:
            continue
        words = text.split()
        if current_text and current_words + len(words) > max_words:
            chunks.append({"start_time": start_time, "end_time": end_time, "text": " ".join(current_text)})
            current_text = []
            current_words = 0
            start_time = ""
            end_time = ""

        if not start_time:
            start_time = segment.get("start") or ""
        end_time = segment.get("end") or end_time
        current_text.append(text)
        current_words += len(words)

    if current_text:
        chunks.append({"start_time": start_time, "end_time": end_time, "text": " ".join(current_text)})
    return chunks


def humanize_title(value: str) -> str:
    value = re.sub(r"[_-]+", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value.title() if value else "Untitled Module"


def make_lesson_title(text: str, index: int) -> str:
    sentence = first_sentence(text)
    words = sentence.split()[:10]
    title = " ".join(words).strip(" ,.;:")
    return title or f"Lesson {index}"


def summarize(text: str) -> str:
    sentences = split_sentences(text)
    summary = " ".join(sentences[:2])
    return summary[:500]


def make_quiz_questions(text: str) -> str:
    title = make_lesson_title(text, 1).lower()
    return "\n".join(
        [
            f"What is the main idea of {title}?",
            "Which key steps or concepts were explained in this lesson?",
            "How would you apply this lesson in a real situation?",
        ]
    )


def first_sentence(text: str) -> str:
    sentences = split_sentences(text)
    return sentences[0] if sentences else text


def split_sentences(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+", normalize_space(text)) if part.strip()]


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()

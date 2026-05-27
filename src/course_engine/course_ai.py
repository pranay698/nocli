from __future__ import annotations

import json
import os
from typing import Any

import google.auth
import requests
from google.auth.transport.requests import Request


MASTER_COURSE_ARCHITECT_PROMPT = """Role: You are an expert Instructional Designer and Senior Content Strategist.
Task: Analyze the provided refined transcript and generate a comprehensive Course Marketing & Structure Kit.

Required output: return only valid JSON with this exact top-level shape:
{
  "core_identity": {
    "primary_title": "results-oriented course title",
    "alternative_title": "SEO-friendly alternative title",
    "category": "topic area",
    "tags": ["10 SEO-focused tags"]
  },
  "hook": {
    "short_description": "2-3 sentence description",
    "learning_objectives": ["Bloom's taxonomy objective 1", "objective 2", "objective 3"],
    "big_promise": "punchy one-line promise"
  },
  "video_metadata": {
    "estimated_duration": "MM:SS or HH:MM:SS",
    "youtube_chapters": [
      {"timestamp": "00:00", "title": "chapter title"}
    ]
  },
  "student_support": {
    "faq": [
      {"question": "question based strictly on transcript complexity", "answer": "answer grounded in transcript"}
    ],
    "target_audience": "level and role"
  },
  "source_reference": {
    "video_url": "",
    "mp3_url": "",
    "transcript_url": ""
  }
}

Constraints:
- Use only the provided transcript.
- Do not use phrases like "In this video".
- Tags must contain exactly 10 items.
- FAQ must contain exactly 3 items.
- Chapters must be YouTube-ready and grounded in the flow of the transcript.
- Learning objectives must use Bloom's Taxonomy verbs.
"""


TRANSCRIPT_REFINEMENT_PROMPT = """You are a transcript refinement editor for a professional e-learning platform.

Clean the raw transcript while preserving the original pedagogical flow, sequence, examples, and instructor intent.

Rules:
- Correct obvious transcription errors and technical terms.
- Remove speech fillers such as uh, um, like, you know, repeated false starts, and accidental repetitions.
- Preserve useful teaching emphasis and step-by-step explanations.
- Do not add new concepts.
- Do not summarize.
- Do not write commentary.
- Return only the refined transcript text.
"""


LANDING_PAGE_PROMPT = """Using the following Course Metadata JSON, generate a Next.js component using Tailwind CSS for a course landing page on Acadma.

Page Requirements:
- Header: Standard Acadma navigation: Home, Categories, Courses, News, Contact Us, Sign In.
- Hero Section: Display the Primary Title, the Big Promise as a sub-headline, and a Join Now CTA.
- Content Grid:
  - Left Column: What You Will Learn and the full course schedule/duration.
  - Right Column: Course Metadata including duration, category, and target audience.
- Video Section: A placeholder for the video player with YouTube chapters listed as a clickable sidebar or accordion.
- FAQ: Clean accessible accordion using the generated FAQ data.
- Styling: Use bg-slate-50, text-indigo-900 for headers, and rounded-2xl for cards.
- Constraints: Do not use "In this video" or fluff. Focus on high-end, professional e-learning aesthetics.

Return only a complete TSX component. Do not wrap it in markdown fences.
"""


DEMO_LANDING_PROMPT_TEMPLATE = """Using the following Course Metadata JSON, generate a polished Next.js component using Tailwind CSS for a course landing page on Acadma.

Design Vibe: {vibe}

Page Requirements:
- Header: Standard Acadma navigation: Home, Categories, Courses, News, Contact Us, Sign In.
- Hero: Clear primary title, Big Promise, and one Join Now CTA. Keep the copy simple and easy for learners.
- Visual Style: Match the selected vibe through color accents, section rhythm, and button styling. Avoid visual clutter.
- Learning Section: Show what students will learn in short, practical bullets.
- Course Details: Show duration, category, level/target audience, and tags.
- Video Section: Add a clean video placeholder and YouTube chapters as a sidebar or accordion.
- FAQ: Add a concise accessible FAQ accordion from the metadata.
- Layout: Premium but easy to read. Use generous spacing, rounded-2xl cards, and responsive mobile-first sections.
- Constraints: Do not use "In this video". Do not add claims beyond the metadata. No fluff.

Return only a complete TSX component. Do not wrap it in markdown fences.
"""


LANDING_VIBES = {
    "luxury": "Deep Indigo and Gold",
    "modern": "Midnight Black and Neon Teal",
    "organic": "Forest Green and Cream",
}


def generate_course_metadata_with_vertex(
    transcript: str,
    *,
    video_url: str,
    mp3_url: str,
    transcript_url: str,
) -> dict[str, Any]:
    refined_transcript = refine_transcript_with_vertex(transcript)

    prompt = (
        f"{MASTER_COURSE_ARCHITECT_PROMPT}\n\n"
        f"Source video URL: {video_url or ''}\n"
        f"MP3 URL: {mp3_url or ''}\n"
        f"Transcript URL: {transcript_url or ''}\n\n"
        f"Refined Transcript:\n{refined_transcript}"
    )
    text = _generate_vertex_text(prompt, response_mime_type="application/json")
    try:
        metadata = json.loads(text)
    except json.JSONDecodeError:
        metadata = {
            "core_identity": {
                "primary_title": "Generated course metadata",
                "alternative_title": "Generated course metadata",
                "category": "Course",
                "tags": [],
            },
            "hook": {
                "short_description": "Gemini returned non-JSON metadata. See raw_output.",
                "learning_objectives": [],
                "big_promise": "",
            },
            "video_metadata": {"estimated_duration": "", "youtube_chapters": []},
            "student_support": {"faq": [], "target_audience": ""},
            "raw_output": text,
        }
    metadata["refined_transcript"] = refined_transcript
    metadata.setdefault("source_reference", {})
    metadata["source_reference"].update(
        {
            "video_url": video_url,
            "mp3_url": mp3_url,
            "transcript_url": transcript_url,
        }
    )
    return metadata


def generate_course_data_with_vertex(
    transcript: str,
    *,
    video_url: str,
    mp3_url: str,
    transcript_url: str,
) -> dict[str, Any]:
    return generate_course_metadata_with_vertex(
        transcript,
        video_url=video_url,
        mp3_url=mp3_url,
        transcript_url=transcript_url,
    )


def refine_transcript_with_vertex(transcript: str) -> str:
    prompt = f"{TRANSCRIPT_REFINEMENT_PROMPT}\n\nRaw Transcript:\n{transcript}"
    return _generate_vertex_text(prompt, response_mime_type="text/plain")


def build_demo_landing_prompt(vibe: str = "luxury", uploaded_prompt: str | None = None) -> str:
    vibe_label = LANDING_VIBES.get(vibe, vibe)
    prompt = DEMO_LANDING_PROMPT_TEMPLATE.format(vibe=vibe_label)
    if uploaded_prompt and uploaded_prompt.strip():
        prompt = (
            f"{uploaded_prompt.strip()}\n\n"
            "Apply this selected style control while keeping the uploaded prompt's structure:\n"
            f"Design Vibe: {vibe_label}\n\n"
            "Keep future upgrades easy: treat the vibe line as the only style knob unless more options are supplied.\n"
        )
    return prompt


def generate_landing_page_with_vertex(metadata: dict[str, Any], custom_prompt: str | None = None) -> str:
    base_prompt = custom_prompt.strip() if custom_prompt and custom_prompt.strip() else LANDING_PAGE_PROMPT
    prompt = (
        f"{base_prompt}\n\n"
        "Use the Course Metadata JSON below as the only content source.\n"
        "Return only a complete TSX component. Do not wrap it in markdown fences.\n\n"
        f"Metadata JSON:\n{json.dumps(metadata, indent=2)}"
    )
    text = _generate_vertex_text(prompt, response_mime_type="text/plain")
    return text.strip().replace("```tsx", "").replace("```jsx", "").replace("```", "").strip()


def _generate_vertex_text(prompt: str, *, response_mime_type: str) -> str:
    project_id = os.getenv("VERTEX_PROJECT_ID") or os.getenv("GOOGLE_CLOUD_PROJECT")
    location = os.getenv("VERTEX_LOCATION", "us-central1")
    model = os.getenv("VERTEX_GEMINI_MODEL", "gemini-1.5-pro")
    if not project_id:
        raise RuntimeError("Set VERTEX_PROJECT_ID or GOOGLE_CLOUD_PROJECT to use Vertex AI Gemini.")

    credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    credentials.refresh(Request())

    url = (
        f"https://{location}-aiplatform.googleapis.com/v1/projects/{project_id}/locations/{location}"
        f"/publishers/google/models/{model}:generateContent"
    )
    generation_config: dict[str, Any] = {"temperature": 0.2}
    if response_mime_type == "application/json":
        generation_config["responseMimeType"] = response_mime_type
    response = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {credentials.token}",
            "Content-Type": "application/json",
        },
        json={
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": generation_config,
        },
        timeout=600,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"Vertex AI Gemini request failed: {response.status_code} {response.text[:1000]}")
    return _extract_text(response.json())


def _extract_text(payload: dict[str, Any]) -> str:
    candidates = payload.get("candidates") or []
    if not candidates:
        raise RuntimeError("Vertex AI Gemini returned no candidates.")
    parts = candidates[0].get("content", {}).get("parts", [])
    text = "".join(part.get("text", "") for part in parts).strip()
    if not text:
        raise RuntimeError("Vertex AI Gemini returned an empty response.")
    return text

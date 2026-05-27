# Course Creation Blueprint

This document lists the source types, processing methods, and course outputs that should sit around the transcription engine.

## Source Inputs

Already included:

- Google Drive public file link
- Google Drive public folder link
- Google Cloud Storage file
- Google Cloud Storage folder
- Browser upload
- Cloudflare R2 public file link
- Direct public video/audio URL

Good next additions:

- YouTube/Vimeo/Wistia links, only when you own the content or have permission
- Zoom/Meet recording exports
- Existing `.srt`, `.vtt`, `.txt`, or `.docx` transcripts
- Podcast/audio-only files: `.mp3`, `.wav`, `.m4a`, `.flac`
- Slide decks: `.pptx` or Google Slides export
- PDFs, handouts, workbook files, and notes
- LMS exports from Teachable, Thinkific, Kajabi, Moodle, or similar platforms

## Transcription Enhancements

High-value additions:

- Speaker diarization for interviews, coaching calls, or multi-teacher lessons
- Word-level timestamps for clickable video references
- Segment-level timestamps for lesson/chapter generation
- Language detection and multilingual transcription
- Translation into target course languages
- Human review status: raw, reviewed, approved
- Confidence scoring to flag weak transcript sections
- Glossary injection for brand names, technical terms, and instructor names

## Media Understanding

Transcription alone misses visual teaching content. Add these when course quality matters:

- Slide OCR: extract text from frames/slides
- Scene/chapter detection: identify natural lesson boundaries
- Key frame capture: save screenshots for course notes
- Whiteboard extraction: capture diagrams and formulas
- On-screen code extraction for programming courses
- Audio cleanup: noise reduction before transcription

## Course Creation Methods

Recommended processing stages:

1. Clean transcript  
   Remove filler words, repeated phrases, false starts, and transcription artifacts.

2. Segment into lessons  
   Split by topic, not by fixed duration only. Keep source video URL plus start/end time.

3. Create module structure  
   Group related lessons into modules with a clear learning progression.

4. Generate learning objectives  
   Each lesson should answer: “After this lesson, the learner can...”

5. Produce lesson assets  
   Generate lesson title, summary, notes, definitions, examples, and action steps.

6. Create assessments  
   Generate quizzes, answer keys, assignments, reflection prompts, and practical exercises.

7. Create workbook material  
   Convert lessons into worksheets, checklists, templates, and practice activities.

8. Quality review  
   Flag unclear sections, missing examples, weak audio, low confidence transcription, and duplicated lessons.

9. Export course sheet  
   Keep one row per lesson with source video reference, transcript reference, timestamps, and generated course fields.

## Course Sheet Columns

Recommended final columns:

- Course name
- Module number
- Module title
- Lesson number
- Lesson title
- Lesson type: video, reading, quiz, assignment, live session
- Learning objective
- Lesson summary
- Clean lesson notes
- Key concepts
- Examples used
- Action steps
- Quiz questions
- Correct answers
- Assignment prompt
- Workbook prompt
- Source video URL
- Transcript URL
- Start timestamp
- End timestamp
- Review status
- Quality flags

## Storage Layout

Recommended GCS structure:

```text
gs://YOUR_BUCKET/raw-videos/
gs://YOUR_BUCKET/raw-uploads/
gs://YOUR_BUCKET/audio/
gs://YOUR_BUCKET/transcripts/raw/
gs://YOUR_BUCKET/transcripts/clean/
gs://YOUR_BUCKET/course-sheets/
gs://YOUR_BUCKET/course-assets/keyframes/
gs://YOUR_BUCKET/course-assets/workbooks/
gs://YOUR_BUCKET/logs/
```

## Operational Controls

Useful controls for the web panel:

- Downloader tab for importing Drive/R2/public files into GCS before transcription
- Pause queue
- Retry failed task
- Cancel queued task
- Priority: normal/high
- Batch name or project name
- Cost estimate before running
- Engine recommendation based on quality/cost
- Export task history
- Filter by status, source, engine, or batch

## Recommended Build Order

1. Stable transcription queue
2. MP3 storage and transcript storage
3. Course sheet generator
4. Transcript cleaner
5. Lesson/module generator
6. Quiz and assignment generator
7. Human review workflow
8. Slide/PDF/OCR enrichment
9. Multi-language export

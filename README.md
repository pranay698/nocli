# GCP Course Creation Engine

Batch pipeline and browser control panel for turning videos into transcript files, then into a course planning sheet that keeps the original video URL as the reference for every generated lesson row.

## What This Builds

1. Browser UI for creating transcription tasks.
2. Inputs from Google Drive public links, GCS files/folders, uploads, public video/audio URLs, and Cloudflare R2 public links.
3. Existing MP3 inputs from Google Drive, GCS, public URLs, R2 public URLs, and local upload.
4. Existing transcript inputs from Google Docs, Drive `.txt`, GCS `.txt`, public `.txt`, and local `.txt` upload.
5. Engine selection: convert to MP3 only, Google Speech-to-Text, Whisper tiny, Whisper small, or Whisper large-v3-turbo.
6. MP3 conversion with `ffmpeg`, saved to GCS.
7. Optional 5, 10, 15, or 20 minute MP3 chunking for long videos.
8. Transcript JSON/TXT files saved to GCS.
9. Task progress, waiting queue, stage, status, history, transcript viewer, MP3 player, and CSV export.
10. Access and account tracking for GCS, Google Drive, and Cloudflare R2 sources.
11. Historic asset table across video, MP3, transcript, and generated course data.
12. Vertex AI Gemini transcript refinement, metadata generation, and landing page component generation.
13. Course CSV builder from transcript JSON files.

## GCS Layout

Recommended bucket structure:

```text
gs://YOUR_BUCKET/raw-videos/
gs://YOUR_BUCKET/audio/
gs://YOUR_BUCKET/transcripts/
gs://YOUR_BUCKET/course-sheets/
```

## Setup

Install `ffmpeg` and authenticate with Google Cloud:

```bash
gcloud auth application-default login
gcloud config set project YOUR_PROJECT_ID
```

Install Python dependencies:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Whisper support is best installed with Python 3.10-3.12. The Dockerfile uses Python 3.11.

Enable APIs:

```bash
gcloud services enable storage.googleapis.com speech.googleapis.com
```

## Run The Web Control Panel

Set bucket defaults:

```bash
export RAW_UPLOAD_PREFIX=gs://YOUR_BUCKET/raw-uploads/
export DEFAULT_AUDIO_PREFIX=gs://YOUR_BUCKET/audio/
export DEFAULT_TRANSCRIPT_PREFIX=gs://YOUR_BUCKET/transcripts/
export COURSE_ENGINE_DATA_DIR=/tmp/course-engine
export COURSE_ENGINE_WORKERS=1
export VERTEX_PROJECT_ID=YOUR_PROJECT_ID
export VERTEX_LOCATION=us-central1
export VERTEX_GEMINI_MODEL=gemini-1.5-pro
```

Start the app:

```bash
python -m course_engine serve --host 0.0.0.0 --port 8080
```

Open:

```text
http://localhost:8080
```

For GCP VM deployment, see `deploy-gce-vm.md`.

For bucket permissions and service account setup, see `gcp-authorization.md`.

For production hardening and the final go-live checklist, see `PRODUCTION_READINESS.md`.

For the full course-creation roadmap after transcription, see `course-creation-blueprint.md`.

## Transcribe Videos

Dry-run first:

```bash
python -m course_engine transcribe \
  --project-id YOUR_PROJECT_ID \
  --input-prefix gs://YOUR_BUCKET/raw-videos/ \
  --audio-prefix gs://YOUR_BUCKET/audio/ \
  --transcript-prefix gs://YOUR_BUCKET/transcripts/ \
  --language-code en-IN \
  --dry-run
```

Run for 5 videos:

```bash
python -m course_engine transcribe \
  --project-id YOUR_PROJECT_ID \
  --input-prefix gs://YOUR_BUCKET/raw-videos/ \
  --audio-prefix gs://YOUR_BUCKET/audio/ \
  --transcript-prefix gs://YOUR_BUCKET/transcripts/ \
  --language-code en-IN \
  --limit 5
```

Run all videos:

```bash
python -m course_engine transcribe \
  --project-id YOUR_PROJECT_ID \
  --input-prefix gs://YOUR_BUCKET/raw-videos/ \
  --audio-prefix gs://YOUR_BUCKET/audio/ \
  --transcript-prefix gs://YOUR_BUCKET/transcripts/ \
  --language-code en-IN
```

## Build Course Sheet

```bash
python -m course_engine build-course-sheet \
  --transcript-prefix gs://YOUR_BUCKET/transcripts/ \
  --output-uri gs://YOUR_BUCKET/course-sheets/course_sheet.csv
```

The CSV includes:

- source video URL
- transcript URL
- lesson title
- lesson summary
- lesson text
- start and end timestamps
- suggested quiz questions

## Queue A Whole GCS Folder

This queues every supported video found recursively under the folder prefix, including subfolders:

```bash
python -m course_engine queue-gcs-folder \
  --folder-uri gs://YOUR_SOURCE_BUCKET/folder/subfolder/ \
  --audio-prefix gs://YOUR_OUTPUT_BUCKET/audio/ \
  --transcript-prefix gs://YOUR_OUTPUT_BUCKET/transcripts/ \
  --engine google_speech \
  --language-code en-IN \
  --db /data/course-engine/tasks.sqlite3
```

Export the full task log for local AI processing or audit:

```bash
python -m course_engine export-task-log \
  --db /data/course-engine/tasks.sqlite3 \
  --output task-log.csv
```

## Queue A Whole Google Drive Course Folder

For course folders like:

```text
Course Name/
  Day 1/
  Day 2/
  Day 3/
  Day 4/
  Day 5/
```

Select **Google Drive public folder** and paste the top course folder link. The app recursively scans subfolders and queues every video it finds. The task history keeps the folder path, such as `Course Name/Day 1/class-1.mp4`, so the course/day structure is easy to audit later.

Drive folder scanning uses the VM service account by default when the Drive API is enabled in GCP. The folder must be public or shared with the VM service account.

An API key is optional fallback only:

```bash
GOOGLE_DRIVE_API_KEY=your_api_key_here
```

## Long Videos And Parallel Runs

For one-hour class recordings, use the UI chunk option and start with `10 minutes`. The app saves the full MP3 first, then splits it into chunk files under `audio/chunks/...`, transcribes each chunk, offsets timestamps, and merges the transcript.

The web worker runs one task at a time by default. On a stronger VM or GPU machine, set this in `/data/course-engine/.env` before restarting Docker:

```bash
COURSE_ENGINE_WORKERS=3
```

Keep this low for Google Speech-to-Text or small CPU VMs. Increase it when the VM has enough CPU/GPU/RAM and you have confirmed quota.

## Import Existing MP3 Or Transcript Files

Use the Transcribe tab source dropdown when you already have part of the workflow complete:

- Choose a **Google Drive MP3**, **GCS MP3**, **Public MP3**, **R2 MP3**, or **Upload MP3** source to skip video conversion and go directly to transcription.
- Choose **Google Drive video to MP3 with yt-dlp** when a Drive video link should be extracted directly to MP3 through `yt-dlp` and FFmpeg.
- Choose a **Google Drive Doc transcript**, **Drive TXT transcript**, **GCS TXT transcript**, **Public TXT transcript**, or **Upload TXT transcript** source to skip audio processing and save the transcript as the task output.

Imported transcripts are saved as both `.json` and `.txt` in the transcript folder, so they can immediately be used for **Generate Metadata** and landing page generation.

## Google Drive Download Fallbacks

Single Google Drive media links are downloaded in three attempts:

1. `gdown` using the full shared URL.
2. Direct Google Drive confirm-token download.
3. `yt-dlp` as a final fallback for links where Drive returns a viewer page or warning page.

After the raw media is downloaded, the app uses `ffmpeg` to create the clean MP3 and then continues with transcription.

## Generate Metadata And Landing Pages With Vertex AI

After a transcript exists, use **Generate Metadata** in the task row. The app sends the transcript to Vertex AI Gemini in two steps:

1. Refine the transcript by correcting technical terms and removing speech fillers while preserving teaching flow.
2. Generate metadata with the Master Course Architect prompt.

The metadata includes:

- core identity with primary title, SEO title, category, and 10 tags
- hook with short description, Bloom's Taxonomy learning objectives, and big promise
- video metadata with estimated duration and YouTube chapters
- student support with 3 transcript-grounded FAQ items and target audience

The app saves files under:

```text
gs://YOUR_BUCKET/transcripts/metadata/
```

Use **Generate Landing Page** after metadata exists. You can optionally upload a `.docx`, `.txt`, or `.md` prompt file before clicking Generate Landing Page. The app extracts the prompt text, stores it with the task, and uses it instead of the default landing-page prompt.

You can also select **Use demo prompt** and choose a landing-page vibe:

- Deep Indigo and Gold
- Midnight Black and Neon Teal
- Forest Green and Cream

The vibe is treated as a small style control line, so future prompt upgrades can change the prompt structure without rewriting the whole workflow.

It saves a Next.js/Tailwind Acadma landing page component under:

```text
gs://YOUR_BUCKET/transcripts/landing-pages/
```

The task row and Historic Course Assets table show the refined transcript, metadata JSON, prompt reference, landing page link, course title, and description.

## Notes

- Start with `--limit 5` before processing all 1000 videos.
- Keep Cloud Speech-to-Text quota and pricing in mind before the full run.
- For production scale, run this inside Cloud Run Jobs with a low concurrency first, then increase gradually.

# Course Transcription Engine: Production Readiness

This product is ready for controlled pilot use after VM deployment, IAM setup, and a small batch test. For full production over hundreds or thousands of videos, complete the hardening checklist below.

## Current Product Flow

1. Ingest source video from Google Drive public link, GCS file/folder, public URL, Cloudflare R2 public URL, or browser upload.
2. Download source to VM working storage.
3. Convert video to MP3 with FFmpeg.
4. Optionally split MP3 into chunks.
5. Transcribe with Google Speech-to-Text or Whisper.
6. Save MP3, transcript JSON, transcript TXT, and task log to GCS.
7. Refine transcript with Vertex AI Gemini.
8. Generate course metadata JSON with the Master Course Architect prompt.
9. Optionally upload a custom landing-page prompt file.
10. Generate Acadma Next.js/Tailwind landing page component.
11. Track all outputs in the task history and Historic Course Assets table.

## Production Must-Haves Before Bulk Runs

### Security

- Add login protection before exposing the app publicly.
- Do not expose port `8080` to the open internet for production. Put it behind IAP, VPN, Cloudflare Access, or a reverse proxy with authentication.
- Keep `.env` only on the VM. Never upload `.env` to GitHub.
- Move long-lived R2 secrets to GCP Secret Manager once the workflow is stable.
- Restrict the VM service account to the required buckets and APIs.

### Source Access

- GCS source buckets need `roles/storage.objectViewer` for the VM service account.
- GCS output buckets need `roles/storage.objectUser` or narrower write permissions.
- Google Drive public files must be shared as `Anyone with the link: Viewer`.
- Google Drive folder import needs `GOOGLE_DRIVE_API_KEY`.
- Cloudflare R2 public links work now.
- Cloudflare R2 private authenticated `r2://...` import is still a recommended next feature.

### Reliability

- Use a regular VM for long runs. Spot VM is cheaper but can stop mid-job.
- Use persistent disk mounted at `/data/course-engine`.
- Keep `COURSE_ENGINE_WORKERS=1` for first tests.
- Increase workers slowly after validating CPU, RAM, disk, Google Speech quota, and Vertex quota.
- Run first batch with 5 videos, then 25, then 100.
- Keep chunking at 10 minutes for long videos until failure rate is known.

### Data Layout

Recommended GCS layout:

```text
gs://YOUR_BUCKET/raw-videos/
gs://YOUR_BUCKET/audio/
gs://YOUR_BUCKET/audio/chunks/
gs://YOUR_BUCKET/transcripts/
gs://YOUR_BUCKET/transcripts/_task-logs/
gs://YOUR_BUCKET/transcripts/metadata/
gs://YOUR_BUCKET/transcripts/metadata/prompts/
gs://YOUR_BUCKET/transcripts/landing-pages/
gs://YOUR_BUCKET/course-sheets/
```

### Monitoring

- Export task CSV daily for audit.
- Watch failed task reasons before increasing concurrency.
- Track cost by bucket, Speech-to-Text, Vertex AI, and VM/GPU separately.
- Add log rotation if Docker logs grow quickly.

## Recommended Next Features

1. Private R2 authenticated import:
   - Add `r2://bucket/key` source support.
   - Read `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, and `R2_ENDPOINT` from `.env` or Secret Manager.

2. User authentication:
   - Protect the app with Google IAP or Cloudflare Access.
   - Add per-user task ownership later if multiple operators use it.

3. Stronger queue backend:
   - SQLite is fine for one VM.
   - For multiple VMs or Cloud Run workers, move tasks to Cloud SQL, Firestore, or Pub/Sub plus Cloud Tasks.

4. Better retry controls:
   - Retry from last successful asset: MP3, transcript, metadata, or landing page.
   - Add bulk retry for failed tasks.

5. Cost controls:
   - Add estimated per-task cost.
   - Add daily spend guardrails.
   - Add max concurrent Google Speech and Vertex calls.

6. Course sheet workflow:
   - Add a dedicated Course Sheet tab.
   - Build one combined sheet from selected metadata JSON files.
   - Keep original video, MP3, transcript, metadata, and landing page URLs in every row.

7. Production landing-page review:
   - Add preview rendering for generated TSX.
   - Add manual approve/reject state before publishing to Acadma.

## Go-Live Pilot Checklist

- VM starts successfully.
- Docker starts app after reboot.
- `/data/course-engine/.env` has bucket, Vertex, and worker settings.
- Service account can read source bucket and write output bucket.
- Speech-to-Text works for one GCS MP3.
- Vertex AI metadata generation works for one transcript.
- Landing page generation works with default prompt.
- Landing page generation works with uploaded `.docx` prompt.
- Historic Course Assets table shows video, MP3, transcript, refined transcript, metadata, prompt, and landing page links.
- Cancel works for queued tasks.
- Failed reason appears clearly for broken Drive/R2/GCS links.

## Current Production Recommendation

Use this version for a controlled pilot on 5-25 videos. Do not run all 1000 videos until private source access, app authentication, and first-batch cost/failure metrics are confirmed.

# Cloud Run Job Example

Build and deploy the container:

```bash
gcloud builds submit --tag gcr.io/YOUR_PROJECT_ID/course-engine

gcloud run jobs create course-transcriber \
  --image gcr.io/YOUR_PROJECT_ID/course-engine \
  --region asia-south1 \
  --memory 4Gi \
  --cpu 2 \
  --task-timeout 7200 \
  --args transcribe,--project-id,YOUR_PROJECT_ID,--input-prefix,gs://YOUR_BUCKET/raw-videos/,--audio-prefix,gs://YOUR_BUCKET/audio/,--transcript-prefix,gs://YOUR_BUCKET/transcripts/,--language-code,en-IN
```

Run the job:

```bash
gcloud run jobs execute course-transcriber --region asia-south1
```

Create the course sheet:

```bash
gcloud run jobs create course-sheet-builder \
  --image gcr.io/YOUR_PROJECT_ID/course-engine \
  --region asia-south1 \
  --memory 1Gi \
  --cpu 1 \
  --task-timeout 3600 \
  --args build-course-sheet,--transcript-prefix,gs://YOUR_BUCKET/transcripts/,--output-uri,gs://YOUR_BUCKET/course-sheets/course_sheet.csv

gcloud run jobs execute course-sheet-builder --region asia-south1
```

For the first real run, add `--limit,5` to the transcriber args.

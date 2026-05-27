# GCP Authorization For Bulk Transcription

For bulk runs, use a dedicated Google Cloud service account. Do not rely on a personal `gcloud auth` login for production.

## Recommended Service Account

Google Workspace/admin email:

```text
PRANAY.TOSHU@GMAIL.COM
```

Use this email to manage the Google Cloud project, billing, VM access, and IAM setup. For the app itself, create one service account for the transcription engine:

Create one service account for the transcription engine:

```bash
gcloud iam service-accounts create course-transcription-engine \
  --display-name "Course Transcription Engine"
```

Use this service account on the Compute Engine VM, Cloud Run service, or Cloud Run Job that runs the app.

## Optional Admin Access

If this Gmail account needs project-level admin access, grant it from the Google Cloud Console IAM page, or use:

```bash
gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
  --member="user:PRANAY.TOSHU@GMAIL.COM" \
  --role="roles/owner"
```

Use project owner only if you are comfortable giving full control. For day-to-day operations, narrower roles are safer.

## Required Bucket Access

If one bucket stores everything, grant these roles on that bucket:

```bash
gcloud storage buckets add-iam-policy-binding gs://YOUR_BUCKET \
  --member="serviceAccount:course-transcription-engine@YOUR_PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/storage.objectViewer"

gcloud storage buckets add-iam-policy-binding gs://YOUR_BUCKET \
  --member="serviceAccount:course-transcription-engine@YOUR_PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/storage.objectCreator"
```

For retrying or overwriting outputs, also grant:

```bash
gcloud storage buckets add-iam-policy-binding gs://YOUR_BUCKET \
  --member="serviceAccount:course-transcription-engine@YOUR_PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/storage.objectUser"
```

Use `objectViewer` for source-only buckets and `objectCreator` or `objectUser` for output buckets.

## External Source Buckets

If source videos are in another Google Cloud project or organization, the owner of that bucket must grant read access to the app service account:

```bash
gcloud storage buckets add-iam-policy-binding gs://OTHER_SOURCE_BUCKET \
  --member="serviceAccount:course-transcriber-sa@ninth-arena-404220.iam.gserviceaccount.com" \
  --role="roles/storage.objectViewer"
```

The app can then read:

```text
gs://OTHER_SOURCE_BUCKET/path/to/video.mp4
```

and save MP3/transcripts into:

```text
gs://course-videos-ninth-arena/audio/
gs://course-videos-ninth-arena/transcripts/
```

## Cloudflare R2 Access

For public R2 links, no authentication is needed. Use the app's `Public video/audio URL` or `Cloudflare R2 public file` source.

For private R2 objects, create a read-only R2 API token in Cloudflare and store the credentials on the VM through environment variables or Secret Manager. Do not paste long-lived R2 secrets into the UI.

## Speech-to-Text Access

If using Google Speech-to-Text:

```bash
gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
  --member="serviceAccount:course-transcription-engine@YOUR_PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/speech.client"
```

If using Vertex AI Gemini for course-data generation:

```bash
gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
  --member="serviceAccount:course-transcription-engine@YOUR_PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/aiplatform.user"
```

Enable APIs:

```bash
gcloud services enable storage.googleapis.com speech.googleapis.com aiplatform.googleapis.com
```

## Attach Service Account To A VM

When creating a VM:

```bash
gcloud compute instances create course-engine-vm \
  --zone=asia-south1-a \
  --machine-type=n2-standard-4 \
  --service-account=course-transcription-engine@YOUR_PROJECT_ID.iam.gserviceaccount.com \
  --scopes=https://www.googleapis.com/auth/cloud-platform
```

If using an existing VM, stop it first, then update the service account:

```bash
gcloud compute instances set-service-account course-engine-vm \
  --zone=asia-south1-a \
  --service-account=course-transcription-engine@YOUR_PROJECT_ID.iam.gserviceaccount.com \
  --scopes=https://www.googleapis.com/auth/cloud-platform
```

## Local Development

For local testing only:

```bash
gcloud auth application-default login
gcloud config set project YOUR_PROJECT_ID
```

Or use a service account key only if your security policy allows it:

```bash
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
```

Avoid service account keys in production. Prefer attached VM or Cloud Run service accounts.

## Bulk Run Checklist

Before processing hundreds or thousands of videos:

- Confirm the service account can list the source folder.
- Confirm it can upload to the MP3/audio folder.
- Confirm it can upload to the transcript folder.
- Confirm Speech-to-Text access if using Google transcription.
- Run 1 video first.
- Run 5 videos next.
- Then run the full batch.

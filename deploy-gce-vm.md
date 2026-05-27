# Deploy On A Google Compute Engine VM

This is the recommended economical deployment if you want Whisper models, especially `small` or `large-v3-turbo`.

## 1. Create A VM

Use a VM with a persistent disk. For Whisper, prefer a GPU VM. For a first test, CPU is fine with `whisper_tiny` or Google Speech-to-Text.

Install:

```bash
sudo apt-get update
sudo apt-get install -y docker.io ffmpeg
sudo usermod -aG docker $USER
```

If using NVIDIA GPU, install the NVIDIA container runtime for your chosen VM image.

## 2. Prepare Environment

Create a file named `/data/course-engine/.env`:

```bash
RAW_UPLOAD_PREFIX=gs://YOUR_BUCKET/raw-uploads/
DEFAULT_AUDIO_PREFIX=gs://YOUR_BUCKET/audio/
DEFAULT_TRANSCRIPT_PREFIX=gs://YOUR_BUCKET/transcripts/
COURSE_ENGINE_DATA_DIR=/data/course-engine
COURSE_ENGINE_DB=/data/course-engine/tasks.sqlite3
COURSE_ENGINE_WORKERS=1
GOOGLE_DRIVE_API_KEY=
VERTEX_PROJECT_ID=YOUR_PROJECT_ID
VERTEX_LOCATION=us-central1
VERTEX_GEMINI_MODEL=gemini-1.5-pro
```

Authenticate the VM with a service account that can read/write the bucket and call Speech-to-Text.

## 3. Build And Run

```bash
docker build -t course-engine .

docker run -d \
  --name course-engine \
  --restart unless-stopped \
  --env-file /data/course-engine/.env \
  -v /data/course-engine:/data/course-engine \
  -p 8080:8080 \
  course-engine
```

Open:

```text
http://YOUR_VM_EXTERNAL_IP:8080
```

## 4. GCP Permissions

The VM service account needs:

- Storage Object Viewer for source videos
- Storage Object Creator for MP3/transcript outputs
- Speech-to-Text access if using Google Speech-to-Text

See `gcp-authorization.md` for exact commands.

## 5. Production Notes

For 1000 videos, start with 5 tasks first. Then increase in batches. On one VM, raise `COURSE_ENGINE_WORKERS` carefully when you have enough CPU/GPU/RAM. If you scale across multiple VMs later, move task storage from SQLite to Cloud SQL or Firestore.

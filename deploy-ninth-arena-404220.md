# Deployment Commands For `ninth-arena-404220`

Project:

```text
ninth-arena-404220
```

Bucket:

```text
gs://course-videos-ninth-arena
```

Service account:

```text
course-transcriber-sa@ninth-arena-404220.iam.gserviceaccount.com
```

VM:

```text
transcription-vm
asia-south1-a
```

## 1. Enable Required APIs

Run in Cloud Shell:

```bash
gcloud config set project ninth-arena-404220

gcloud services enable \
  compute.googleapis.com \
  storage.googleapis.com \
  speech.googleapis.com \
  cloudbuild.googleapis.com
```

## 2. Grant Speech-To-Text Access

You already granted bucket access. If you want the Google Speech-to-Text option, also run:

```bash
gcloud projects add-iam-policy-binding ninth-arena-404220 \
  --member="serviceAccount:course-transcriber-sa@ninth-arena-404220.iam.gserviceaccount.com" \
  --role="roles/speech.client"

gcloud projects add-iam-policy-binding ninth-arena-404220 \
  --member="serviceAccount:course-transcriber-sa@ninth-arena-404220.iam.gserviceaccount.com" \
  --role="roles/aiplatform.user"
```

## 3. Create The VM

You already started this command. If it finishes successfully, continue to step 4.

Important: you created a Spot VM. That is cheaper, but Google can stop it. For long bulk jobs, a regular VM is safer. Spot is okay for first tests.

## 4. SSH Into The VM

```bash
gcloud compute ssh transcription-vm --zone=asia-south1-a
```

## 5. Install Docker And Git On The VM

Run inside the VM:

```bash
sudo apt-get update
sudo apt-get install -y docker.io git ffmpeg
sudo usermod -aG docker $USER
newgrp docker
```

## 6. Get The App Code Onto The VM

Option A: clone from your repo if you upload this project to GitHub.

Option B: copy the project folder from Cloud Shell or your machine to the VM.

Once the code is on the VM, enter the project folder.

## 7. Create Runtime Environment

Run inside the project folder on the VM:

```bash
mkdir -p /data/course-engine

cat > /data/course-engine/.env <<'EOF'
RAW_UPLOAD_PREFIX=gs://course-videos-ninth-arena/raw-uploads/
DEFAULT_AUDIO_PREFIX=gs://course-videos-ninth-arena/audio/
DEFAULT_TRANSCRIPT_PREFIX=gs://course-videos-ninth-arena/transcripts/
COURSE_ENGINE_DATA_DIR=/data/course-engine
COURSE_ENGINE_DB=/data/course-engine/tasks.sqlite3
COURSE_ENGINE_WORKERS=1
GOOGLE_DRIVE_API_KEY=
GOOGLE_WORKSPACE_ADMIN_EMAIL=PRANAY.TOSHU@GMAIL.COM
SERVICE_ACCOUNT_EMAIL=course-transcriber-sa@ninth-arena-404220.iam.gserviceaccount.com
VERTEX_PROJECT_ID=ninth-arena-404220
VERTEX_LOCATION=us-central1
VERTEX_GEMINI_MODEL=gemini-1.5-pro
EOF
```

## 8. Build And Run

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

## 9. Allow Browser Access

Open port 8080:

```bash
gcloud compute firewall-rules create allow-course-engine-8080 \
  --project=ninth-arena-404220 \
  --allow=tcp:8080 \
  --target-tags=http-server \
  --description="Allow course engine web app on port 8080"
```

Then find VM external IP:

```bash
gcloud compute instances describe transcription-vm \
  --zone=asia-south1-a \
  --format='get(networkInterfaces[0].accessConfigs[0].natIP)'
```

Open:

```text
http://VM_EXTERNAL_IP:8080
```

## 10. First Test

Use one video first:

- Source: `gs://course-videos-ninth-arena/raw-videos/YOUR_VIDEO.mp4`
- Engine: `Google Speech-to-Text` or `Whisper tiny`
- Transcript save location: `gs://course-videos-ninth-arena/transcripts/`
- MP3 save location: `gs://course-videos-ninth-arena/audio/`

Then test 5 videos before running the full batch.

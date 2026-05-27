const form = document.querySelector("#taskForm");
const downloadForm = document.querySelector("#downloadForm");
const accessPanel = document.querySelector("#accessPanel");
const accountsPanel = document.querySelector("#accountsPanel");
const transcribeTab = document.querySelector("#transcribeTab");
const downloadTab = document.querySelector("#downloadTab");
const accessTab = document.querySelector("#accessTab");
const accountsTab = document.querySelector("#accountsTab");
const sourceType = document.querySelector("#sourceType");
const sourceValues = document.querySelector("#sourceValues");
const linksField = document.querySelector("#linksField");
const uploadField = document.querySelector("#uploadField");
const uploadLabel = document.querySelector("#uploadLabel");
const uploadFiles = document.querySelector("#uploadFiles");
const engine = document.querySelector("#engine");
const languageCode = document.querySelector("#languageCode");
const transcriptPrefix = document.querySelector("#transcriptPrefix");
const audioPrefix = document.querySelector("#audioPrefix");
const chunkMinutes = document.querySelector("#chunkMinutes");
const landingPromptFile = document.querySelector("#landingPromptFile");
const useDemoPrompt = document.querySelector("#useDemoPrompt");
const landingVibe = document.querySelector("#landingVibe");
const saveMp3 = document.querySelector("#saveMp3");
const formMessage = document.querySelector("#formMessage");
const taskList = document.querySelector("#taskList");
const assetTableBody = document.querySelector("#assetTableBody");
const taskTemplate = document.querySelector("#taskTemplate");
const lastUpdated = document.querySelector("#lastUpdated");
const uploadHint = document.querySelector("#uploadHint");
const downloadSourceType = document.querySelector("#downloadSourceType");
const downloadSourceValues = document.querySelector("#downloadSourceValues");
const downloadDestinationPrefix = document.querySelector("#downloadDestinationPrefix");
const downloadMessage = document.querySelector("#downloadMessage");
const accessProvider = document.querySelector("#accessProvider");
const accessBucket = document.querySelector("#accessBucket");
const accessServiceAccount = document.querySelector("#accessServiceAccount");
const accessMode = document.querySelector("#accessMode");
const accessOutput = document.querySelector("#accessOutput");
const generateAccessButton = document.querySelector("#generateAccessButton");
const copyAccessButton = document.querySelector("#copyAccessButton");
const accountName = document.querySelector("#accountName");
const accountProvider = document.querySelector("#accountProvider");
const accountAuthMethod = document.querySelector("#accountAuthMethod");
const accountStatus = document.querySelector("#accountStatus");
const accountNotes = document.querySelector("#accountNotes");
const saveAccountButton = document.querySelector("#saveAccountButton");
const accountList = document.querySelector("#accountList");

const statusCounts = {
  queued: document.querySelector("#queuedCount"),
  running: document.querySelector("#runningCount"),
  done: document.querySelector("#doneCount"),
  failed: document.querySelector("#failedCount"),
  canceled: document.querySelector("#canceledCount"),
};

function setMessage(text) {
  formMessage.textContent = text;
}

function isUploadSource() {
  return ["upload", "mp3_upload", "transcript_upload"].includes(sourceType.value);
}

function isTranscriptSource() {
  return sourceType.value.startsWith("transcript_");
}

function toggleSourceMode() {
  const uploading = isUploadSource();
  linksField.classList.toggle("hidden", uploading);
  uploadField.classList.toggle("hidden", !uploading);
  engine.disabled = isTranscriptSource();
  saveMp3.disabled = isTranscriptSource();
  chunkMinutes.disabled = isTranscriptSource();
  if (sourceType.value === "mp3_upload") {
    uploadLabel.textContent = "Upload MP3 files";
    uploadFiles.accept = "audio/mpeg,.mp3";
    uploadHint.textContent = "MP3 uploads are saved to GCS audio imports first";
  } else if (sourceType.value === "transcript_upload") {
    uploadLabel.textContent = "Upload TXT transcripts";
    uploadFiles.accept = ".txt,text/plain";
    uploadHint.textContent = "Transcript uploads are saved and ready for course metadata";
  } else if (sourceType.value === "upload") {
    uploadLabel.textContent = "Upload videos";
    uploadFiles.accept = "video/*";
    uploadHint.textContent = "Uploads are stored in GCS first";
  } else if (sourceType.value === "drive_ytdlp_mp3") {
    uploadHint.textContent = "Drive video link is extracted directly to MP3 with yt-dlp and FFmpeg";
  } else if (isTranscriptSource()) {
    uploadHint.textContent = "Transcript sources skip MP3 and transcription";
  } else if (sourceType.value.startsWith("mp3_")) {
    uploadHint.textContent = "MP3 sources skip video conversion";
  } else {
    uploadHint.textContent = "";
  }
}

async function loadConfig() {
  const response = await fetch("/api/config");
  const config = await response.json();
  if (config.defaults.audio_prefix) audioPrefix.value = config.defaults.audio_prefix;
  if (config.defaults.transcript_prefix) transcriptPrefix.value = config.defaults.transcript_prefix;
  if (config.defaults.raw_upload_prefix) downloadDestinationPrefix.value = config.defaults.raw_upload_prefix.replace("/raw-uploads/", "/raw-videos/");
  if (config.defaults.service_account_email) accessServiceAccount.value = config.defaults.service_account_email;
}

async function submitLinks() {
  const values = sourceValues.value
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
  if (!values.length) {
    throw new Error("Add at least one link or folder path.");
  }
  const response = await fetch("/api/tasks", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      source_type: sourceType.value,
      source_values: values,
      engine: engine.value,
      transcript_prefix: transcriptPrefix.value,
      audio_prefix: audioPrefix.value,
      language_code: languageCode.value,
      save_mp3: saveMp3.checked,
      chunk_minutes: Number(chunkMinutes.value || 0),
    }),
  });
  if (!response.ok) throw new Error((await response.json()).detail || "Could not queue task.");
  return response.json();
}

async function submitUploads() {
  if (!uploadFiles.files.length) {
    throw new Error("Choose at least one file.");
  }
  const data = new FormData();
  for (const file of uploadFiles.files) data.append("files", file);
  data.append("source_type", sourceType.value);
  data.append("engine", engine.value);
  data.append("transcript_prefix", transcriptPrefix.value);
  data.append("audio_prefix", audioPrefix.value);
  data.append("language_code", languageCode.value);
  data.append("save_mp3", saveMp3.checked ? "true" : "false");
  data.append("chunk_minutes", chunkMinutes.value || "0");

  const response = await fetch("/api/uploads", { method: "POST", body: data });
  if (!response.ok) throw new Error((await response.json()).detail || "Could not upload videos.");
  return response.json();
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  setMessage("Adding task...");
  try {
    const result = isUploadSource() ? await submitUploads() : await submitLinks();
    setMessage(`Queued ${result.task_ids.length} task(s).`);
    sourceValues.value = "";
    uploadFiles.value = "";
    await loadTasks();
  } catch (error) {
    setMessage(error.message);
  }
});

sourceType.addEventListener("change", toggleSourceMode);
document.querySelector("#refreshButton").addEventListener("click", loadTasks);

function showTab(name) {
  const downloading = name === "download";
  const access = name === "access";
  const accounts = name === "accounts";
  downloadForm.classList.toggle("hidden", !downloading);
  accessPanel.classList.toggle("hidden", !access);
  accountsPanel.classList.toggle("hidden", !accounts);
  form.classList.toggle("hidden", downloading || access || accounts);
  downloadTab.classList.toggle("active", downloading);
  accessTab.classList.toggle("active", access);
  accountsTab.classList.toggle("active", accounts);
  transcribeTab.classList.toggle("active", !downloading && !access && !accounts);
}

transcribeTab.addEventListener("click", () => showTab("transcribe"));
downloadTab.addEventListener("click", () => showTab("download"));
accessTab.addEventListener("click", () => showTab("access"));
accountsTab.addEventListener("click", () => {
  showTab("accounts");
  loadAccounts();
});

downloadForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  downloadMessage.textContent = "Adding download...";
  const values = downloadSourceValues.value
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
  if (!values.length) {
    downloadMessage.textContent = "Add at least one link.";
    return;
  }
  const response = await fetch("/api/downloads", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      source_type: downloadSourceType.value,
      source_values: values,
      destination_prefix: downloadDestinationPrefix.value,
    }),
  });
  if (!response.ok) {
    downloadMessage.textContent = (await response.json()).detail || "Could not queue download.";
    return;
  }
  const result = await response.json();
  downloadMessage.textContent = `Queued ${result.task_ids.length} download(s).`;
  downloadSourceValues.value = "";
  await loadTasks();
});

function normalizeBucket(value) {
  return value.replace(/^gs:\/\//, "").replace(/\/.*$/, "");
}

function generateAccessInstructions() {
  const provider = accessProvider.value;
  const bucket = accessBucket.value.trim();
  const serviceAccount = accessServiceAccount.value.trim();
  const mode = accessMode.value;
  if (!bucket) {
    accessOutput.value = "Enter a bucket/source first.";
    return;
  }
  if (provider === "gcs") {
    if (!serviceAccount) {
      accessOutput.value = "Enter the app service account email first.";
      return;
    }
    const bucketName = normalizeBucket(bucket);
    const commands = [];
    if (mode === "read" || mode === "read_write") {
      commands.push(`gcloud storage buckets add-iam-policy-binding gs://${bucketName} \\\n  --member=\"serviceAccount:${serviceAccount}\" \\\n  --role=\"roles/storage.objectViewer\"`);
    }
    if (mode === "write" || mode === "read_write") {
      commands.push(`gcloud storage buckets add-iam-policy-binding gs://${bucketName} \\\n  --member=\"serviceAccount:${serviceAccount}\" \\\n  --role=\"roles/storage.objectUser\"`);
    }
    accessOutput.value = `Ask the owner/admin of gs://${bucketName} to run:\n\n${commands.join("\n\n")}\n\nThen use this in the app:\nInput source: Google Cloud Storage file or folder\nPath: gs://${bucketName}/path/to/video.mp4`;
    return;
  }
  if (provider === "r2_public") {
    accessOutput.value = `For public Cloudflare R2 objects, no authentication is needed.\n\nUse:\nInput source: Cloudflare R2 public file or Public video/audio URL\nURL: ${bucket}\n\nIf the URL opens/downloads in an incognito browser, the app can download it.`;
    return;
  }
  accessOutput.value = `For private Cloudflare R2, create a read-only R2 API token in Cloudflare.\n\nDo not paste long-lived secrets into this UI.\n\nRecommended VM env names:\nR2_ACCOUNT_ID=...\nR2_ACCESS_KEY_ID=...\nR2_SECRET_ACCESS_KEY=...\nR2_BUCKET=${bucket}\n\nThen the backend can be extended to use S3-compatible authenticated downloads. For now, make R2 objects public or use signed/public URLs in the Downloader tab.`;
}

generateAccessButton.addEventListener("click", generateAccessInstructions);
copyAccessButton.addEventListener("click", async () => {
  await copyText(accessOutput.value);
  copyAccessButton.textContent = "Copied";
  setTimeout(() => {
    copyAccessButton.textContent = "Copy Instructions";
  }, 1000);
});

async function loadAccounts() {
  const response = await fetch("/api/accounts");
  const data = await response.json();
  accountList.replaceChildren(
    ...data.accounts.map((account) => {
      const item = document.createElement("article");
      item.className = "accountItem";
      item.innerHTML = `
        <strong>${account.name}</strong>
        <p>${account.provider} · ${account.auth_method} · ${account.status}</p>
        <p>${account.notes || ""}</p>
      `;
      return item;
    })
  );
}

saveAccountButton.addEventListener("click", async () => {
  if (!accountName.value.trim()) return;
  await fetch("/api/accounts", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      name: accountName.value.trim(),
      provider: accountProvider.value,
      auth_method: accountAuthMethod.value,
      status: accountStatus.value,
      notes: accountNotes.value.trim(),
    }),
  });
  accountName.value = "";
  accountNotes.value = "";
  await loadAccounts();
});

function linkOrDash(uri) {
  if (!uri) return "—";
  const escaped = escapeHtml(uri);
  if (uri.startsWith("gs://")) return escaped;
  return `<a href="${escaped}" target="_blank" rel="noreferrer">${escaped}</a>`;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function copyable(value) {
  if (!value) return "—";
  const encoded = encodeURIComponent(value);
  return `<div class="valueRow"><span>${linkOrDash(value)}</span><button class="copyButton" type="button" data-copy="${encoded}">Copy</button></div>`;
}

function formatDateTime(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

function taskActions(task) {
  const actions = [];
  if (task.text_uri || task.transcript_uri) {
    actions.push(`<a class="smallButton" href="/api/tasks/${task.id}/transcript" target="_blank" rel="noreferrer">View Transcript</a>`);
    actions.push(`<button class="smallButton" type="button" data-course="${task.id}">${task.course_data_uri ? "Regenerate Metadata" : "Generate Metadata"}</button>`);
  }
  if (task.refined_transcript_uri) {
    actions.push(`<a class="smallButton" href="/api/tasks/${task.id}/refined-transcript" target="_blank" rel="noreferrer">View Refined</a>`);
  }
  if (task.mp3_uri) {
    actions.push(`<audio class="audioPlayer" controls preload="none" src="/api/tasks/${task.id}/audio"></audio>`);
  }
  if (task.course_data_uri) {
    actions.push(`<a class="smallButton" href="/api/tasks/${task.id}/course-data" target="_blank" rel="noreferrer">View Metadata</a>`);
    actions.push(`<button class="smallButton" type="button" data-landing="${task.id}">${task.landing_page_uri ? "Regenerate Landing Page" : "Generate Landing Page"}</button>`);
  }
  if (task.landing_page_uri) {
    actions.push(`<a class="smallButton" href="/api/tasks/${task.id}/landing-page" target="_blank" rel="noreferrer">View Landing Page</a>`);
  }
  if (task.landing_prompt_uri) {
    actions.push(`<span class="mutedTiny">Prompt saved</span>`);
  }
  return actions.length ? `<div class="actionRow">${actions.join("")}</div>` : "—";
}

function taskControls(task) {
  if (task.status === "queued" || task.status === "running") {
    return `<button class="dangerButton" type="button" data-cancel="${task.id}">Cancel</button>`;
  }
  return "—";
}

async function copyText(value) {
  if (navigator.clipboard && window.isSecureContext) {
    await navigator.clipboard.writeText(value);
    return;
  }
  const textarea = document.createElement("textarea");
  textarea.value = value;
  textarea.setAttribute("readonly", "");
  textarea.style.position = "fixed";
  textarea.style.top = "-1000px";
  document.body.appendChild(textarea);
  textarea.select();
  document.execCommand("copy");
  textarea.remove();
}

function renderTask(task) {
  const node = taskTemplate.content.firstElementChild.cloneNode(true);
  node.querySelector('[data-field="source"]').textContent = task.source_value;
  node.querySelector('[data-field="message"]').textContent = task.error || task.message || "";
  const status = node.querySelector('[data-field="status"]');
  status.textContent = task.status;
  status.classList.add(task.status);
  node.querySelector('[data-field="progress"]').style.width = `${task.progress || 0}%`;
  node.querySelector('[data-field="sourceLink"]').innerHTML = copyable(task.source_value);
  node.querySelector('[data-field="sourceFolder"]').innerHTML = copyable(task.source_folder_uri);
  node.querySelector('[data-field="savedVideo"]').innerHTML = copyable(task.saved_source_uri);
  node.querySelector('[data-field="stage"]').textContent = task.stage || "—";
  node.querySelector('[data-field="startedAt"]').textContent = formatDateTime(task.started_at);
  node.querySelector('[data-field="completedAt"]').textContent = formatDateTime(task.completed_at);
  node.querySelector('[data-field="chunking"]').textContent = task.chunk_minutes ? `${task.chunk_minutes} min chunks` : "No split";
  node.querySelector('[data-field="engine"]').textContent = task.engine;
  node.querySelector('[data-field="actions"]').innerHTML = taskActions(task);
  node.querySelector('[data-field="controls"]').innerHTML = taskControls(task);
  node.querySelector('[data-field="transcript"]').innerHTML = copyable(task.transcript_uri || task.text_uri);
  node.querySelector('[data-field="mp3"]').innerHTML = copyable(task.mp3_uri);
  node.querySelector('[data-field="taskLog"]').innerHTML = copyable(task.task_log_uri);
  node.querySelector('[data-field="error"]').innerHTML = copyable(task.error);
  return node;
}

function assetState(task) {
  const hasVideo = Boolean(task.saved_source_uri || task.source_value);
  const hasMp3 = Boolean(task.mp3_uri);
  const hasTranscript = Boolean(task.text_uri || task.transcript_uri);
  const hasCourse = Boolean(task.course_data_uri);
  const hasLanding = Boolean(task.landing_page_uri);
  if (hasMp3 && hasTranscript && hasCourse && hasLanding) return "MP3 + transcript + metadata + landing page";
  if (hasMp3 && hasTranscript && hasCourse) return "MP3 + transcript + course data";
  if (hasVideo && hasMp3 && hasTranscript) return "Video + MP3 + transcript";
  if (hasTranscript && hasCourse) return "Transcript + course data";
  if (hasMp3 && hasTranscript) return "MP3 + transcript";
  if (hasVideo && hasMp3) return "Video + MP3";
  if (hasVideo) return "Video";
  return task.status;
}

function assetLink(value, label) {
  if (!value) return "—";
  if (String(value).startsWith("gs://")) {
    return `<span>${escapeHtml(value)}</span>`;
  }
  return `<a href="${escapeHtml(value)}" target="_blank" rel="noreferrer">${escapeHtml(label || value)}</a>`;
}

function renderAssetTable(tasks) {
  assetTableBody.replaceChildren(
    ...tasks.map((task) => {
      const row = document.createElement("tr");
      row.innerHTML = `
        <td>${escapeHtml(assetState(task))}</td>
        <td>${assetLink(task.saved_source_uri || task.source_value, "Video")}</td>
        <td>${task.mp3_uri ? `<a href="/api/tasks/${task.id}/audio" target="_blank" rel="noreferrer">MP3</a><div class="mutedTiny">${escapeHtml(task.mp3_uri)}</div>` : "—"}</td>
        <td>${task.text_uri || task.transcript_uri ? `<a href="/api/tasks/${task.id}/transcript" target="_blank" rel="noreferrer">Transcript</a><div class="mutedTiny">${escapeHtml(task.text_uri || task.transcript_uri)}</div>` : "—"}</td>
        <td>${task.refined_transcript_uri ? `<a href="/api/tasks/${task.id}/refined-transcript" target="_blank" rel="noreferrer">Refined</a><div class="mutedTiny">${escapeHtml(task.refined_transcript_uri)}</div>` : "—"}</td>
        <td>${escapeHtml(task.course_title || "—")}</td>
        <td>${escapeHtml(task.course_description || "—")}</td>
        <td>${task.course_data_uri ? `<a href="/api/tasks/${task.id}/course-data" target="_blank" rel="noreferrer">Metadata</a><div class="mutedTiny">${escapeHtml(task.course_data_uri)}</div>` : "—"}</td>
        <td>${task.landing_prompt_uri ? `<span>Custom prompt</span><div class="mutedTiny">${escapeHtml(task.landing_prompt_uri)}</div>` : "Default"}</td>
        <td>${task.landing_page_uri ? `<a href="/api/tasks/${task.id}/landing-page" target="_blank" rel="noreferrer">Landing</a><div class="mutedTiny">${escapeHtml(task.landing_page_uri)}</div>` : "—"}</td>
      `;
      return row;
    })
  );
}

async function loadTasks() {
  const response = await fetch("/api/tasks");
  const data = await response.json();
  for (const key of Object.keys(statusCounts)) {
    statusCounts[key].textContent = data.counts[key] || 0;
  }
  taskList.replaceChildren(...data.tasks.map(renderTask));
  renderAssetTable(data.tasks);
  lastUpdated.textContent = new Date().toLocaleTimeString();
}

toggleSourceMode();
loadConfig();
loadTasks();
setInterval(loadTasks, 4000);

document.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-copy]");
  if (!button) return;
  await copyText(decodeURIComponent(button.dataset.copy || ""));
  const oldText = button.textContent;
  button.textContent = "Copied";
  setTimeout(() => {
    button.textContent = oldText;
  }, 1000);
});

document.addEventListener("click", async (event) => {
  const cancelButton = event.target.closest("[data-cancel]");
  if (cancelButton) {
    cancelButton.textContent = "Canceling";
    await fetch(`/api/tasks/${cancelButton.dataset.cancel}/cancel`, { method: "POST" });
    await loadTasks();
    return;
  }
  const courseButton = event.target.closest("[data-course]");
  if (courseButton) {
    courseButton.textContent = "Generating";
    courseButton.disabled = true;
    const response = await fetch(`/api/tasks/${courseButton.dataset.course}/course-data`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ force: true }),
    });
    if (!response.ok) {
      const error = await response.json();
      alert(error.detail || "Course generation failed.");
    }
    await loadTasks();
    return;
  }
  const landingButton = event.target.closest("[data-landing]");
  if (landingButton) {
    landingButton.textContent = "Generating";
    landingButton.disabled = true;
    const body = new FormData();
    body.append("force", "true");
    body.append("use_demo_prompt", useDemoPrompt.checked ? "true" : "false");
    body.append("landing_vibe", landingVibe.value);
    if (landingPromptFile.files.length) {
      body.append("prompt_file", landingPromptFile.files[0]);
    }
    const response = await fetch(`/api/tasks/${landingButton.dataset.landing}/landing-page`, {
      method: "POST",
      body,
    });
    if (!response.ok) {
      const error = await response.json();
      alert(error.detail || "Landing page generation failed.");
    }
    await loadTasks();
  }
});

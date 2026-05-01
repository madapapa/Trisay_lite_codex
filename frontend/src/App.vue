<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import {
  CheckCircle2,
  Copy,
  Download,
  FileAudio,
  FileText,
  Mic,
  Moon,
  Palette,
  Pause,
  Play,
  Settings,
  Square,
  Sun,
  Trash2,
  Upload,
  X
} from "lucide-vue-next";

type LanguageCode = "auto" | "zh" | "id";
type AppView = "dashboard" | "settings";
type ModelTab = "catalog" | "local";
type SessionStatus = "idle" | "recording" | "paused" | "processing" | "completed" | "error";
type ModelStatus = "idle" | "queued" | "downloading" | "completed" | "error";

interface TranscriptionMetrics {
  processing_seconds?: number | null;
  segment_count?: number;
  kept_segment_count?: number;
  confidence?: number | null;
  avg_logprob?: number | null;
  avg_compression_ratio?: number | null;
  avg_no_speech_prob?: number | null;
}

interface UploadResponse {
  session_id: string;
  language: LanguageCode;
  status: SessionStatus;
  transcript: string;
  filename: string;
  metrics?: TranscriptionMetrics | null;
  error?: string;
}

interface SessionSummary {
  id: string;
  title: string;
  language: LanguageCode;
  status: SessionStatus;
  source: string;
  filename: string | null;
  created_at: string;
  updated_at: string;
}

interface SessionsResponse {
  items: SessionSummary[];
}

interface SessionDetail extends SessionSummary {
  transcript: string;
  metrics?: TranscriptionMetrics | null;
  error?: string | null;
}

interface ModelDownloadJob {
  model_id: string;
  status: ModelStatus;
  progress: number;
  downloaded_bytes: number;
  total_bytes: number;
  current_file?: string | null;
  message?: string | null;
  started_at: number;
  updated_at: number;
}

interface ModelItem {
  id: string;
  name: string;
  repo_id: string;
  huggingface_url: string;
  description: string;
  recommended_on_apple_silicon: boolean;
  local_dir: string;
  installed: boolean;
  selected: boolean;
  recommended: boolean;
  download_job?: ModelDownloadJob | null;
}

interface ModelEntry {
  id: string;
  name: string;
  description: string;
  installed: boolean;
  selected: boolean;
  recommended?: boolean;
  local_dir: string;
  huggingface_url?: string | null;
  download_job?: ModelDownloadJob | null;
  source?: string;
}

interface MachineInfo {
  system: string;
  machine: string;
  apple_silicon: boolean;
  recommended_family: string;
}

interface ModelsResponse {
  machine: MachineInfo;
  selected_model_id: string | null;
  models: ModelItem[];
  downloads: ModelDownloadJob[];
}

interface LocalModelsResponse {
  selected_model_id: string | null;
  models: ModelEntry[];
}

const API_BASE = "http://127.0.0.1:8000";
const WS_BASE = API_BASE.replace(/^http/, "ws");

const currentView = ref<AppView>("dashboard");
const modelTab = ref<ModelTab>("catalog");
const language = ref<LanguageCode>("auto");
const theme = ref<"light" | "dark">("light");
const status = ref<SessionStatus>("idle");
const transcript = ref("");
const currentSessionId = ref<string | null>(null);
const currentFileName = ref("");
const elapsedSeconds = ref(0);
const uploadError = ref("");
const isExportOpen = ref(false);
const toastMessage = ref("");
const mediaRecorder = ref<MediaRecorder | null>(null);
const liveSocket = ref<WebSocket | null>(null);
const liveAudioChunks = ref<Blob[]>([]);
const isLiveTranscribing = ref(false);
const timerId = ref<number | null>(null);
const recentSessions = ref<SessionSummary[]>([]);
const sessionsError = ref("");
const isLoadingSessions = ref(false);
const transcriptionMetrics = ref<TranscriptionMetrics | null>(null);
const modelItems = ref<ModelItem[]>([]);
const localModelItems = ref<ModelEntry[]>([]);
const machineInfo = ref<MachineInfo | null>(null);
const selectedModelId = ref<string | null>("");
const modelsError = ref("");
const isLoadingModels = ref(false);
const modelRefreshTimer = ref<number | null>(null);
const localModelUploadInput = ref<HTMLInputElement | null>(null);
const isImportingLocalModel = ref(false);
const localImportProgress = ref(0);
const localImportStatus = ref("");

const languageLabel = computed(() => {
  const labels: Record<LanguageCode, string> = {
    auto: "Auto",
    zh: "Mandarin",
    id: "Bahasa Indonesia"
  };
  return labels[language.value];
});
const languageBadge = computed(() => {
  const labels: Record<LanguageCode, string> = {
    auto: "AUTO",
    zh: "ZH",
    id: "ID"
  };
  return labels[language.value];
});
const formattedDuration = computed(() => {
  const hours = Math.floor(elapsedSeconds.value / 3600);
  const minutes = Math.floor((elapsedSeconds.value % 3600) / 60);
  const seconds = elapsedSeconds.value % 60;
  return [hours, minutes, seconds].map((value) => String(value).padStart(2, "0")).join(":");
});
const statusLabel = computed(() => {
  const labels: Record<SessionStatus, string> = {
    idle: "Ready",
    recording: "Recording in progress...",
    paused: "Paused",
    processing: "Processing audio...",
    completed: "Completed",
    error: "Error"
  };
  return labels[status.value];
});
const canCopyOrExport = computed(() => transcript.value.trim().length > 0);
const activeSessionTitle = computed(() => currentFileName.value || "Today's Meeting");
const liveSessions = computed(() => recentSessions.value.filter((item) => item.source === "live"));
const mediaSessions = computed(() => recentSessions.value.filter((item) => item.source !== "live"));
const formattedProcessingTime = computed(() => {
  const seconds = transcriptionMetrics.value?.processing_seconds;
  if (typeof seconds !== "number") return "--";

  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = Math.round(seconds % 60);
  return minutes > 0 ? `${minutes}m ${String(remainingSeconds).padStart(2, "0")}s` : `${remainingSeconds}s`;
});
const formattedConfidence = computed(() => {
  const confidence = transcriptionMetrics.value?.confidence;
  if (typeof confidence !== "number") return "--";
  return `${(confidence * 100).toFixed(1)}%`;
});
const metricsTooltip = computed(() => {
  const metrics = transcriptionMetrics.value;
  if (!metrics) return "Model metrics are available after upload transcription completes.";

  return [
    typeof metrics.avg_logprob === "number" ? `avg_logprob ${metrics.avg_logprob.toFixed(3)}` : null,
    typeof metrics.avg_compression_ratio === "number" ? `compression ${metrics.avg_compression_ratio.toFixed(2)}` : null,
    typeof metrics.avg_no_speech_prob === "number" ? `no_speech ${metrics.avg_no_speech_prob.toExponential(2)}` : null,
    typeof metrics.kept_segment_count === "number" && typeof metrics.segment_count === "number"
      ? `segments ${metrics.kept_segment_count}/${metrics.segment_count}`
      : null
  ]
    .filter(Boolean)
    .join(" · ");
});
const modelRecommendationText = computed(() => {
  if (!machineInfo.value) return "Loading machine info...";
  if (machineInfo.value.apple_silicon) {
    return `Apple Silicon detected (${machineInfo.value.machine}). MLX models are recommended.`;
  }
  return `This machine is ${machineInfo.value.machine}. MLX models are designed for Apple Silicon.`;
});
const activeModel = computed(() => modelItems.value.find((model) => model.selected) || null);
const anyModelDownloading = computed(() => modelItems.value.some((model) => model.download_job?.status === "queued" || model.download_job?.status === "downloading"));
const visibleModels = computed(() => (modelTab.value === "catalog" ? modelItems.value : localModelItems.value));

function showToast(message: string) {
  toastMessage.value = message;
  window.setTimeout(() => {
    toastMessage.value = "";
  }, 1800);
}

function startTimer() {
  if (timerId.value !== null) return;
  timerId.value = window.setInterval(() => {
    elapsedSeconds.value += 1;
  }, 1000);
}

function stopTimer() {
  if (timerId.value === null) return;
  window.clearInterval(timerId.value);
  timerId.value = null;
}

function formatSessionDate(value: string) {
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit"
  }).format(new Date(value));
}

async function loadSessions() {
  isLoadingSessions.value = true;
  sessionsError.value = "";
  try {
    const response = await fetch(`${API_BASE}/sessions`);
    if (!response.ok) {
      throw new Error("Unable to load history.");
    }
    const data = (await response.json()) as SessionsResponse;
    recentSessions.value = data.items;
  } catch (error) {
    sessionsError.value = error instanceof Error ? error.message : "Unable to load history.";
  } finally {
    isLoadingSessions.value = false;
  }
}

async function loadModels() {
  isLoadingModels.value = true;
  modelsError.value = "";
  try {
    const response = await fetch(`${API_BASE}/models`);
    if (!response.ok) {
      throw new Error("Unable to load models.");
    }
    const data = (await response.json()) as ModelsResponse;
    machineInfo.value = data.machine;
    selectedModelId.value = data.selected_model_id;
    modelItems.value = data.models;
  } catch (error) {
    modelsError.value = error instanceof Error ? error.message : "Unable to load models.";
  } finally {
    isLoadingModels.value = false;
    refreshModelPolling();
  }
}

async function refreshCurrentModelTab() {
  if (modelTab.value === "catalog") {
    await loadModels();
  } else {
    await loadLocalModels();
  }
}

async function loadLocalModels() {
  isLoadingModels.value = true;
  modelsError.value = "";
  try {
    const response = await fetch(`${API_BASE}/models/local`);
    if (!response.ok) {
      throw new Error("Unable to load local models.");
    }
    const data = (await response.json()) as LocalModelsResponse;
    selectedModelId.value = data.selected_model_id;
    localModelItems.value = data.models;
  } catch (error) {
    modelsError.value = error instanceof Error ? error.message : "Unable to load local models.";
  } finally {
    isLoadingModels.value = false;
  }
}

async function downloadModel(model: ModelEntry) {
  modelsError.value = "";
  try {
    const response = await fetch(`${API_BASE}/models/${model.id}/download`, { method: "POST" });
    if (!response.ok) {
      throw new Error("Unable to start model download.");
    }
    await loadModels();
  } catch (error) {
    modelsError.value = error instanceof Error ? error.message : "Unable to start model download.";
  }
}

async function startModel(model: ModelEntry) {
  modelsError.value = "";
  if (selectedModelId.value && selectedModelId.value !== model.id) {
    window.alert("Please stop the currently selected model before starting another model.");
    return;
  }

  try {
    const response = await fetch(`${API_BASE}/models/${model.id}/select`, { method: "POST" });
    if (!response.ok) {
      const detail = await response.json().catch(() => null);
      throw new Error(detail?.detail || "Unable to select model.");
    }
    selectedModelId.value = model.id;
    await refreshCurrentModelTab();
    showToast(`Started ${model.name}`);
  } catch (error) {
    modelsError.value = error instanceof Error ? error.message : "Unable to start model.";
  }
}

async function stopModel(model: ModelEntry) {
  modelsError.value = "";
  try {
    const response = await fetch(`${API_BASE}/models/${model.id}/stop`, { method: "POST" });
    if (!response.ok) {
      throw new Error("Unable to stop model.");
    }
    selectedModelId.value = null;
    await refreshCurrentModelTab();
    showToast(`Stopped ${model.name}`);
  } catch (error) {
    modelsError.value = error instanceof Error ? error.message : "Unable to stop model.";
  }
}

async function deleteModel(model: ModelEntry) {
  const confirmed = window.confirm(`Delete the local files for "${model.name}"?`);
  if (!confirmed) return;

  modelsError.value = "";
  try {
    const response = await fetch(`${API_BASE}/models/${model.id}`, { method: "DELETE" });
    if (!response.ok) {
      throw new Error("Unable to delete model.");
    }
    if (selectedModelId.value === model.id) {
      selectedModelId.value = "";
    }
    await refreshCurrentModelTab();
    showToast("Model deleted");
  } catch (error) {
    modelsError.value = error instanceof Error ? error.message : "Unable to delete model.";
  }
}

async function importLocalModel(event: Event) {
  const input = event.target as HTMLInputElement;
  const files = Array.from(input.files || []);
  if (!files.length) return;

  const firstPath = files[0].webkitRelativePath || files[0].name;
  const modelId = firstPath.split("/")[0] || files[0].name;
  const body = new FormData();
  body.append("model_id", modelId);
  for (const file of files) {
    const relativePath = file.webkitRelativePath || file.name;
    const rel = relativePath.split("/").slice(1).join("/");
    body.append("files", file, rel || file.name);
  }

  modelsError.value = "";
  isImportingLocalModel.value = true;
  localImportProgress.value = 0;
  localImportStatus.value = `Importing ${modelId}`;
  try {
    await new Promise<void>((resolve, reject) => {
      const request = new XMLHttpRequest();
      request.open("POST", `${API_BASE}/models/local/import`);

      request.upload.onprogress = (progressEvent) => {
        if (!progressEvent.lengthComputable) {
          localImportStatus.value = `Importing ${modelId}`;
          return;
        }
        localImportProgress.value = Math.min(99, Math.round((progressEvent.loaded / progressEvent.total) * 100));
      };

      request.onload = () => {
        if (request.status >= 200 && request.status < 300) {
          localImportProgress.value = 100;
          resolve();
          return;
        }
        try {
          const payload = JSON.parse(request.responseText) as { detail?: string };
          reject(new Error(payload.detail || "Unable to import local model."));
        } catch {
          reject(new Error("Unable to import local model."));
        }
      };

      request.onerror = () => reject(new Error("Unable to import local model."));
      request.send(body);
    });
    await loadLocalModels();
    showToast("Local model imported");
  } catch (error) {
    modelsError.value = error instanceof Error ? error.message : "Unable to import local model.";
  } finally {
    isImportingLocalModel.value = false;
    window.setTimeout(() => {
      localImportProgress.value = 0;
      localImportStatus.value = "";
    }, 1200);
    input.value = "";
  }
}

function refreshModelPolling() {
  if (modelRefreshTimer.value !== null) {
    window.clearInterval(modelRefreshTimer.value);
    modelRefreshTimer.value = null;
  }
  if (anyModelDownloading.value) {
    modelRefreshTimer.value = window.setInterval(() => {
      void loadModels();
    }, 2000);
  }
}

function switchModelTab(tab: ModelTab) {
  modelTab.value = tab;
  if (tab === "catalog") {
    void loadModels();
  } else {
    void loadLocalModels();
  }
}

async function openSession(sessionId: string) {
  stopRecording();
  uploadError.value = "";
  try {
    const response = await fetch(`${API_BASE}/sessions/${sessionId}`);
    if (!response.ok) {
      throw new Error("Unable to open transcript.");
    }
    const data = (await response.json()) as SessionDetail;
    currentView.value = "dashboard";
    currentSessionId.value = data.id;
    currentFileName.value = data.filename || data.title;
    language.value = data.language;
    status.value = data.status;
    transcript.value = data.transcript || data.error || "(No transcript text saved)";
    transcriptionMetrics.value = data.metrics || null;
    elapsedSeconds.value = 0;
  } catch (error) {
    uploadError.value = error instanceof Error ? error.message : "Unable to open transcript.";
    status.value = "error";
  }
}

async function deleteSession(session: SessionSummary) {
  const name = session.filename || session.title;
  const confirmed = window.confirm(`Delete "${name}" from history and remove its saved audio/transcript files?`);
  if (!confirmed) return;

  if (currentSessionId.value === session.id && (status.value === "recording" || status.value === "paused")) {
    stopRecording();
  }

  try {
    const response = await fetch(`${API_BASE}/sessions/${session.id}`, {
      method: "DELETE"
    });
    if (!response.ok) {
      throw new Error("Unable to delete transcript.");
    }

    if (currentSessionId.value === session.id) {
      transcript.value = "";
      transcriptionMetrics.value = null;
      currentSessionId.value = null;
      currentFileName.value = "";
      elapsedSeconds.value = 0;
      status.value = "idle";
    }

    await loadSessions();
    showToast("Transcript deleted");
  } catch (error) {
    sessionsError.value = error instanceof Error ? error.message : "Unable to delete transcript.";
  }
}

async function startRecording() {
  uploadError.value = "";
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const socket = new WebSocket(`${WS_BASE}/transcriptions/live?language=${language.value}`);
    liveSocket.value = socket;

    socket.addEventListener("open", () => {
      const recorder = new MediaRecorder(stream);
      mediaRecorder.value = recorder;
      liveAudioChunks.value = [];
      isLiveTranscribing.value = false;
      transcript.value = "";
      transcriptionMetrics.value = null;
      currentSessionId.value = null;
      currentFileName.value = "Live transcription";
      elapsedSeconds.value = 0;
      status.value = "recording";

      recorder.addEventListener("dataavailable", async (event) => {
        if (event.data.size === 0 || socket.readyState !== WebSocket.OPEN) return;
        liveAudioChunks.value.push(event.data);
        if (isLiveTranscribing.value) return;

        isLiveTranscribing.value = true;
        const snapshot = new Blob(liveAudioChunks.value, { type: recorder.mimeType || event.data.type });
        socket.send(await snapshot.arrayBuffer());
      });

      recorder.start(5000);
      startTimer();
    });

    socket.addEventListener("message", (event) => {
      const payload = JSON.parse(event.data) as { type: string; session_id?: string; text?: string; message?: string };
      if (payload.type === "session_started" && payload.session_id) {
        currentSessionId.value = payload.session_id;
      }
      if (payload.type === "transcript" && payload.text) {
        transcript.value = payload.text;
        isLiveTranscribing.value = false;
      }
      if (payload.type === "silence" || payload.type === "unchanged") {
        isLiveTranscribing.value = false;
      }
      if (payload.type === "error") {
        uploadError.value = payload.message || "Live transcription failed for this audio chunk.";
        isLiveTranscribing.value = false;
      }
    });

    socket.addEventListener("close", () => {
      liveSocket.value = null;
      liveAudioChunks.value = [];
      isLiveTranscribing.value = false;
      void loadSessions();
    });

    socket.addEventListener("error", () => {
      status.value = "error";
      uploadError.value = "Live transcription connection failed.";
      isLiveTranscribing.value = false;
      stream.getTracks().forEach((track) => track.stop());
      stopTimer();
    });
  } catch (error) {
    status.value = "error";
    uploadError.value = error instanceof Error ? error.message : "Microphone permission was denied.";
  }
}

function pauseRecording() {
  if (status.value === "recording") {
    mediaRecorder.value?.pause();
    status.value = "paused";
    stopTimer();
    return;
  }
  if (status.value === "paused") {
    mediaRecorder.value?.resume();
    status.value = "recording";
    startTimer();
  }
}

function stopRecording() {
  mediaRecorder.value?.stop();
  mediaRecorder.value?.stream.getTracks().forEach((track) => track.stop());
  mediaRecorder.value = null;
  liveSocket.value?.close();
  liveSocket.value = null;
  liveAudioChunks.value = [];
  isLiveTranscribing.value = false;
  stopTimer();
  status.value = transcript.value ? "completed" : "idle";
  window.setTimeout(() => {
    void loadSessions();
  }, 500);
}

function newSession() {
  stopRecording();
  status.value = "idle";
  transcript.value = "";
  transcriptionMetrics.value = null;
  currentSessionId.value = null;
  currentFileName.value = "";
  elapsedSeconds.value = 0;
  uploadError.value = "";
}

async function uploadAudio(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  if (!file) return;

  status.value = "processing";
  uploadError.value = "";
  transcriptionMetrics.value = null;
  currentFileName.value = file.name;

  const body = new FormData();
  body.append("file", file);
  body.append("language", language.value);

  try {
    const response = await fetch(`${API_BASE}/transcriptions/upload`, {
      method: "POST",
      body
    });
    const data = (await response.json()) as UploadResponse;
    if (!response.ok || data.status === "error") {
      throw new Error(data.error || "Upload transcription failed.");
    }
    currentSessionId.value = data.session_id;
    transcript.value = data.transcript || "(No speech detected)";
    status.value = data.status;
    transcriptionMetrics.value = data.metrics || null;
    await loadSessions();
    showToast("Transcription completed");
  } catch (error) {
    status.value = "error";
    uploadError.value = error instanceof Error ? error.message : "Upload failed.";
  } finally {
    input.value = "";
  }
}

async function copyTranscript() {
  if (!canCopyOrExport.value) return;
  await navigator.clipboard.writeText(transcript.value);
  showToast("Copied to clipboard");
}

async function downloadMarkdown() {
  if (!canCopyOrExport.value) return;

  if (currentSessionId.value) {
    const response = await fetch(`${API_BASE}/exports/markdown/${currentSessionId.value}`);
    if (response.ok) {
      const blob = await response.blob();
      triggerDownload(blob, `${currentFileName.value || "trisay-transcript"}.md`);
      isExportOpen.value = false;
      return;
    }
  }

  const markdown = `# Trisay Lite Transcript\n\nLanguage: ${languageLabel.value}\n\n${transcript.value}\n`;
  triggerDownload(new Blob([markdown], { type: "text/markdown;charset=utf-8" }), "trisay-transcript.md");
  isExportOpen.value = false;
}

function triggerDownload(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

onMounted(() => {
  void loadSessions();
  void loadModels();
  void loadLocalModels();
  refreshModelPolling();
});

onUnmounted(() => {
  if (modelRefreshTimer.value !== null) {
    window.clearInterval(modelRefreshTimer.value);
  }
});
</script>

<template>
  <div class="app-shell" :class="{ 'dark-mode': theme === 'dark' }">
    <header class="topbar">
      <div class="brand">Trisay Lite</div>
      <nav class="topnav" aria-label="Main navigation">
        <button :class="{ active: currentView === 'dashboard' }" @click="currentView = 'dashboard'">Dashboard</button>
        <button :class="{ active: currentView === 'settings' }" @click="currentView = 'settings'">Settings</button>
      </nav>
      <div class="top-actions">
        <div class="segmented" aria-label="Transcription language">
          <button :class="{ selected: language === 'auto' }" @click="language = 'auto'">Auto</button>
          <button :class="{ selected: language === 'zh' }" @click="language = 'zh'">Mandarin</button>
          <button :class="{ selected: language === 'id' }" @click="language = 'id'">Bahasa Indonesia</button>
        </div>
        <button class="icon-button" :title="theme === 'light' ? 'Switch to dark' : 'Switch to light'" @click="theme = theme === 'light' ? 'dark' : 'light'">
          <Sun v-if="theme === 'light'" :size="20" />
          <Moon v-else :size="20" />
        </button>
        <button class="primary-button" @click="newSession">New Session</button>
      </div>
    </header>

    <aside class="sidebar">
      <div class="sidebar-title">
        <h2>Recent Transcripts</h2>
        <p>{{ isLoadingSessions ? "Loading..." : "Last 30 sessions" }}</p>
      </div>
      <section class="sidebar-directory" aria-label="Live Transcription">
        <div class="directory-heading">
          <span>Live Transcription</span>
          <small>{{ liveSessions.length + 1 }}</small>
        </div>
        <button class="side-item directory-item" :class="{ active: !currentSessionId }" @click="currentView = 'dashboard'">
          <FileText :size="20" />
          <span>{{ activeSessionTitle }}</span>
        </button>
        <div
          v-for="item in liveSessions"
          :key="item.id"
          class="side-item directory-item history-item"
          :class="{ active: currentSessionId === item.id }"
          role="button"
          tabindex="0"
          @click="openSession(item.id)"
          @keydown.enter="openSession(item.id)"
        >
          <FileText :size="20" />
          <span>
            <strong>{{ item.filename || item.title }}</strong>
            <small>{{ item.status }} · {{ formatSessionDate(item.created_at) }}</small>
          </span>
          <button class="delete-history-button" title="Delete transcript" @click.stop="deleteSession(item)">
            <Trash2 :size="16" />
          </button>
        </div>
      </section>

      <section class="sidebar-directory" aria-label="Upload Media">
        <div class="directory-heading">
          <span>Upload Media</span>
          <small>{{ mediaSessions.length }}</small>
        </div>
        <label class="side-item directory-item upload-item">
          <FileAudio :size="20" />
          <span>Upload Media</span>
          <input type="file" accept="audio/*,video/*" @change="uploadAudio" />
        </label>
        <div
          v-for="item in mediaSessions"
          :key="item.id"
          class="side-item directory-item history-item"
          :class="{ active: currentSessionId === item.id }"
          role="button"
          tabindex="0"
          @click="openSession(item.id)"
          @keydown.enter="openSession(item.id)"
        >
          <FileAudio :size="20" />
          <span>
            <strong>{{ item.filename || item.title }}</strong>
            <small>{{ item.status }} · {{ formatSessionDate(item.created_at) }}</small>
          </span>
          <button class="delete-history-button" title="Delete transcript" @click.stop="deleteSession(item)">
            <Trash2 :size="16" />
          </button>
        </div>
      </section>
      <p v-if="sessionsError" class="sidebar-error">{{ sessionsError }}</p>
      <button class="history-button" @click="loadSessions">Refresh History</button>
    </aside>

    <main class="main-area">
      <section v-if="currentView === 'dashboard'" class="dashboard">
        <div class="status-row">
          <div class="status-copy">
            <span class="status-dot" :class="status"></span>
            <strong>{{ statusLabel }}</strong>
            <span>{{ formattedDuration }}</span>
          </div>
          <div class="mobile-language">{{ languageBadge }}</div>
        </div>

        <section class="transcript-card">
          <div class="card-toolbar">
            <div class="control-group">
              <button class="primary-button start-button" :disabled="status === 'recording' || status === 'processing'" @click="startRecording">
                <Play :size="18" />
                Start Transcription
              </button>
              <button class="secondary-button pause-button" :disabled="status === 'idle' || status === 'processing' || status === 'completed'" @click="pauseRecording">
                <Pause v-if="status === 'recording'" :size="18" />
                <Play v-else :size="18" />
                {{ status === "paused" ? "Resume" : "Pause" }}
              </button>
              <button class="danger-button stop-button" :disabled="status !== 'recording' && status !== 'paused'" @click="stopRecording">
                <Square :size="16" />
                Stop
              </button>
              <div class="metrics-panel" :title="metricsTooltip" aria-label="Media Info">
                <span class="metrics-title">Media Info</span>
                <span class="metric-chip">
                  <span class="metric-label">Confidence</span>
                  <strong class="metric-value">{{ formattedConfidence }}</strong>
                </span>
                <span class="metric-chip">
                  <span class="metric-label">Process time</span>
                  <strong class="metric-value">{{ formattedProcessingTime }}</strong>
                </span>
              </div>
            </div>
            <div class="icon-group">
              <button class="icon-button" title="Copy text" :disabled="!canCopyOrExport" @click="copyTranscript">
                <Copy :size="20" />
              </button>
              <button class="icon-button" title="Export markdown" :disabled="!canCopyOrExport" @click="isExportOpen = true">
                <Download :size="20" />
              </button>
            </div>
          </div>

          <div class="upload-strip">
            <label class="upload-button">
              <Upload :size="18" />
              Upload audio
              <input type="file" accept="audio/*,video/*" @change="uploadAudio" />
            </label>
            <span>{{ currentFileName || "Supports local audio or video files" }}</span>
          </div>

          <p v-if="uploadError" class="error-message">{{ uploadError }}</p>

          <article class="transcript-content">
            <template v-if="transcript">
              <p v-for="(line, index) in transcript.split('\n').filter(Boolean)" :key="index">{{ line }}</p>
            </template>
            <div v-else class="empty-state">
              <Mic :size="42" />
              <h1>Ready for local transcription</h1>
              <p>Choose Auto for mixed-language audio, then start recording or upload an audio file.</p>
            </div>
          </article>
        </section>
      </section>

      <section v-else class="settings-page">
        <div class="page-heading">
          <h1>Settings</h1>
          <p>Manage transcription language and appearance preferences.</p>
        </div>

        <section class="settings-card">
          <h2><Settings :size="24" /> Language</h2>
          <p>Select your primary language for transcription.</p>
          <label class="radio-row" :class="{ checked: language === 'auto' }">
            <span class="language-avatar">AUTO</span>
            <span>Auto detect</span>
            <input v-model="language" type="radio" value="auto" />
          </label>
          <label class="radio-row" :class="{ checked: language === 'zh' }">
            <span class="language-avatar">ZH</span>
            <span>Mandarin</span>
            <input v-model="language" type="radio" value="zh" />
          </label>
          <label class="radio-row" :class="{ checked: language === 'id' }">
            <span class="language-avatar">ID</span>
            <span>Bahasa Indonesia</span>
            <input v-model="language" type="radio" value="id" />
          </label>
        </section>

        <section class="settings-card">
          <h2><Download :size="24" /> Model Management</h2>
          <p>{{ modelRecommendationText }}</p>
          <div class="model-machine-line" v-if="machineInfo">
            <span>System: {{ machineInfo.system }}</span>
            <span>Chip: {{ machineInfo.machine }}</span>
            <span v-if="machineInfo.apple_silicon">Apple Silicon ready</span>
          </div>
          <p v-if="modelsError" class="sidebar-error">{{ modelsError }}</p>
          <div class="model-tabs" role="tablist" aria-label="Model sources">
            <button class="model-tab" :class="{ active: modelTab === 'catalog' }" @click="switchModelTab('catalog')">
              Catalog
            </button>
            <button class="model-tab" :class="{ active: modelTab === 'local' }" @click="switchModelTab('local')">
              Local
            </button>
          </div>
          <p v-if="modelTab === 'catalog' && anyModelDownloading" class="model-progress-note">Download in progress. The list refreshes automatically.</p>
          <p v-if="modelTab === 'local'" class="model-progress-note">Choose a local model folder. The browser will ask for permission, then Trisay Lite imports it into the local model library.</p>
          <div class="model-list">
            <article v-for="model in visibleModels" :key="model.id" class="model-row" :class="{ selected: model.selected }">
              <div class="model-row-main">
                <div class="model-row-heading">
                  <strong>{{ model.name }}</strong>
                  <span v-if="model.recommended" class="model-badge">Recommended</span>
                  <span v-if="model.installed" class="model-badge installed">Installed</span>
                  <span v-if="model.selected" class="model-badge selected">Selected</span>
                </div>
                <p>{{ model.description }}</p>
                <div v-if="modelTab === 'catalog' && model.download_job && (model.download_job.status === 'queued' || model.download_job.status === 'downloading')" class="model-progress">
                  <div class="model-progress-bar">
                    <span :style="{ width: `${Math.max(3, model.download_job.progress)}%` }"></span>
                  </div>
                  <small>
                    {{ model.download_job.current_file || "Preparing download" }}
                    <template v-if="model.download_job.total_bytes > 0">
                      · {{ model.download_job.progress.toFixed(0) }}%
                    </template>
                  </small>
                </div>
                <div v-if="modelTab === 'catalog' && model.download_job?.status === 'error'" class="model-download-error">
                  <strong>Download failed</strong>
                  <span>{{ model.download_job.message || "Unable to download this model." }}</span>
                </div>
                <a v-if="modelTab === 'catalog'" class="model-link" :href="model.huggingface_url || undefined" target="_blank" rel="noreferrer">Hugging Face download page</a>
              </div>
              <div class="model-row-actions">
                <button v-if="modelTab === 'catalog' && !model.installed" class="secondary-button" :disabled="model.download_job?.status === 'queued' || model.download_job?.status === 'downloading'" @click="downloadModel(model)">
                  {{ model.download_job?.status === "error" ? "Retry download" : "Download" }}
                </button>
                <button v-if="model.installed" class="primary-button" :disabled="model.selected" @click="startModel(model)">
                  Start
                </button>
                <button v-if="model.installed" class="secondary-button" :disabled="!model.selected" @click="stopModel(model)">
                  Stop
                </button>
                <button v-if="model.installed" class="danger-button" @click="deleteModel(model)">
                  Delete
                </button>
              </div>
            </article>
          </div>
          <label v-if="modelTab === 'local' && !isImportingLocalModel" class="upload-button model-import-button">
            Choose local model folder
            <input ref="localModelUploadInput" type="file" webkitdirectory directory multiple @change="importLocalModel" />
          </label>
          <div v-if="modelTab === 'local' && (isImportingLocalModel || localImportStatus)" class="model-progress local-import-progress">
            <div class="model-progress-bar">
              <span :style="{ width: `${Math.max(3, localImportProgress)}%` }"></span>
            </div>
            <small>{{ localImportStatus || "Import complete" }} · {{ localImportProgress }}%</small>
          </div>
          <p v-if="isLoadingModels">Loading models...</p>
        </section>

        <section class="settings-card">
          <h2><Palette :size="24" /> Appearance</h2>
          <div class="theme-grid">
            <button class="theme-option" :class="{ checked: theme === 'light' }" @click="theme = 'light'">
              <Sun :size="20" />
              Light
            </button>
            <button class="theme-option dark-preview" :class="{ checked: theme === 'dark' }" @click="theme = 'dark'">
              <Moon :size="20" />
              Dark
            </button>
          </div>
        </section>
      </section>
    </main>

    <div v-if="isExportOpen" class="modal-backdrop">
      <section class="modal-card" role="dialog" aria-modal="true" aria-labelledby="export-title">
        <header>
          <h2 id="export-title">Export to Markdown</h2>
          <button class="icon-button" aria-label="Close" @click="isExportOpen = false">
            <X :size="20" />
          </button>
        </header>
        <p>Download the current transcript as a Markdown file.</p>
        <div class="export-option checked">
          <CheckCircle2 :size="20" />
          <div>
            <strong>Export Full Transcript</strong>
            <span>Includes spoken content and current language metadata.</span>
          </div>
        </div>
        <footer>
          <button class="secondary-button" @click="isExportOpen = false">Cancel</button>
          <button class="primary-button" @click="downloadMarkdown">
            <Download :size="18" />
            Download .md
          </button>
        </footer>
      </section>
    </div>

    <div v-if="toastMessage" class="toast">
      <CheckCircle2 :size="20" />
      {{ toastMessage }}
    </div>
  </div>
</template>

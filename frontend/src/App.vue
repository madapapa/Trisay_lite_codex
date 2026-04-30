<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
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
type SessionStatus = "idle" | "recording" | "paused" | "processing" | "completed" | "error";

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

const API_BASE = "http://127.0.0.1:8000";
const WS_BASE = API_BASE.replace(/^http/, "ws");

const currentView = ref<AppView>("dashboard");
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

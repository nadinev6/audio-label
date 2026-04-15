import LabelStudio from '@heartexlabs/label-studio';
import '@heartexlabs/label-studio/build/static/css/main.css';
import { initAuth, getAccessToken } from './auth.js';

const EXPORT_VERSION = 1;
const SESSION_KEY = 'audio-label-index';

const LABEL_CONFIG = `
  <View>
    <AudioPlus name="audio" value="$audio"/>
    <Labels name="label" toName="audio">
      <Label value="Speech"/>
      <Label value="Noise"/>
    </Labels>
  </View>
`;

const LS_OPTIONS = {
  config: LABEL_CONFIG,
  interfaces: ['controls', 'submit'],
};

function onLabelStudioLoad(LS) {
  const created = LS.annotationStore.addAnnotation({ userGenerate: true });
  LS.annotationStore.selectAnnotation(created.id);
}

let tasks = [];
let index = 0;
let studio = null;
let completedTaskIds = new Set();

function setStatus(text, isError = false) {
  const el = document.getElementById('status');
  el.textContent = text;
  el.style.color = isError ? '#c0392b' : '#666666';
}

function showBanner(text, isError = false) {
  const banner = document.getElementById('save-banner');
  banner.textContent = text;
  banner.style.background = isError ? '#fff0f0' : '#f0faf4';
  banner.style.color = isError ? '#c0392b' : '#1a7a3a';
  banner.style.borderColor = isError ? '#c0392b' : '#1a7a3a';
  banner.style.opacity = '1';
  clearTimeout(banner._timer);
  banner._timer = setTimeout(() => {
    banner.style.opacity = '0';
  }, 3000);
}

function updateProgressBar() {
  const count = completedTaskIds.size;
  const total = tasks.length;
  const pct = total > 0 ? Math.round((count / total) * 100) : 0;
  document.getElementById('progress-text').textContent = `${count} / ${total} annotated`;
  document.getElementById('progress-fill').style.width = `${pct}%`;
}

function taskMetaLine(task) {
  if (!task) return '';
  const done = completedTaskIds.has(task.id);
  const checkmark = done ? ' ✓' : '';
  const parts = [`${index + 1} / ${tasks.length || 0}`, `id: ${task.id}${checkmark}`];
  if (task.meta && Object.keys(task.meta).length) {
    parts.push(JSON.stringify(task.meta));
  }
  return parts.join(' · ');
}

async function authedFetch(url, options = {}) {
  const token = await getAccessToken();
  const headers = { ...(options.headers ?? {}) };
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }
  return fetch(url, { ...options, headers });
}

async function loadTaskList() {
  try {
    const r = await authedFetch('/api/tasks');
    if (r.ok) {
      const body = await r.json();
      return Array.isArray(body.tasks) ? body.tasks : [];
    }
  } catch {
    // Dev without backend: fall through
  }
  const r = await fetch('/tasks.json');
  if (!r.ok) throw new Error(`tasks unavailable (${r.status})`);
  const body = await r.json();
  return Array.isArray(body.tasks) ? body.tasks : [];
}

async function loadProgress() {
  try {
    const r = await authedFetch('/api/progress');
    if (r.ok) {
      const body = await r.json();
      if (Array.isArray(body.completed_task_ids)) {
        completedTaskIds = new Set(body.completed_task_ids);
      }
    }
  } catch {
    // Progress unavailable; start fresh
  }
}

function mountStudio(task) {
  const root = document.getElementById('root');
  root.replaceChildren();
  if (!task || !task.data?.audio) {
    root.innerHTML =
      '<p style="padding:1rem;color:#666666;font-family:var(--font-mono);">No task or missing <code>data.audio</code> URL.</p>';
    return;
  }
  studio = new LabelStudio('root', {
    ...LS_OPTIONS,
    onLabelStudioLoad,
    task: {
      id: task.id,
      annotations: [],
      predictions: [],
      data: task.data,
      meta: task.meta,
    },
    onSubmitAnnotation: (_ls, annotation) => {
      void persistAnnotation(task, annotation);
    },
  });
}

async function persistAnnotation(task, annotation) {
  const payload = {
    export_version: EXPORT_VERSION,
    task_id: task.id,
    annotation: annotation.serializeAnnotation?.() ?? annotation,
    meta: task.meta ?? {},
  };
  try {
    const r = await authedFetch('/api/annotations', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (r.ok) {
      completedTaskIds.add(task.id);
      updateProgressBar();
      updateChrome();
      showBanner('Saved to database');
      return;
    }
    showBanner(`Save failed: HTTP ${r.status}`, true);
  } catch {
    showBanner('Save failed (is the API running?)', true);
  }
  console.warn('Annotation (copy if needed):', payload);
}

function updateChrome() {
  const task = tasks[index];
  document.getElementById('task-meta').textContent = taskMetaLine(task);
  document.getElementById('btn-prev').disabled = index <= 0;
  document.getElementById('btn-next').disabled = index >= tasks.length - 1;
  document.getElementById('btn-skip').disabled = index >= tasks.length - 1;
  try { sessionStorage.setItem(SESSION_KEY, String(index)); } catch { /* ignore */ }
  mountStudio(task);
}

async function startApp() {
  setStatus('Loading…');
  try {
    [tasks] = await Promise.all([loadTaskList(), loadProgress()]);
  } catch (e) {
    setStatus(e.message || 'Failed to load tasks', true);
    document.getElementById('root').innerHTML = `
      <p style="padding:1rem;max-width:42rem;line-height:1.5;color:#333333;font-family:var(--font-mono);">
        Could not load tasks. Start the API (<code>python -m uvicorn main:app --reload --port 8000</code> from <code>server/</code>)
        or place <code>public/tasks.json</code> for static hosting.
      </p>`;
    return;
  }
  if (tasks.length === 0) {
    setStatus('No tasks', true);
    document.getElementById('root').innerHTML =
      '<p style="padding:1rem;color:#666666;font-family:var(--font-mono);">Add tasks to <code>tasks.json</code> (see README).</p>';
    return;
  }

  const saved = parseInt(sessionStorage.getItem(SESSION_KEY) ?? '', 10);
  if (!isNaN(saved) && saved >= 0 && saved < tasks.length) {
    index = saved;
  } else {
    const firstIncomplete = tasks.findIndex(t => !completedTaskIds.has(t.id));
    index = firstIncomplete === -1 ? 0 : firstIncomplete;
  }

  setStatus('');
  updateProgressBar();
  updateChrome();

  document.getElementById('btn-prev').addEventListener('click', () => {
    index = Math.max(0, index - 1);
    updateChrome();
  });
  document.getElementById('btn-next').addEventListener('click', () => {
    index = Math.min(tasks.length - 1, index + 1);
    updateChrome();
  });
  document.getElementById('btn-skip').addEventListener('click', () => {
    index = Math.min(tasks.length - 1, index + 1);
    updateChrome();
  });
}

initAuth(startApp);

import LabelStudio from '@heartexlabs/label-studio';
import '@heartexlabs/label-studio/build/static/css/main.css';

/** Bump when you change label config shapes that downstream must interpret. */
const EXPORT_VERSION = 1;

/**
 * Edit this XML to match your taxonomy (keep names stable for pipeline joins).
 * @see https://labelstud.io/tags
 */
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

/**
 * Label Studio 1.x expects an empty annotation to be created on load for editing.
 */
function onLabelStudioLoad(LS) {
  const created = LS.annotationStore.addAnnotation({ userGenerate: true });
  LS.annotationStore.selectAnnotation(created.id);
}

let tasks = [];
let index = 0;
let studio = null;

function setStatus(text, isError = false) {
  const el = document.getElementById('status');
  el.textContent = text;
  el.style.color = isError ? '#f85149' : '#8b949e';
}

function taskMetaLine(task) {
  if (!task) return '';
  const parts = [`${index + 1} / ${tasks.length || 0}`, `id: ${task.id}`];
  if (task.meta && Object.keys(task.meta).length) {
    parts.push(JSON.stringify(task.meta));
  }
  return parts.join(' · ');
}

async function loadTaskList() {
  try {
    const r = await fetch('/api/tasks');
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

function mountStudio(task) {
  const root = document.getElementById('root');
  root.replaceChildren();
  if (!task || !task.data?.audio) {
    root.innerHTML =
      '<p style="padding:1rem;color:#8b949e;">No task or missing <code>data.audio</code> URL.</p>';
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
    const r = await fetch('/api/annotations', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (r.ok) {
      setStatus('Saved');
      return;
    }
    setStatus(`Save failed: HTTP ${r.status}`, true);
  } catch {
    setStatus('Save failed (is the API running?)', true);
  }
  // Fallback: still log so work is not silently lost during bring-up
  console.warn('Annotation (copy if needed):', payload);
}

function updateChrome() {
  const task = tasks[index];
  document.getElementById('task-meta').textContent = taskMetaLine(task);
  document.getElementById('btn-prev').disabled = index <= 0;
  document.getElementById('btn-next').disabled = index >= tasks.length - 1;
  mountStudio(task);
}

async function main() {
  setStatus('Loading tasks…');
  try {
    tasks = await loadTaskList();
  } catch (e) {
    setStatus(e.message || 'Failed to load tasks', true);
    document.getElementById('root').innerHTML = `
      <p style="padding:1rem;max-width:42rem;line-height:1.5;color:#e6edf3;">
        Could not load tasks. Start the API (<code>python -m uvicorn main:app --reload --port 8000</code> from <code>server/</code>)
        or place <code>public/tasks.json</code> for static hosting.
      </p>`;
    return;
  }
  if (tasks.length === 0) {
    setStatus('No tasks', true);
    document.getElementById('root').innerHTML =
      '<p style="padding:1rem;color:#8b949e;">Add tasks to <code>tasks.json</code> (see README).</p>';
    return;
  }
  index = 0;
  setStatus('');
  updateChrome();

  document.getElementById('btn-prev').addEventListener('click', () => {
    index = Math.max(0, index - 1);
    updateChrome();
  });
  document.getElementById('btn-next').addEventListener('click', () => {
    index = Math.min(tasks.length - 1, index + 1);
    updateChrome();
  });
}

main();

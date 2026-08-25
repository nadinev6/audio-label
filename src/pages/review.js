import { api } from '../api.js';

let currentTask = null;
let currentProject = null;
let audioEl = null;
let startTime = 0;

export async function renderReview(projectId, project = null) {
  if (!project) {
    const data = await api.projects.get(projectId);
    project = data.project;
  }
  currentProject = project;

  const app = document.getElementById('root');
  app.innerHTML = `
    <div class="review-page">
      <div class="review-topbar">
        <a href="#/projects/${projectId}" class="btn btn-ghost btn-sm">← Dashboard</a>
        <span class="text-muted" id="review-status">Loading next task...</span>
        <div class="review-progress" id="review-progress"></div>
        <button class="btn btn-sm btn-ghost" id="btn-skip-task">Skip</button>
      </div>

      <div class="review-main">
        <div class="review-audio-section">
          <div id="audio-player">
            <p class="text-muted">Loading audio...</p>
          </div>
        </div>

        <div class="review-transcript-section">
          <div class="input-group">
            <label>Model Transcript</label>
            <div id="model-transcript" class="transcript-display"></div>
          </div>

          <div class="input-group" style="flex:1">
            <label>Corrected Transcript</label>
            <textarea id="corrected-transcript" class="transcript-edit" placeholder="Type your corrected transcript here..." rows="5"></textarea>
          </div>

          <div class="input-group" id="labels-section">
            <label>Issue Types</label>
            <div id="label-buttons" class="label-grid"></div>
          </div>

          <div class="input-group">
            <label>Notes (optional)</label>
            <textarea id="review-notes" rows="2" placeholder="Any additional notes about this segment..."></textarea>
          </div>

          <div class="review-actions">
            <button class="btn btn-primary btn-lg" id="btn-submit">Submit Annotation</button>
          </div>
        </div>
      </div>
    </div>
  `;

  loadTask(projectId, project);
}

export async function renderSpecificTask(projectId, taskId) {
  const data = await api.projects.get(projectId);
  const project = data.project;
  currentProject = project;
  const taskData = await api.tasks.get(taskId);
  currentTask = taskData.task;

  const app = document.getElementById('root');
  app.innerHTML = `
    <div class="review-page">
      <div class="review-topbar">
        <a href="#/projects/${projectId}" class="btn btn-ghost btn-sm">← Dashboard</a>
        <span class="text-muted" id="review-status">Task ${taskId.slice(0, 8)}</span>
        <div class="review-progress" id="review-progress"></div>
        <button class="btn btn-sm btn-ghost" id="btn-skip-task">Skip</button>
      </div>

      <div class="review-main">
        <div class="review-audio-section">
          <div id="audio-player">
            <p class="text-muted">Loading audio...</p>
          </div>
        </div>

        <div class="review-transcript-section">
          <div class="input-group">
            <label>Model Transcript</label>
            <div id="model-transcript" class="transcript-display"></div>
          </div>

          <div class="input-group" style="flex:1">
            <label>Corrected Transcript</label>
            <textarea id="corrected-transcript" class="transcript-edit" placeholder="Type your corrected transcript here..." rows="5"></textarea>
          </div>

          <div class="input-group" id="labels-section">
            <label>Issue Types</label>
            <div id="label-buttons" class="label-grid"></div>
          </div>

          <div class="input-group">
            <label>Notes (optional)</label>
            <textarea id="review-notes" rows="2" placeholder="Any additional notes about this segment..."></textarea>
          </div>

          <div class="review-actions">
            <button class="btn btn-primary btn-lg" id="btn-submit">Submit Annotation</button>
          </div>
        </div>
      </div>
    </div>
  `;

  populateTask(currentTask);
}

async function loadTask(projectId, project) {
  try {
    const data = await api.tasks.next(projectId);
    if (!data.task) {
      document.getElementById('audio-player').innerHTML = '<p class="empty-state">No pending tasks. All caught up!</p>';
      document.getElementById('review-status').textContent = 'No tasks available';
      return;
    }
    currentTask = data.task;
    populateTask(currentTask);
  } catch (err) {
    document.getElementById('review-status').textContent = `Error: ${err.message}`;
  }
}

function populateTask(task) {
  const segData = task.segment_data || {};
  const metadata = segData.metadata || {};
  const labels = (currentProject?.label_config?.labels) || [
    { value: 'phonetic_error', title: 'Phonetic error', color: '#e74c3c' },
    { value: 'lexical_substitution', title: 'Lexical substitution', color: '#f39c12' },
    { value: 'pidgin_loss', title: 'Pidgin loss', color: '#9b59b6' },
    { value: 'no_issues', title: 'No issues', color: '#2ecc71' },
  ];

  document.getElementById('review-status').textContent =
    `Type: ${task.task_type} · Language: ${metadata.language || '—'} · Gender: ${metadata.gender || '—'} · Domain: ${metadata.domain || '—'}`;

  const transcript = segData.transcript || '';
  document.getElementById('model-transcript').textContent = transcript;

  document.getElementById('corrected-transcript').value = '';

  const labelGrid = document.getElementById('label-buttons');
  labelGrid.innerHTML = '';
  for (const lbl of labels) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'label-btn';
    btn.dataset.value = lbl.value;
    btn.textContent = lbl.title || lbl.value;
    btn.addEventListener('click', () => btn.classList.toggle('active'));
    labelGrid.appendChild(btn);
  }

  const audioUrl = segData.audio_url || '';
  const playerContainer = document.getElementById('audio-player');
  playerContainer.innerHTML = '';
  if (audioUrl) {
    audioEl = document.createElement('audio');
    audioEl.controls = true;
    audioEl.style.width = '100%';
    audioEl.src = audioUrl;
    playerContainer.appendChild(audioEl);

    const metaDiv = document.createElement('div');
    metaDiv.className = 'audio-meta';
    metaDiv.innerHTML = `
      <span>Duration: ${metadata.duration ? metadata.duration.toFixed(1) + 's' : '—'}</span>
      <span>SNR: ${metadata.snr || '—'}</span>
      <span>Speaker: ${metadata.speaker_id || '—'}</span>
    `;
    playerContainer.appendChild(metaDiv);
  } else {
    playerContainer.innerHTML = '<p class="text-muted">No audio URL available</p>';
  }

  startTime = Date.now();

  document.getElementById('btn-submit').onclick = () => submitAnnotation(task.id);
  document.getElementById('btn-skip-task').onclick = () => skipTask(task.id);
}

async function submitAnnotation(taskId) {
  const corrected = document.getElementById('corrected-transcript').value.trim();
  if (!corrected) {
    alert('Please enter a corrected transcript before submitting.');
    return;
  }

  const activeLabels = [...document.querySelectorAll('#label-buttons .label-btn.active')].map(b => b.dataset.value);

  const timeSpent = Date.now() - startTime;

  const btn = document.getElementById('btn-submit');
  btn.disabled = true;
  btn.textContent = 'Saving...';

  try {
    await api.tasks.submit(taskId, {
      transcript_corrected: corrected,
      labels: activeLabels,
      notes: document.getElementById('review-notes').value.trim(),
      time_spent_ms: timeSpent,
    });
    document.getElementById('review-status').textContent = '✓ Saved! Loading next task...';
    document.getElementById('btn-submit').textContent = 'Submit Annotation';
    document.getElementById('btn-submit').disabled = false;

    const projectId = currentTask?.project_id;
    if (projectId) {
      loadTask(projectId, null);
    } else {
      window.location.hash = '#/teams';
    }
  } catch (err) {
    btn.disabled = false;
    btn.textContent = 'Submit Annotation';
    document.getElementById('review-status').textContent = `Error: ${err.message}`;
  }
}

async function skipTask(taskId) {
  try {
    await api.tasks.skip(taskId);
    const projectId = currentTask?.project_id;
    if (projectId) {
      loadTask(projectId, null);
    }
  } catch (err) {
    document.getElementById('review-status').textContent = `Error: ${err.message}`;
  }
}

function escHtml(s) {
  if (!s) return '';
  const div = document.createElement('div');
  div.textContent = s;
  return div.innerHTML;
}
import { api } from '../api.js';

export async function renderProjects(teamId) {
  const data = await api.projects.list(teamId);
  const container = document.getElementById('project-list');
  if (!container) return;

  container.innerHTML = '';
  if (data.projects.length === 0) {
    container.innerHTML = '<p class="empty-state">No projects yet. Create one to start labeling.</p>';
    return;
  }

  for (const p of data.projects) {
    const card = document.createElement('a');
    card.href = `#/projects/${p.id}`;
    card.className = 'card';
    const pct = p.total_tasks > 0 ? Math.round((p.approved_tasks / p.total_tasks) * 100) : 0;
    card.innerHTML = `
      <div class="card-body">
        <div class="card-title">${escHtml(p.name)}</div>
        <div class="card-subtitle">${escHtml(p.description) || 'No description'}</div>
        <div class="card-stats">
          <span>${p.approved_tasks}/${p.total_tasks} approved</span>
          <span class="progress-mini"><span style="width:${pct}%"></span></span>
        </div>
      </div>
    `;
    container.appendChild(card);
  }
}

function escHtml(s) {
  if (!s) return '';
  const div = document.createElement('div');
  div.textContent = s;
  return div.innerHTML;
}

export async function renderCreateProject(teamId) {
  const app = document.getElementById('root');
  app.innerHTML = `
    <div class="project-form-page">
      <a href="#/teams/${teamId}" class="back-link">← Back to Team</a>
      <h2>New Project</h2>
      <form id="create-project-form" class="form">
        <div class="input-group">
          <label>Project name *</label>
          <input type="text" id="proj-name" required placeholder="e.g. Naija Transcript Review" />
        </div>
        <div class="input-group">
          <label>Description</label>
          <textarea id="proj-desc" rows="2" placeholder="What will reviewers look for?"></textarea>
        </div>
        <div class="input-group">
          <label>Algolia index</label>
          <input type="text" id="proj-index" value="african_language_podcasts" />
        </div>
        <div class="input-group">
          <label>Algolia filters (optional)</label>
          <input type="text" id="proj-filters" placeholder="e.g. language:naija AND gender:female" />
        </div>
        <div class="form-row">
          <div class="input-group">
            <label>IAA sample rate (0.0 - 1.0)</label>
            <input type="number" id="proj-iaa" step="0.05" min="0" max="1" value="0.1" />
          </div>
          <div class="input-group">
            <label>Gold set size</label>
            <input type="number" id="proj-gold" min="0" value="0" />
          </div>
        </div>
        <div class="input-group">
          <label>Label config (JSON)</label>
          <textarea id="proj-labels" rows="6" readonly
>{
  "labels": [
    {"value": "phonetic_error", "title": "Phonetic error", "color": "#e74c3c"},
    {"value": "lexical_substitution", "title": "Lexical substitution", "color": "#f39c12"},
    {"value": "pidgin_loss", "title": "Pidgin loss", "color": "#9b59b6"},
    {"value": "no_issues", "title": "No issues", "color": "#2ecc71"}
  ],
  "transcript_field": "transcript",
  "audio_field": "audio_url"
}</textarea>
        </div>
        <div class="modal-actions">
          <a href="#/teams/${teamId}" class="btn btn-ghost">Cancel</a>
          <button type="submit" class="btn btn-primary">Create Project</button>
        </div>
      </form>
    </div>
  `;

  document.getElementById('create-project-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const name = document.getElementById('proj-name').value.trim();
    const description = document.getElementById('proj-desc').value.trim();
    const algolia_index = document.getElementById('proj-index').value.trim();
    const algolia_filters = document.getElementById('proj-filters').value.trim() || null;
    const iaa_sample_rate = parseFloat(document.getElementById('proj-iaa').value) || 0.1;
    const gold_set_size = parseInt(document.getElementById('proj-gold').value) || 0;
    let label_config = {};
    try {
      label_config = JSON.parse(document.getElementById('proj-labels').value);
    } catch {}

    const result = await api.projects.create({
      team_id: teamId,
      name,
      description,
      algolia_index,
      algolia_filters,
      iaa_sample_rate,
      gold_set_size,
      label_config,
    });
    window.location.hash = `#/projects/${result.project.id}`;
  });
}
import { api } from '../api.js';
import { renderReview } from './review.js';

export async function renderProject(projectId) {
  const app = document.getElementById('root');
  app.innerHTML = `<p class="empty-state">Loading project...</p>`;
  let role;
  try {
    const data = await api.projects.get(projectId);
    const project = data.project;
    const stats = data.stats;
    role = data.role;

    const pct = stats.total_tasks > 0 ? Math.round((stats.approved / stats.total_tasks) * 100) : 0;

    app.innerHTML = `
      <div class="project-page">
        <a href="#/teams/${project.team_id}" class="back-link">← Back to Team</a>
        <div class="page-header">
          <div>
            <h2>${escHtml(project.name)}</h2>
            <p class="text-muted">${escHtml(project.description) || 'No description'}</p>
          </div>
          <div class="header-actions">
            ${role === 'owner' || role === 'admin' ? '<button class="btn btn-ghost" id="btn-edit-project">Settings</button>' : ''}
            <button class="btn btn-primary" id="btn-start-review">Start Review</button>
          </div>
        </div>

        <div class="stats-grid">
          <div class="stat-card">
            <div class="stat-value">${stats.total_tasks}</div>
            <div class="stat-label">Total Tasks</div>
          </div>
          <div class="stat-card">
            <div class="stat-value">${stats.pending}</div>
            <div class="stat-label">Pending</div>
          </div>
          <div class="stat-card">
            <div class="stat-value">${stats.in_progress}</div>
            <div class="stat-label">In Progress</div>
          </div>
          <div class="stat-card">
            <div class="stat-value">${stats.approved}</div>
            <div class="stat-label">Approved</div>
          </div>
          <div class="stat-card stat-card-wide">
            <div class="progress-bar"><div style="width:${pct}%"></div></div>
            <div class="stat-label">${pct}% complete</div>
          </div>
        </div>

        <div class="section">
          <div class="section-header">
            <h3>Tasks</h3>
            <div class="header-actions">
              <button class="btn btn-sm btn-ghost" id="btn-refresh-tasks">Refresh</button>
            </div>
          </div>
          <div id="task-table-wrapper">
            <table class="task-table" id="task-table">
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Type</th>
                  <th>Status</th>
                  <th>Assigned To</th>
                  <th>Created</th>
                  <th></th>
                </tr>
              </thead>
              <tbody id="task-tbody"></tbody>
            </table>
          </div>
        </div>

        ${role === 'owner' || role === 'admin' ? `
        <div class="section" id="admin-section">
          <div class="section-header">
            <h3>Admin</h3>
          </div>
          <div class="admin-cards">
            <div class="card">
              <div class="card-body">
                <div class="card-title">Import from Algolia</div>
                <div class="card-subtitle">Pull segments from search index into this project</div>
                <form id="import-form" class="form-inline">
                  <input type="number" id="import-limit" value="100" min="1" max="10000" />
                  <button type="submit" class="btn btn-primary btn-sm">Import</button>
                </form>
                <div id="import-result"></div>
              </div>
            </div>
            <div class="card">
              <div class="card-body">
                <div class="card-title">QA Stats</div>
                <div class="card-subtitle">IAA agreement and gold set accuracy</div>
                <button class="btn btn-sm btn-ghost" id="btn-load-qa">Load Stats</button>
                <div id="qa-stats"></div>
              </div>
            </div>
            <div class="card">
              <div class="card-body">
                <div class="card-title">Exports</div>
                <div class="card-subtitle">Export approved annotations</div>
                <button class="btn btn-sm btn-primary" id="btn-export">Export Approved</button>
                <div id="export-list"></div>
              </div>
            </div>
          </div>
        </div>
        ` : ''}
      </div>
    `;

    document.getElementById('btn-start-review').addEventListener('click', () => {
      renderReview(projectId, project);
    });

    loadTaskTable(projectId);

    if (role === 'owner' || role === 'admin') {
      document.getElementById('import-form').addEventListener('submit', async (e) => {
        e.preventDefault();
        const limit = parseInt(document.getElementById('import-limit').value) || 100;
        const result = await api.projects.import_algolia(projectId, { limit });
        document.getElementById('import-result').innerHTML =
          `<span class="text-success">Imported ${result.imported} of ${result.total} segments</span>`;
        loadTaskTable(projectId);
      });

      document.getElementById('btn-load-qa').addEventListener('click', async () => {
        const qa = await api.tasks.list(projectId, { limit: 1 });
        const stats = await api.projects.qaStats(projectId);
        document.getElementById('qa-stats').innerHTML = `
          <div class="qa-detail">
            <p>IAA pairs: ${stats.iaa.total_iaa}</p>
            <p>Avg agreement: ${stats.iaa.avg_agreement ? (stats.iaa.avg_agreement * 100).toFixed(1) + '%' : 'N/A'}</p>
            <p>High agreement (>80%): ${stats.iaa.high_agreement}</p>
            <p>Reviewers active: ${stats.reviewers.length}</p>
          </div>
        `;
      });

      document.getElementById('btn-export').addEventListener('click', async () => {
        await api.exports.create(projectId, { filters: { status: 'approved' } });
        loadExports(projectId);
      });
    }

    document.getElementById('btn-refresh-tasks')?.addEventListener('click', () => loadTaskTable(projectId));
  } catch (err) {
    console.error('Failed to load project:', err);
    app.innerHTML = `<div class="project-page"><p class="empty-state">Error loading project: ${escHtml(err.message)}</p></div>`;
  }
}

async function loadTaskTable(projectId) {
  try {
    const data = await api.tasks.list(projectId, { limit: 50 });
    const tbody = document.getElementById('task-tbody');
    if (!tbody) return;
    tbody.innerHTML = '';
    for (const t of data.tasks) {
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td class="cell-mono">${escHtml(t.segment_id || t.id.slice(0, 8))}</td>
        <td><span class="badge badge-${t.task_type}">${escHtml(t.task_type)}</span></td>
        <td><span class="status-dot status-${t.status}"></span> ${t.status}</td>
        <td class="text-muted">${t.assigned_to ? escHtml(t.assigned_to.slice(0, 8)) + '...' : '—'}</td>
        <td class="text-muted">${new Date(t.created_at).toLocaleDateString()}</td>
        <td><a href="#/projects/${projectId}/review/${t.id}" class="btn btn-sm btn-ghost">Review</a></td>
      `;
      tbody.appendChild(tr);
    }
  } catch (err) {
    console.error('Failed to load tasks:', err);
  }
}

async function loadExports(projectId) {
  try {
    const data = await api.exports.list(projectId);
    const el = document.getElementById('export-list');
    if (!el) return;
    el.innerHTML = data.exports.length === 0
      ? '<p class="text-muted">No exports yet</p>'
      : data.exports.map(e => `<p class="text-small">${new Date(e.created_at).toLocaleDateString()} — ${e.status} (${e.batch_size} items)</p>`).join('');
  } catch {}
}

function escHtml(s) {
  if (!s) return '';
  const div = document.createElement('div');
  div.textContent = s;
  return div.innerHTML;
}
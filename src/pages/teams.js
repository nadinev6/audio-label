import { api } from '../api.js';

export async function renderTeams() {
  const app = document.getElementById('root');
  app.innerHTML = `<p class="empty-state">Loading teams...</p>`;
  try {
    const data = await api.teams.list();
    app.innerHTML = `
      <div class="teams-page">
        <div class="page-header">
          <h2>My Teams</h2>
          <button class="btn btn-primary" id="btn-create-team">+ New Team</button>
        </div>
        <div id="team-list" class="card-grid">
          ${data.teams.length === 0 ? '<p class="empty-state">No teams yet. Create one to get started.</p>' : ''}
        </div>
      </div>
    `;

    const list = document.getElementById('team-list');
    for (const t of data.teams) {
      list.appendChild(createTeamCard(t));
    }

    document.getElementById('btn-create-team').addEventListener('click', () => showCreateForm());
  } catch (err) {
    console.error('Failed to load teams:', err);
    app.innerHTML = `<div class="teams-page"><p class="empty-state">Error loading teams: ${escHtml(err.message)}. Make sure the backend server is running.</p></div>`;
  }
}

function createTeamCard(t) {
  const card = document.createElement('a');
  card.href = `#/teams/${t.id}`;
  card.className = 'card';
  card.innerHTML = `
    <div class="card-body">
      <div class="card-title">${escHtml(t.name)}</div>
      <div class="card-subtitle">${escHtml(t.description) || 'No description'}</div>
      <div class="card-meta">
        <span class="badge">${escHtml(t.role)}</span>
        <span class="text-muted">${new Date(t.created_at).toLocaleDateString()}</span>
      </div>
    </div>
  `;
  return card;
}

function showCreateForm() {
  const overlay = document.createElement('div');
  overlay.className = 'modal-overlay';
  overlay.innerHTML = `
    <div class="modal">
      <h3>Create Team</h3>
      <form id="create-team-form">
        <div class="input-group">
          <label>Team name</label>
          <input type="text" id="team-name" required placeholder="e.g. AccentLabs Reviewers" />
        </div>
        <div class="input-group">
          <label>Description (optional)</label>
          <textarea id="team-desc" rows="2" placeholder="What will this team work on?"></textarea>
        </div>
        <div class="modal-actions">
          <button type="button" class="btn btn-ghost" id="cancel-create">Cancel</button>
          <button type="submit" class="btn btn-primary">Create</button>
        </div>
      </form>
    </div>
  `;
  document.body.appendChild(overlay);

  overlay.querySelector('#cancel-create').addEventListener('click', () => overlay.remove());
  overlay.addEventListener('click', (e) => { if (e.target === overlay) overlay.remove(); });

  overlay.querySelector('#create-team-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const name = overlay.querySelector('#team-name').value.trim();
    const description = overlay.querySelector('#team-desc').value.trim();
    if (!name) return;
    await api.teams.create({ name, description });
    overlay.remove();
    renderTeams();
  });
}

function escHtml(s) {
  if (!s) return '';
  const div = document.createElement('div');
  div.textContent = s;
  return div.innerHTML;
}
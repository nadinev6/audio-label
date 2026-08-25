import { api } from '../api.js';
import { renderProjects } from './projects.js';

export async function renderTeam(teamId) {
  const app = document.getElementById('root');
  app.innerHTML = `<p class="empty-state">Loading team...</p>`;
  try {
    const data = await api.teams.get(teamId);
    const team = data.team;
    const members = data.members;

    const app = document.getElementById('root');
    app.innerHTML = `
      <div class="team-page">
        <a href="#/teams" class="back-link">← All Teams</a>
        <div class="page-header">
          <div>
            <h2>${escHtml(team.name)}</h2>
            <p class="text-muted">${escHtml(team.description) || 'No description'}</p>
          </div>
          <div class="header-actions">
            <button class="btn btn-ghost" id="btn-edit-team">Edit</button>
          </div>
        </div>

        <div class="section">
          <div class="section-header">
            <h3>Members (${members.length})</h3>
            <button class="btn btn-sm btn-primary" id="btn-invite">+ Invite</button>
          </div>
          <div id="member-list" class="member-list"></div>
        </div>

        <div class="section">
          <div class="section-header">
            <h3>Projects</h3>
            <button class="btn btn-sm btn-primary" id="btn-new-project">+ New Project</button>
          </div>
          <div id="project-list" class="card-grid"></div>
        </div>
      </div>
    `;

    const memberList = document.getElementById('member-list');
    for (const m of members) {
      const el = document.createElement('div');
      el.className = 'member-row';
      el.innerHTML = `
        <div class="member-info">
          <span class="member-id">${escHtml(m.user_id.slice(0, 8))}...</span>
          <span class="badge">${escHtml(m.role)}</span>
        </div>
        <span class="text-muted">joined ${new Date(m.joined_at).toLocaleDateString()}</span>
      `;
      memberList.appendChild(el);
    }

    document.getElementById('btn-invite').addEventListener('click', () => showInviteForm(teamId));
    document.getElementById('btn-new-project').addEventListener('click', () => {
      window.location.hash = `#/teams/${teamId}/projects/new`;
    });

    document.getElementById('btn-edit-team').addEventListener('click', () => {
      showEditTeamForm(teamId, team);
    });

    renderProjects(teamId);
  } catch (err) {
    console.error('Failed to load team:', err);
    app.innerHTML = `<div class="team-page"><a href="#/teams" class="back-link">← All Teams</a><p class="empty-state">Error loading team: ${escHtml(err.message)}</p></div>`;
  }
}

async function showInviteForm(teamId) {
  const overlay = document.createElement('div');
  overlay.className = 'modal-overlay';
  overlay.innerHTML = `
    <div class="modal">
      <h3>Invite Member</h3>
      <form id="invite-form">
        <div class="input-group">
          <label>User ID (Supabase UID)</label>
          <input type="text" id="invite-user-id" required placeholder="User's Supabase UID" />
        </div>
        <div class="input-group">
          <label>Role</label>
          <select id="invite-role">
            <option value="reviewer">Reviewer</option>
            <option value="admin">Admin</option>
          </select>
        </div>
        <div class="modal-actions">
          <button type="button" class="btn btn-ghost" id="cancel-invite">Cancel</button>
          <button type="submit" class="btn btn-primary">Invite</button>
        </div>
      </form>
    </div>
  `;
  document.body.appendChild(overlay);

  overlay.querySelector('#cancel-invite').addEventListener('click', () => overlay.remove());
  overlay.addEventListener('click', (e) => { if (e.target === overlay) overlay.remove(); });

  overlay.querySelector('#invite-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const uid = overlay.querySelector('#invite-user-id').value.trim();
    const role = overlay.querySelector('#invite-role').value;
    await api.teams.invite(teamId, { user_id: uid, role });
    overlay.remove();
    renderTeam(teamId);
  });
}

function showEditTeamForm(teamId, team) {
  const overlay = document.createElement('div');
  overlay.className = 'modal-overlay';
  overlay.innerHTML = `
    <div class="modal">
      <h3>Edit Team</h3>
      <form id="edit-team-form">
        <div class="input-group">
          <label>Team name</label>
          <input type="text" id="edit-team-name" value="${escHtml(team.name)}" required />
        </div>
        <div class="input-group">
          <label>Description</label>
          <textarea id="edit-team-desc" rows="2">${escHtml(team.description)}</textarea>
        </div>
        <div class="modal-actions">
          <button type="button" class="btn btn-ghost" id="cancel-edit">Cancel</button>
          <button type="submit" class="btn btn-primary">Save</button>
        </div>
      </form>
    </div>
  `;
  document.body.appendChild(overlay);

  overlay.querySelector('#cancel-edit').addEventListener('click', () => overlay.remove());
  overlay.addEventListener('click', (e) => { if (e.target === overlay) overlay.remove(); });

  overlay.querySelector('#edit-team-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const name = overlay.querySelector('#edit-team-name').value.trim();
    const description = overlay.querySelector('#edit-team-desc').value.trim();
    await api.teams.update(teamId, { name, description });
    overlay.remove();
    renderTeam(teamId);
  });
}

function escHtml(s) {
  if (!s) return '';
  const div = document.createElement('div');
  div.textContent = s;
  return div.innerHTML;
}
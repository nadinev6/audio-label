import { initAuth } from './auth.js';
import { renderTeams } from './pages/teams.js';
import { renderTeam } from './pages/team.js';
import { renderProject } from './pages/project.js';
import { renderCreateProject } from './pages/projects.js';
import { renderReview, renderSpecificTask } from './pages/review.js';

const routes = [
  { pattern: /^\/teams$/, handler: renderTeams },
  { pattern: /^\/teams\/([a-f0-9-]+)\/projects\/new$/, handler: (m) => renderCreateProject(m[1]) },
  { pattern: /^\/teams\/([a-f0-9-]+)$/, handler: (m) => renderTeam(m[1]) },
  { pattern: /^\/projects\/([a-f0-9-]+)\/review\/([a-f0-9-]+)$/, handler: (m) => renderSpecificTask(m[1], m[2]) },
  { pattern: /^\/projects\/([a-f0-9-]+)$/, handler: (m) => renderProject(m[1]) },
];

function route() {
  const hash = window.location.hash.slice(1) || '/teams';
  for (const { pattern, handler } of routes) {
    const m = hash.match(pattern);
    if (m) {
      document.getElementById('chrome').style.display = 'flex';
      handler(m);
      return;
    }
  }
  document.getElementById('root').innerHTML = `<p class="empty-state">Page not found: ${escHtml(hash)}</p>`;
}

window.addEventListener('hashchange', route);

window.addEventListener('unhandledrejection', (e) => {
  console.error('Unhandled rejection:', e.reason);
  const root = document.getElementById('root');
  if (root && !root.innerHTML.trim()) {
    root.innerHTML = `<div class="teams-page"><p class="empty-state">Something went wrong: ${escHtml(e.reason?.message || 'Unknown error')}. Check the console for details.</p></div>`;
  }
});

function startApp() {
  if (window.location.hash) {
    route();
  } else {
    window.location.hash = '#/teams';
  }
}

function escHtml(s) {
  if (!s) return '';
  const div = document.createElement('div');
  div.textContent = s;
  return div.innerHTML;
}

initAuth(startApp);
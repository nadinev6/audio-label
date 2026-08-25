// Dev-mode auth: any login bypasses Supabase. Swap to real auth when you set up Supabase.

export function getLoginOverlay() {
  return document.getElementById('login-overlay');
}

export function getAppShell() {
  return document.getElementById('app-shell');
}

export async function getAccessToken() {
  // Return a dummy token that the FastAPI dev server will accept
  return Promise.resolve('dev-token');
}

export function initAuth(onAuthenticated) {
  const form = document.getElementById('login-form');

  form.addEventListener('submit', (e) => {
    e.preventDefault();
    const email = document.getElementById('login-email').value.trim();
    const password = document.getElementById('login-password').value;
    if (!email || !password) {
      document.getElementById('login-error').textContent = 'Enter email and password';
      document.getElementById('login-error').style.display = 'block';
      return;
    }
    showApp();
    onAuthenticated();
  });

  document.getElementById('btn-signout').addEventListener('click', () => {
    showLogin();
  });

  showLogin();
}

function showLogin() {
  getLoginOverlay().style.display = 'flex';
  getAppShell().style.display = 'none';
}

function showApp() {
  getLoginOverlay().style.display = 'none';
  getAppShell().style.display = 'block';
}
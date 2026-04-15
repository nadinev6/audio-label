import { supabase } from './supabase.js';

export function getLoginOverlay() {
  return document.getElementById('login-overlay');
}

export function getAppShell() {
  return document.getElementById('app-shell');
}

function showLogin() {
  getLoginOverlay().style.display = 'flex';
  getAppShell().style.display = 'none';
}

function showApp() {
  getLoginOverlay().style.display = 'none';
  getAppShell().style.display = 'block';
}

function setLoginError(msg) {
  const el = document.getElementById('login-error');
  el.textContent = msg;
  el.style.display = msg ? 'block' : 'none';
}

function setLoginLoading(loading) {
  const btn = document.getElementById('btn-signin');
  btn.disabled = loading;
  btn.textContent = loading ? 'Signing in…' : 'Sign in';
}

export async function getSession() {
  const { data } = await supabase.auth.getSession();
  return data.session;
}

export async function getAccessToken() {
  const session = await getSession();
  return session?.access_token ?? null;
}

export function initAuth(onAuthenticated) {
  const form = document.getElementById('login-form');

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    setLoginError('');
    setLoginLoading(true);

    const email = document.getElementById('login-email').value.trim();
    const password = document.getElementById('login-password').value;

    const { error } = await supabase.auth.signInWithPassword({ email, password });

    setLoginLoading(false);

    if (error) {
      setLoginError(error.message);
      return;
    }

    showApp();
    onAuthenticated();
  });

  document.getElementById('btn-signout').addEventListener('click', async () => {
    await supabase.auth.signOut();
    showLogin();
  });

  supabase.auth.onAuthStateChange((event, session) => {
    if (event === 'SIGNED_OUT' || !session) {
      showLogin();
    }
  });

  getSession().then((session) => {
    if (session) {
      showApp();
      onAuthenticated();
    } else {
      showLogin();
    }
  });
}

<div align="center">
  <img src="github.jpg" alt="Audio Label" width="100%" />
  <p><strong>Audio Label</strong></p>
  <p>
    <a href="https://github.com/nadinev6/audio-label/blob/main/LICENSE"><img src="https://img.shields.io/github/license/nadinev6/audio-label" alt="License" /></a>
    <a href="https://github.com/nadinev6/audio-label"><img src="https://img.shields.io/badge/source-GitHub-181717?logo=github" alt="Source on GitHub" /></a>
    <img src="https://img.shields.io/badge/node-%3E%3D20-339933?logo=node.js&logoColor=white" alt="Node.js 20+" />
    <img src="https://img.shields.io/badge/python-%3E%3D3.10-3776AB?logo=python&logoColor=white" alt="Python 3.10+" />
  </p>
</div>

Small self-hosted **audio-only** labeling shell: [Label Studio](https://labelstud.io/) embedded in the browser (`@heartexlabs/label-studio`) plus an optional **FastAPI** service that serves `public/tasks.json` and appends submissions to `data/annotations.jsonl` for your downstream pipeline.

**Upstream repository:** [https://github.com/nadinev6/audio-label](https://github.com/nadinev6/audio-label)

## Why `@heartexlabs/label-studio@1.4.0`?

The npm tarball for **1.8.x** currently ships without the prebuilt `build/` assets and relies on a `postinstall` script that is not viable on all environments. Version **1.4.0** includes `build/static/js/main.js` and `build/static/css/main.css`, so Vite can bundle reliably. You can revisit upgrading once a future release publishes complete build artifacts again.

## Prerequisites

- Node.js 20+ recommended  
- Python 3.10+ (optional, for the JSONL API)

## Quick start (development)

**Terminal 1 — API (saves to `data/annotations.jsonl`):**

```bash
cd server
python -m venv .venv
# Windows: .venv\Scripts\activate
# Unix:    source .venv/bin/activate
pip install -r requirements.txt
python -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

**Terminal 2 — Vite dev server (proxies `/api` → `http://127.0.0.1:8000`):**

```bash
npm install
npm run dev
```

Open the URL Vite prints (usually `http://localhost:5173`). Edit tasks in [`public/tasks.json`](public/tasks.json) (audio URLs must be reachable from your browser; configure **CORS** on the file host if it differs from the UI origin).

### Frontend-only (no Python)

If you only want to browse tasks statically, `npm run dev` can still load [`public/tasks.json`](public/tasks.json) via `/tasks.json`, but **Submit** will not persist unless the API is running.

## Production-ish layout

1. `npm run build` → static assets in `dist/`.
2. Serve `dist/` with any static host (Nginx, S3, etc.).
3. Run the FastAPI app (or your own service) behind the same origin or reverse-proxy **`/api`** to that service so the UI can POST annotations.

Each JSON line in `data/annotations.jsonl` includes `submitted_at`, `export_version`, `task_id`, `annotation`, and optional `meta`.

## Customizing labels

Edit the `LABEL_CONFIG` template in [`src/main.js`](src/main.js) (`<AudioPlus>`, `<Labels>`). Keep label strings aligned with your downstream pipeline; bump `EXPORT_VERSION` when you change the shape meaningfully.

## Future upgrades (optional)

| Direction | Typical approach |
|-----------|------------------|
| Auth | Put the static UI behind your gateway (OAuth, VPN, Basic) or switch to full Label Studio server + its auth. |
| Queue / Redis | Add workers that consume your JSONL or use Celery + Redis for batch exports—only needed at scale. |
| ML assist | Label Studio ML backend + prediction API; wire predictions into tasks when you adopt the full server. |

## License

This project is licensed under the Apache License 2.0 — see [LICENSE](LICENSE). Third-party attribution for the embedded frontend library is in [NOTICE](NOTICE).

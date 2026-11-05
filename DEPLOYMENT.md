# Render API + Vercel Client Deployment

This deploys the student-facing React/Express app on Render Free and Vercel. Free-tier SQLite storage is ephemeral and intended for demos, not durable participant research data. It does not deploy the separate Python/MySQL research experiment in `research/`.

## 1. Push the repository to GitHub

Render and Vercel deploy from the GitHub repository. Do not commit `.env`, `research/config.yaml`, benchmark data, API keys, or generated study outputs.

## 2. Create the Render API

1. In Render, choose **New → Blueprint** and select this repository. Render reads the root [render.yaml](render.yaml).
2. Select the **Free** web-service tier. The checked-in `render.yaml` configures temporary SQLite storage under `/tmp`; it does not request a persistent disk.
3. The service is pinned to Node `22.16.0` by `server/.node-version`; keep this file in the service root so Render does not select Node 26 for the `better-sqlite3` native module.
4. Confirm Render has these environment variables. Generate `COOKIE_SECRET` in Render and keep it stable.

| Key | Value |
|---|---|
| `NODE_ENV` | `production` |
| `DATA_DIR` | `/tmp/sql-project-data` |
| `EPHEMERAL_DATA_DIR` | `/tmp/sql-project-data` |
| `ALLOW_EPHEMERAL_DATA` | `true` |
| `COOKIE_SECRET` | Generate a value in Render |

For an existing production service still configured with `DATA_DIR=/var/data`, the latest code automatically falls back to `/tmp/sql-project-data` when that path is unwritable. To make it explicit, set `DATA_DIR` and `EPHEMERAL_DATA_DIR` to `/tmp/sql-project-data` and `ALLOW_EPHEMERAL_DATA=true`. Set `ALLOW_EPHEMERAL_DATA=false` only if you want startup to fail instead of using temporary storage. No disk is needed.

At startup the service creates the exercise database and sample rows under `/tmp`. Render Free may sleep and its filesystem is not durable; submissions, votes, and database files can disappear after a restart, sleep, or deploy and will then be reinitialized. This mode is suitable for a demo, not durable participant or research data. Do not run `npm run seed` unless you intend to reset the app database.

Wait for the health check to pass at `https://<render-service>.onrender.com/api/v1/health`.

## 3. Deploy the Vercel client

1. In Vercel, import the same GitHub repository.
2. Keep **Root Directory** at the repository root (`.`). The client has a local `file:..` package reference, so building from the repo root ensures npm can resolve it.
3. Use the checked-in [vercel.json](vercel.json): it installs from `client`, runs the Vite build, publishes `client/dist`, and provides SPA route fallback.
4. [vercel.json](vercel.json) already proxies `/api/*` to `https://sql-project-i7oz.onrender.com`. If Render gives your service a different hostname, change that rewrite target, preserving `/api/$1`.
5. No `VITE_API_URL` variable is needed. Browser requests stay on the Vercel origin and Vercel proxies `/api/*` to Render.
6. Deploy and note the exact production origin Vercel assigns.

## 4. Allow the Frontend Origin

With the Vercel rewrite, browser requests are same-origin, so `CLIENT_ORIGINS` is not required for the Vercel frontend. Leave it blank unless you also make direct browser requests to the Render API; if so, set it to the exact allowed origin(s). The frontend sends credentials so the signed participant cookie persists through the proxy.

Because the browser communicates with Vercel and Vercel proxies the API requests, the browser does not need to accept a third-party Render cookie. The API still sets a secure production cookie; Vercel forwards it on the proxied response.

## 5. Verify the Deployment

1. Open the Render health endpoint and confirm it returns `{"status":"ok"}`.
2. Open the Vercel site, load an exercise, submit a query, and reload the page.
3. Confirm the participant cookie is present and the attempt remains visible after reload.
4. Open Handout and verify its exercise data loads; use the browser print action as a smoke test.
5. In Render logs, confirm startup reports initialized databases only on a fresh disk, not on every deploy.

## Operations

- `COOKIE_SECRET` must remain stable across deploys. Rotating it invalidates existing signed participant cookies.
- Free-tier SQLite data is temporary. For durable storage, upgrade to a paid Render plan, attach a persistent disk at `/var/data`, set `DATA_DIR=/var/data`, and disable `ALLOW_EPHEMERAL_DATA`.
- If using the Render API directly from a browser, restrict `CLIENT_ORIGINS`; do not use `*` with credentialed requests.
- Vercel preview deployments use the same proxy target, so no per-preview CORS origin is required.
- The Render service uses SQLite and is intended for a single instance. For horizontal scaling, migrate participant/voting state to a managed database and update the repository layer first.

## Research Experiment Is Separate

The `research/` scripts use MySQL 8 and Docker and are intended to run in a controlled research environment, not as part of the Render web service. Keep benchmark-derived files private until SQLRepair dataset reuse terms are confirmed. See [research/README.md](research/README.md).
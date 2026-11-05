# Render API + Vercel Client Deployment

This deploys the student-facing React/Express app. It uses SQLite on a Render persistent disk; it does not deploy the separate Python/MySQL research experiment in `research/`.

## 1. Push the repository to GitHub

Render and Vercel deploy from the GitHub repository. Do not commit `.env`, `research/config.yaml`, benchmark data, API keys, or generated study outputs.

## 2. Create the Render API

1. In Render, choose **New → Blueprint** and select this repository. Render reads the root [render.yaml](render.yaml).
2. Select the paid Starter web-service tier. SQLite persistence requires the attached 1 GB disk; the free tier has ephemeral storage and is not suitable for preserving participant records.
3. The service is pinned to Node `22.16.0` by `server/.node-version`; keep this file in the service root so Render does not select Node 26 for the `better-sqlite3` native module.
4. When prompted for `CLIENT_ORIGINS`, enter a temporary value or leave it blank until Vercel supplies the production URL. After the frontend deploys, set it to the exact Vercel origin, for example `https://sql-project.vercel.app`, with no trailing slash.
5. Confirm Render has `NODE_ENV=production`, `DATA_DIR=/var/data`, a generated `COOKIE_SECRET`, and `CLIENT_ORIGINS` set. Keep one service instance because SQLite and its attached disk are single-instance storage.
6. Wait for the health check to pass at `https://<render-service>.onrender.com/api/v1/health`.

If you created the service from the manual **New Web Service** form instead of the Blueprint, add the disk yourself under the service's **Disks** settings: name `sql-project-data`, mount path `/var/data`, size `1 GB`. Set `DATA_DIR=/var/data` on that same service and redeploy. A Starter compute plan alone does not create or mount the disk.

At first startup, the service creates the exercise database and initial sample rows on the disk. Later restarts and deploys reuse those files and preserve submissions. Do not run `npm run seed` on the deployed disk: that command resets the app database.

## 3. Deploy the Vercel client

1. In Vercel, import the same GitHub repository.
2. Keep **Root Directory** at the repository root (`.`). The client has a local `file:..` package reference, so building from the repo root ensures npm can resolve it.
3. Use the checked-in [vercel.json](vercel.json): it installs from `client`, runs the Vite build, publishes `client/dist`, and provides SPA route fallback.
4. In [vercel.json](vercel.json), set the `/api/(.*)` rewrite destination to your exact Render service URL, preserving `/api/$1`. The checked-in value assumes the service is `sql-project-api-chakri`; change only the hostname if Render assigned a different one.
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
- Keep the Render disk attached and mounted at `/var/data`. Replacing the disk loses app data unless restored from backup.
- Back up `app.db` before risky changes. A persistent disk is not a backup strategy.
- If using the Render API directly from a browser, restrict `CLIENT_ORIGINS`; do not use `*` with credentialed requests.
- Vercel preview deployments use the same proxy target, so no per-preview CORS origin is required.
- The Render service uses SQLite and is intended for a single instance. For horizontal scaling, migrate participant/voting state to a managed database and update the repository layer first.

## Research Experiment Is Separate

The `research/` scripts use MySQL 8 and Docker and are intended to run in a controlled research environment, not as part of the Render web service. Keep benchmark-derived files private until SQLRepair dataset reuse terms are confirmed. See [research/README.md](research/README.md).
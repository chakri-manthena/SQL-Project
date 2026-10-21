# SQL-Project

A React + Node.js re-implementation of **SQLSearch** and **SQLRepair**, the tools
from the paper *Identifying and Repairing Mistakes in Student-Authored SQL Queries*
by Kai Presler-Marshall, Sarah Heckman and Kathryn Stolee
([original Java implementation](https://github.com/kpresler/SQLRepair)).

## Run Locally

Requires Node.js 20.19+ and npm. From the project root:

```powershell
npm run install:all
npm run seed
npm run dev
```

Open http://localhost:5173. The Express API runs at http://localhost:4000;
its health endpoint is http://localhost:4000/api/v1/health. Vite proxies `/api`
requests to the backend. If Vite selects another port, use the URL printed in
the terminal. Stop development servers with Ctrl+C.

To run services in separate terminals, use `npm run dev:server` and
`npm run dev:client` from the project root.

**Only seed on initial setup or when deliberately resetting data.** The seed
command replaces the exercise database and deletes stored submissions and votes.
Normal restarts do not require seeding.

## Query Exercises

Select one of ten exercises, inspect the source data and expected output, then
submit a SELECT query. For Problem 1, try:

```sql
SELECT * FROM alpha WHERE MIN = 0;
```

Submissions run against every dataset for that exercise. A mismatch shows the
source, expected output and actual output for the failing test. Row order is
ignored except for the ORDER BY exercise (Problem 8); duplicate rows are retained.
Drafts are kept while switching exercises, but not across page reloads.
Attempts are persisted under a signed participant cookie; the browser cannot
choose the participant by supplying an ID in the request body.

The problem database is read-only. The parser permits one SELECT against the
exercise's visible source tables; answer tables, writes, CTEs, subqueries, UNION,
and functions other than COUNT/SUM/AVG/MIN/MAX are not supported. Queries are
limited to 5000 characters and submissions are rate-limited. This is an exercise
runner, not a general-purpose SQL sandbox. It uses SQLite with a limited MySQL
syntax translation, not full MariaDB compatibility. Problem 10 preserves the
original exercise's representative-row GROUP BY behavior.

Repair suggestions rank curated and previously verified correct queries by
token similarity, and also run a bounded AST search over comparison operators,
nearby numeric literals, and the expected output projection. Every candidate is
checked against all datasets for the exercise before it is returned; invalid,
low-similarity, or unverified candidates are not shown. This is still a limited
repair baseline, not the original Java/Z3 synthetic repair algorithm: it does
not invent new joins, predicates, aggregates, or arbitrary query structures.
Problems 9 and 10 do not offer repair suggestions.

Alternative-query voting requires five submissions for the selected exercise and
a five-minute wait from the first submission. When available, rate each distinct
query from 1 (very difficult) to 7 (very easy). The current UI exposes the
eligibility message while the threshold is unmet. Votes are stored for the study
workflow but do not yet feed back into repair ranking.

## Verification

```powershell
npm test
npm run build
```

The Node test suite builds temporary databases from the real exercise dataset and
tests known solutions, hidden-test failures, result comparison, SQL restrictions,
API responses and participant isolation. It does not reset local practice data.

Set `COOKIE_SECRET` to a stable secret to keep participant cookies valid across
server restarts. Without it, the backend generates a new secret on each start.
Other backend options include `PORT` (default 4000) and `DATA_DIR` (default
`server/var`). If changing the API port, update the Vite proxy to match.

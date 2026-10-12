import assert from 'node:assert/strict';
import { after, test } from 'node:test';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import config from '../src/config.js';
import { buildProblemDatabase, openProblemDatabase } from '../src/db/problemDb.js';
import { openAppDatabase } from '../src/db/appDb.js';
import { createExecutor, resultsEqual } from '../src/sql/executor.js';
import { parseStudentQuery, queryForTable } from '../src/sql/studentQuery.js';
import { checkQuery } from '../src/services/checker.js';
import { PROBLEMS, SEED_CORRECT_QUERIES } from '../src/problems.js';
import { createApp } from '../src/app.js';

const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'sql-project-test-'));
const dbFile = path.join(directory, 'problems.db');
buildProblemDatabase(dbFile, config.problemSqlDir);
const db = openProblemDatabase(dbFile);
const executor = createExecutor(db);
const repo = openAppDatabase(':memory:');
after(() => {
  db.close();
  repo.close();
  fs.rmSync(directory, { recursive: true, force: true });
});

for (const problem of PROBLEMS.slice(0, 8)) {
  test(`${problem.name}: seeded correct queries pass every dataset`, () => {
    for (const query of SEED_CORRECT_QUERIES[problem.name]) {
      assert.equal(checkQuery(executor, problem, query).kind, 'success', query);
    }
  });
}

test('join and grouping exercises accept their documented solutions', () => {
  assert.equal(checkQuery(executor, PROBLEMS[8],
    'SELECT LAT, STT, ISPREF FROM india a, juliett b WHERE CVF != 256 AND a.cui = b.cui').kind, 'success');
  assert.equal(checkQuery(executor, PROBLEMS[9],
    'SELECT * FROM sqlsearchdata.kilo GROUP BY LUI').kind, 'success');
});

test('comparison ignores row order only when requested and retains duplicates', () => {
  const first = [['VALUE'], [1], [2]];
  const second = [['value'], [2], [1]];
  assert.equal(resultsEqual(first, second, { ordered: false }), true);
  assert.equal(resultsEqual(first, second, { ordered: true }), false);
  assert.equal(resultsEqual(first, [['VALUE'], [1], [1]], { ordered: false }), false);
  assert.equal(checkQuery(executor, PROBLEMS[7], 'SELECT * FROM hotel').kind, 'mismatch');
});

test('incorrect queries return feedback, including hidden-test failures', () => {
  assert.equal(checkQuery(executor, PROBLEMS[0], 'SELECT * FROM alpha').kind, 'mismatch');
  const hidden = checkQuery(executor, PROBLEMS[0], 'SELECT * FROM alpha WHERE MIN = 0 LIMIT 3');
  assert.equal(hidden.kind, 'mismatch');
  assert.match(hidden.message, /test 3 of 3/);
  assert.equal(checkQuery(executor, PROBLEMS[0], 'SELECT missing FROM alpha').kind, 'error');
});

test('writes, answer tables, extra statements and expensive queries are rejected', () => {
  for (const query of [
    'DELETE FROM alpha', 'PRAGMA table_info(alpha)', 'SELECT * FROM alphad',
    'SELECT * FROM alpha; SELECT * FROM alpha', 'SELECT * FROM alpha2',
    'SELECT randomblob(1000000000) FROM alpha',
    'SELECT * FROM alpha WHERE MIN = (SELECT MIN(MIN) FROM alpha)',
    'WITH RECURSIVE c AS (SELECT 1) SELECT * FROM c',
  ]) {
    assert.equal(checkQuery(executor, PROBLEMS[0], query).kind, 'error', query);
  }
  assert.equal(executor.readTable('alpha').length, 14);
});

test('hidden table rewriting preserves literals and qualified references', () => {
  const statement = parseStudentQuery("SELECT alpha.COL FROM alpha WHERE COL != 'alpha'", PROBLEMS[0]);
  const query = queryForTable(statement, 'alpha', 'alpha2');
  assert.match(query, /'alpha'/);
  assert.match(query, /`alpha2`\.`COL`/);
  assert.equal(checkQuery(executor, PROBLEMS[0], 'SELECT alpha.* FROM alpha AS alpha WHERE alpha.MIN = 0').kind, 'success');
});

test('API validates submissions and stores attempts under the signed participant', async () => {
  const app = createApp({ config, repo, executor });
  const server = app.listen(0, '127.0.0.1');
  await new Promise((resolve) => server.once('listening', resolve));
  const url = `http://127.0.0.1:${server.address().port}/api/v1`;
  try {
    const identity = await fetch(`${url}/myId`);
    const participant = await identity.json();
    const cookie = identity.headers.get('set-cookie').split(';')[0];
    const exercise = await (await fetch(`${url}/problems/Problem%201`)).json();
    assert.equal(exercise.sourceTables.length, 1);
    assert.equal(exercise.sourceTables[0].name, 'alpha');
    assert.equal(exercise.expected.length, 4);
    assert.equal(exercise.testCount, 3);
    const submit = (body) => fetch(`${url}/submitQuery`, {
      method: 'POST', headers: { 'Content-Type': 'application/json', Cookie: cookie },
      body: JSON.stringify(body),
    });
    const correct = await submit({ problem: 'Problem 1', query: 'SELECT * FROM alpha WHERE MIN = 0', participant: 'spoofed' });
    const result = await correct.json();
    assert.equal(result.status, 'success');
    assert.equal(result.testsPassed, 3);
    assert.equal(result.actual.length, 4);
    const mismatch = await submit({ problem: 'Problem 1', query: 'SELECT * FROM alpha' });
    assert.equal((await mismatch.json()).status, 'mismatch');
    const invalid = await submit({ problem: 'Problem 1', query: 'SELECT missing FROM alpha' });
    assert.equal((await invalid.json()).status, 'error');
    assert.equal((await submit({ problem: 'Unknown', query: 'SELECT 1' })).status, 400);
    assert.equal(repo.getMyStatements(participant, 'Problem 1').length, 3);
    assert.equal(repo.getMyStatements('spoofed', 'Problem 1').length, 0);
  } finally {
    await new Promise((resolve) => server.close(resolve));
  }
});
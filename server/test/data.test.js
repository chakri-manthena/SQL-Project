import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { after, test } from 'node:test';
import config from '../src/config.js';
import { initializeData } from '../src/data.js';

const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'sql-project-startup-'));
after(() => fs.rmSync(directory, { recursive: true, force: true }));

test('startup initializes seed data once and preserves participant rows on restart', () => {
  const startupConfig = { ...config, dataDir: directory };
  const first = initializeData(startupConfig);
  assert.ok(fs.existsSync(path.join(directory, 'problems.db')));
  assert.ok(first.repo.getCorrectStatementsForProblem('Problem 1').length > 0);
  first.repo.addStatement({
    participant: 'deploy-test',
    problem: 'Problem 1',
    statement: 'SELECT * FROM alpha WHERE MIN = 0',
    correct: true,
  });
  first.repo.close();

  const second = initializeData(startupConfig);
  assert.equal(second.repo.getMyStatements('deploy-test', 'Problem 1').length, 1);
  second.repo.close();
});
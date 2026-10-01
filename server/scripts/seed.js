import path from 'node:path';
import fs from 'node:fs';
import config from '../src/config.js';
import { buildProblemDatabase } from '../src/db/problemDb.js';
import { openAppDatabase } from '../src/db/appDb.js';
import { seedAppData } from '../src/db/seed.js';

const problemDbFile = path.join(config.dataDir, 'problems.db');
const appDbFile = path.join(config.dataDir, 'app.db');

const tables = buildProblemDatabase(problemDbFile, config.problemSqlDir);
console.log(`Built ${problemDbFile} with ${tables.length} tables`);

for (const suffix of ['', '-wal', '-shm']) fs.rmSync(appDbFile + suffix, { force: true });
const repo = openAppDatabase(appDbFile);
seedAppData(repo);
repo.close();
console.log(`Reset ${appDbFile} and loaded seed queries`);

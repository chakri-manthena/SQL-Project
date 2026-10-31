import fs from 'node:fs';
import path from 'node:path';
import { openAppDatabase } from './db/appDb.js';
import { buildProblemDatabase } from './db/problemDb.js';
import { seedAppData } from './db/seed.js';

export function initializeData(config) {
  fs.mkdirSync(config.dataDir, { recursive: true });
  const problemDbFile = path.join(config.dataDir, 'problems.db');
  if (!fs.existsSync(problemDbFile)) {
    const tables = buildProblemDatabase(problemDbFile, config.problemSqlDir);
    console.log(`Initialized ${problemDbFile} with ${tables.length} tables`);
  }

  const appDbFile = path.join(config.dataDir, 'app.db');
  const initializeSampleData = !fs.existsSync(appDbFile);
  const repo = openAppDatabase(appDbFile);
  if (initializeSampleData) {
    seedAppData(repo);
    console.log('Initialized the sample repair data');
  }
  return { repo, problemDbFile };
}
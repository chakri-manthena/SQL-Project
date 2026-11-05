import fs from 'node:fs';
import path from 'node:path';
import { openAppDatabase } from './db/appDb.js';
import { buildProblemDatabase } from './db/problemDb.js';
import { seedAppData } from './db/seed.js';

export function ensureDataDirectory(dataDir, mkdirSync = fs.mkdirSync) {
  try {
    mkdirSync(dataDir, { recursive: true });
  } catch (error) {
    if (error.code === 'EACCES' || error.code === 'EPERM') {
      throw new Error(
        `DATA_DIR is not writable: ${dataDir}. On Render, attach a persistent disk mounted at this exact path and set DATA_DIR to the same mount path.`,
        { cause: error },
      );
    }
    throw error;
  }
}

export function initializeData(config) {
  ensureDataDirectory(config.dataDir);
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
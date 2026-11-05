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
        `DATA_DIR is not writable: ${dataDir}. Set ALLOW_EPHEMERAL_DATA=true to use temporary storage, or attach a writable persistent disk at this path.`,
        { cause: error },
      );
    }
    throw error;
  }
}

export function resolveDataDirectory(config, ensureWritable = ensureDataDirectory) {
  try {
    ensureWritable(config.dataDir);
    if (
      config.allowEphemeralData &&
      path.resolve(config.dataDir) === path.resolve(config.ephemeralDataDir)
    ) {
      console.warn(
        `WARNING: using ephemeral DATA_DIR ${config.dataDir}; submissions and votes will be lost when this instance restarts or redeploys.`,
      );
    }
    return config.dataDir;
  } catch (error) {
    if (!config.allowEphemeralData || !['EACCES', 'EPERM'].includes(error.code)) {
      throw error;
    }
    ensureWritable(config.ephemeralDataDir);
    console.warn(
      `WARNING: ${config.dataDir} is unavailable. Using ephemeral DATA_DIR ${config.ephemeralDataDir}; submissions and votes will be lost when this instance restarts or redeploys.`,
    );
    return config.ephemeralDataDir;
  }
}

export function initializeData(config) {
  const dataDir = resolveDataDirectory(config);
  const problemDbFile = path.join(dataDir, 'problems.db');
  if (!fs.existsSync(problemDbFile)) {
    const tables = buildProblemDatabase(problemDbFile, config.problemSqlDir);
    console.log(`Initialized ${problemDbFile} with ${tables.length} tables`);
  }

  const appDbFile = path.join(dataDir, 'app.db');
  const initializeSampleData = !fs.existsSync(appDbFile);
  const repo = openAppDatabase(appDbFile);
  if (initializeSampleData) {
    seedAppData(repo);
    console.log('Initialized the sample repair data');
  }
  return { repo, problemDbFile };
}
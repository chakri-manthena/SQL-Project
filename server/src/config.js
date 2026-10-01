import crypto from 'node:crypto';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const serverRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

function intFromEnv(name, fallback) {
  const value = Number.parseInt(process.env[name] ?? '', 10);
  return Number.isNaN(value) ? fallback : value;
}

const config = {
  port: intFromEnv('PORT', 4000),
  dataDir: process.env.DATA_DIR ?? path.join(serverRoot, 'var'),
  problemSqlDir: path.join(serverRoot, 'data', 'problems'),
  // A random secret means participant cookies are invalidated on restart; set COOKIE_SECRET to persist them.
  cookieSecret: process.env.COOKIE_SECRET ?? crypto.randomBytes(32).toString('hex'),
  isProduction: process.env.NODE_ENV === 'production',
  voting: {
    minAttempts: intFromEnv('VOTING_MIN_ATTEMPTS', 5),
    minMinutes: intFromEnv('VOTING_MIN_MINUTES', 5),
  },
};

export default config;

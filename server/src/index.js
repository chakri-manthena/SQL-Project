import fs from 'node:fs';
import path from 'node:path';
import config from './config.js';
import { createApp } from './app.js';
import { openAppDatabase } from './db/appDb.js';
import { openProblemDatabase } from './db/problemDb.js';
import { createExecutor } from './sql/executor.js';

const problemDbFile = path.join(config.dataDir, 'problems.db');
if (!fs.existsSync(problemDbFile)) {
  console.error(`Missing ${problemDbFile}. Run "npm run seed" first.`);
  process.exit(1);
}

const repo = openAppDatabase(path.join(config.dataDir, 'app.db'));
const executor = createExecutor(openProblemDatabase(problemDbFile));
const app = createApp({ config, repo, executor });

app.listen(config.port, () => {
  console.log(`SQL-Project API listening on http://localhost:${config.port}`);
});

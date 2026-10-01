import fs from 'node:fs';
import path from 'node:path';
import config from './config.js';
import { createApp } from './app.js';

const problemDbFile = path.join(config.dataDir, 'problems.db');
if (!fs.existsSync(problemDbFile)) {
  console.error(`Missing ${problemDbFile}. Run "npm run seed" first.`);
  process.exit(1);
}

const app = createApp({ config });

app.listen(config.port, () => {
  console.log(`SQL-Project API listening on http://localhost:${config.port}`);
});

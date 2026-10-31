import config from './config.js';
import { createApp } from './app.js';
import { initializeData } from './data.js';
import { openProblemDatabase } from './db/problemDb.js';
import { createExecutor } from './sql/executor.js';

const { repo, problemDbFile } = initializeData(config);
const problemDb = openProblemDatabase(problemDbFile);
const executor = createExecutor(problemDb);
const app = createApp({ config, repo, executor });

const server = app.listen(config.port, () => {
  console.log(`SQL-Project API listening on http://localhost:${config.port}`);
});

function shutdown() {
  server.close(() => {
    problemDb.close();
    repo.close();
    process.exit(0);
  });
}

process.on('SIGTERM', shutdown);
process.on('SIGINT', shutdown);

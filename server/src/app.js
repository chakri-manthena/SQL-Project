import crypto from 'node:crypto';
import express from 'express';
import helmet from 'helmet';
import cookieParser from 'cookie-parser';
import { PROBLEMS, PROBLEM_GOALS, getProblem } from './problems.js';
import { queryRoutes } from './routes/queries.js';

const PARTICIPANT_COOKIE = 'pid';

function participantMiddleware(isProduction) {
  return (req, res, next) => {
    let id = req.signedCookies[PARTICIPANT_COOKIE];
    if (typeof id !== 'string' || !/^\d{6,10}$/.test(id)) {
      id = String(crypto.randomInt(10_000_000, 100_000_000));
      res.cookie(PARTICIPANT_COOKIE, id, {
        signed: true,
        httpOnly: true,
        sameSite: 'strict',
        secure: isProduction,
        maxAge: 1000 * 60 * 60 * 24 * 30,
      });
    }
    req.participant = id;
    next();
  };
}

/**
 * @param {object} deps
 * @param {object} deps.config
 * @param {object} deps.repo      App database repository
 * @param {object} deps.executor  Executor bound to the read-only problem database
 */
export function createApp({ config, repo, executor }) {
  const app = express();
  app.disable('x-powered-by');
  app.use(helmet());
  app.use(express.json({ limit: '20kb' }));
  app.use(cookieParser(config.cookieSecret));

  const api = express.Router();
  api.use(participantMiddleware(config.isProduction));

  api.get('/health', (req, res) => res.json({ status: 'ok' }));

  api.get('/myId', (req, res) => res.json(req.participant));

  api.get('/tables', (req, res) => res.json(PROBLEMS.map((p) => ({ problemName: p.name }))));

  api.get('/problems', (req, res) =>
    res.json(PROBLEMS.map((p, index) => ({ name: p.name, goal: PROBLEM_GOALS[index] }))));

  api.get('/problems/:name', (req, res) => {
    const problem = getProblem(req.params.name);
    if (!problem) return res.status(404).json({ status: 'failed', message: 'Unknown problem' });
    const tables = [problem.sourceTables[0], ...(problem.name === 'Problem 9' ? ['juliett'] : [])];
    return res.json({
      name: problem.name,
      goal: PROBLEM_GOALS[PROBLEMS.indexOf(problem)],
      testCount: problem.sourceTables.length,
      sourceTables: tables.map((name) => ({ name, data: executor.readTable(name) })),
      expected: executor.readTable(problem.destinationTables[0]),
    });
  });

  api.use(queryRoutes({ repo, executor }));

  app.use('/api/v1', api);

  app.use('/api', (req, res) => res.status(404).json({ status: 'failed', message: 'Not found' }));

  // eslint-disable-next-line no-unused-vars
  app.use((err, req, res, next) => {
    if (err.type === 'entity.parse.failed' || err.type === 'entity.too.large') {
      return res.status(400).json({ status: 'failed', message: 'Invalid request body' });
    }
    console.error(err);
    return res.status(500).json({ status: 'failed', message: 'Internal server error' });
  });

  return app;
}

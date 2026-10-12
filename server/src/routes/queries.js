import express from 'express';
import rateLimit from 'express-rate-limit';
import { getProblem } from '../problems.js';
import { MAX_QUERY_LENGTH } from '../sql/executor.js';
import { checkQuery } from '../services/checker.js';

export function queryRoutes({ repo, executor }) {
  const router = express.Router();

  const submitLimiter = rateLimit({
    windowMs: 60 * 1000,
    limit: 30,
    standardHeaders: 'draft-7',
    legacyHeaders: false,
    message: { status: 'failed', message: 'Too many submissions, please slow down' },
  });

  router.post('/submitQuery', submitLimiter, (req, res) => {
    const { problem: problemName, query } = req.body ?? {};
    const problem = typeof problemName === 'string' ? getProblem(problemName) : null;
    if (!problem) return res.status(400).json({ status: 'failed', message: 'Unknown problem' });
    if (typeof query !== 'string' || !query.trim() || query.length > MAX_QUERY_LENGTH) {
      return res.status(400).json({ status: 'failed', message: 'Query must be a non-empty string' });
    }

    const result = checkQuery(executor, problem, query);
    repo.addStatement({
      participant: req.participant,
      problem: problem.name,
      statement: query,
      correct: result.kind === 'success',
    });

    if (result.kind === 'success') {
      return res.json({
        status: 'success',
        message: `Good work, results matched! You've successfully solved ${problem.name}.`,
        actual: result.actual,
        testsPassed: result.testsPassed,
      });
    }
    if (result.kind === 'error') {
      return res.json({ status: 'error', errorMessage: result.message });
    }
    const { message, ...tables } = result;
    return res.json({ ...tables, status: 'mismatch', errorMessage: message });
  });

  return router;
}

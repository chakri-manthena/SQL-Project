import express from 'express';
import rateLimit from 'express-rate-limit';
import { getProblem } from '../problems.js';
import { MAX_QUERY_LENGTH } from '../sql/executor.js';
import { checkQuery } from '../services/checker.js';
import { suggestRepair } from '../services/repair.js';

function voteStatus(repo, participant, problem, config) {
  const attempts = repo.getMyStatements(participant, problem);
  if (attempts.length < config.voting.minAttempts) {
    return {
      allowed: false,
      message: `Submit at least ${config.voting.minAttempts} queries before requesting alternatives.`,
      attempts: attempts.length,
      needed: config.voting.minAttempts,
    };
  }
  const first = attempts[0]?.submitted_at ?? Date.now();
  const unlock = first + config.voting.minMinutes * 60 * 1000;
  const remainingMs = unlock - Date.now();
  if (remainingMs > 0) {
    return {
      allowed: false,
      message: `Please wait ${Math.ceil(remainingMs / 1000)} more seconds before requesting alternatives.`,
      attempts: attempts.length,
      needed: config.voting.minAttempts,
    };
  }
  return { allowed: true, attempts: attempts.length };
}

function normalizeVoteScores(payload) {
  const queries = {
    otherQuery: payload.otherQuery || null,
    repairedQuery: payload.repairedQuery || null,
    myCorrectQuery: payload.myCorrectQuery || null,
    myRepairedQuery: payload.myRepairedQuery || null,
  };
  const scores = {
    otherScore: payload.otherScore ?? null,
    repairedScore: payload.repairedScore ?? null,
    myCorrectScore: payload.myCorrectScore ?? null,
    myRepairedScore: payload.myRepairedScore ?? null,
  };
  const pairs = Object.entries(queries);
  for (const [leftField, leftQuery] of pairs) {
    if (!leftQuery) continue;
    const scoreKey = leftField.replace('Query', 'Score');
    for (const [rightField, rightQuery] of pairs) {
      if (leftField === rightField || !rightQuery || leftQuery !== rightQuery) continue;
      const rightScoreKey = rightField.replace('Query', 'Score');
      if (scores[scoreKey] == null && scores[rightScoreKey] != null) scores[scoreKey] = scores[rightScoreKey];
      if (scores[rightScoreKey] == null && scores[scoreKey] != null) scores[rightScoreKey] = scores[scoreKey];
    }
  }
  return { ...queries, ...scores };
}

function validateScores(payload) {
  const scoreKeys = ['otherScore', 'repairedScore', 'myCorrectScore', 'myRepairedScore'];
  const queryKeys = ['otherQuery', 'repairedQuery', 'myCorrectQuery', 'myRepairedQuery'];
  let hasAny = false;
  for (const key of queryKeys) {
    const value = payload[key];
    if (value != null && typeof value !== 'string') return `${key} must be a string`;
  }
  for (const key of scoreKeys) {
    const value = payload[key];
    if (value == null) continue;
    if (!Number.isInteger(value) || value < 1 || value > 7) return `${key} must be an integer between 1 and 7`;
    hasAny = true;
  }
  return hasAny ? null : 'At least one score is required';
}

function votingOptions(repo, participant, problem, submittedQuery) {
  const myCorrect = repo.getMyCorrectStatement(participant, problem)?.statement || null;
  const anotherCorrect = repo.getAnotherCorrectStatement(participant, problem) || null;
  const anotherRepair = repo.getAnotherRepairedQuery(participant, problem) || null;
  const latestWrong = repo.getMyWrongStatements(participant, problem, 1)[0]?.statement || submittedQuery || '';
  const myRepair = suggestRepair(repo, problem, latestWrong)?.query || null;

  if (anotherCorrect) repo.incrementStatementCount(anotherCorrect.id);
  if (anotherRepair) repo.incrementRepairCount(anotherRepair.id);

  const values = {
    otherQuery: anotherCorrect?.statement || null,
    repairedQuery: anotherRepair?.query || null,
    myCorrectQuery: myCorrect,
    myRepairedQuery: myRepair,
  };
  const seen = new Set();
  const cards = [];
  const labels = [
    ['otherQuery', 'Query A'],
    ['repairedQuery', 'Query B'],
    ['myCorrectQuery', 'Query C'],
    ['myRepairedQuery', 'Query D'],
  ];
  for (const [field, label] of labels) {
    const query = values[field];
    if (!query) continue;
    const key = query.trim().toUpperCase();
    if (seen.has(key)) continue;
    seen.add(key);
    cards.push({ id: field.replace('Query', ''), field, label, query });
  }
  return { ...values, cards };
}

export function queryRoutes({ repo, executor, config }) {
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
      canBeDisplayed: result.kind === 'success',
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

  router.post('/repair/suggest', submitLimiter, (req, res) => {
    const { problem: problemName, query } = req.body ?? {};
    const problem = typeof problemName === 'string' ? getProblem(problemName) : null;
    if (!problem) return res.status(400).json({ status: 'failed', message: 'Unknown problem' });
    if (!problem.repairable) {
      return res.status(400).json({ status: 'failed', message: 'Automated repair is unavailable for this exercise.' });
    }
    if (typeof query !== 'string' || !query.trim() || query.length > MAX_QUERY_LENGTH) {
      return res.status(400).json({ status: 'failed', message: 'Query must be a non-empty string' });
    }
    const suggestion = suggestRepair(repo, problem.name, query);
    if (!suggestion) {
      return res.status(404).json({ status: 'failed', message: 'No repair suggestion available yet.' });
    }
    repo.addRepairedQuery(suggestion.query, 'SYSTEM', problem.name);
    return res.json({ status: 'success', ...suggestion });
  });

  router.get('/voting/options/:problem', (req, res) => {
    const problem = getProblem(req.params.problem);
    if (!problem) return res.status(400).json({ status: 'failed', message: 'Unknown problem' });
    const status = voteStatus(repo, req.participant, problem.name, config);
    if (!status.allowed) {
      return res.json({ status: 'pending', canRequestToVote: false, ...status });
    }
    const options = votingOptions(repo, req.participant, problem.name, req.query.query || '');
    if (!options.cards.length) {
      return res.json({ status: 'pending', canRequestToVote: false, message: 'No alternative queries are available yet.' });
    }
    return res.json({ status: 'success', canRequestToVote: true, problem: problem.name, ...options });
  });

  router.post('/voting/submit', submitLimiter, (req, res) => {
    const problem = getProblem(req.body?.problem);
    if (!problem) return res.status(400).json({ status: 'failed', message: 'Unknown problem' });
    const normalized = normalizeVoteScores(req.body ?? {});
    const error = validateScores(normalized);
    if (error) return res.status(400).json({ status: 'failed', message: error });
    repo.addVote({
      participant: req.participant,
      problem: problem.name,
      explanation: typeof req.body?.explanation === 'string' ? req.body.explanation.trim().slice(0, 1000) : null,
      ...normalized,
    });
    return res.json({ status: 'success', message: 'Vote submitted' });
  });

  return router;
}

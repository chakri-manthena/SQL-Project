import express from 'express';
import rateLimit from 'express-rate-limit';
import { randomUUID } from 'node:crypto';
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

const VOTE_SESSION_TTL_MS = 10 * 60 * 1000;
const VOTE_FIELDS = {
  other: 'other',
  repaired: 'repaired',
  myCorrect: 'myCorrect',
  myRepaired: 'myRepaired',
};

function votingOptions(repo, executor, participant, problem, submittedQuery) {
  const myCorrect = repo.getMyCorrectStatement(participant, problem)?.statement || null;
  const anotherCorrect = repo.getAnotherCorrectStatement(participant, problem) || null;
  const anotherRepair = repo.getAnotherRepairedQuery(participant, problem) || null;
  const latestWrong = repo.getMyWrongStatements(participant, problem, 1)[0]?.statement || submittedQuery || '';
  const problemDefinition = getProblem(problem);
  const myRepair = suggestRepair(repo, problem, latestWrong, {
    expectedColumns: executor.readTable(problemDefinition.destinationTables[0])[0],
    isValidCandidate: (candidate) => checkQuery(executor, problemDefinition, candidate).kind === 'success',
  })?.query || null;

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
  const votingOptionsLimiter = rateLimit({
    windowMs: 60 * 1000,
    limit: 10,
    standardHeaders: 'draft-7',
    legacyHeaders: false,
    message: { status: 'failed', message: 'Too many voting sessions requested' },
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
    const suggestion = suggestRepair(repo, problem.name, query, {
      expectedColumns: executor.readTable(problem.destinationTables[0])[0],
      isValidCandidate: (candidate) => checkQuery(executor, problem, candidate).kind === 'success',
    });
    if (!suggestion) {
      return res.status(404).json({ status: 'failed', message: 'No repair suggestion available yet.' });
    }
    repo.addRepairedQuery(suggestion.query, 'SYSTEM', problem.name);
    return res.json({ status: 'success', ...suggestion });
  });

  router.get('/voting/options/:problem', votingOptionsLimiter, (req, res) => {
    const problem = getProblem(req.params.problem);
    if (!problem) return res.status(400).json({ status: 'failed', message: 'Unknown problem' });
    const status = voteStatus(repo, req.participant, problem.name, config);
    if (!status.allowed) {
      return res.json({ status: 'pending', canRequestToVote: false, ...status });
    }
    const options = votingOptions(repo, executor, req.participant, problem.name, req.query.query || '');
    if (!options.cards.length) {
      return res.json({ status: 'pending', canRequestToVote: false, message: 'No alternative queries are available yet.' });
    }
    const sessionId = randomUUID();
    repo.createVotingSession({
      id: sessionId,
      participant: req.participant,
      problem: problem.name,
      cards: options.cards,
      ttlMs: VOTE_SESSION_TTL_MS,
    });
    return res.json({
      status: 'success',
      canRequestToVote: true,
      problem: problem.name,
      sessionId,
      cards: options.cards,
    });
  });

  router.post('/voting/submit', submitLimiter, (req, res) => {
    const { sessionId, ratings, explanation } = req.body ?? {};
    if (typeof sessionId !== 'string' || !/^[0-9a-f-]{36}$/i.test(sessionId)) {
      return res.status(400).json({ status: 'failed', message: 'A valid voting session is required' });
    }
    if (!ratings || typeof ratings !== 'object' || Array.isArray(ratings)) {
      return res.status(400).json({ status: 'failed', message: 'Ratings must be provided for each displayed query' });
    }

    const outcome = repo.transaction(() => {
      const session = repo.getVotingSession(sessionId, req.participant);
      if (!session) return { status: 404, message: 'Voting session not found for this participant' };
      const now = Date.now();
      if (session.expires_at <= now) return { status: 410, message: 'Voting session expired. Load new alternatives.' };
      if (session.used_at != null) return { status: 409, message: 'This voting session has already been submitted' };

      const cardIds = session.cards.map((card) => card.id);
      const ratingIds = Object.keys(ratings);
      if (ratingIds.length !== cardIds.length || cardIds.some((id) => !Object.hasOwn(ratings, id))) {
        return { status: 400, message: 'Rate every query shown in this voting session' };
      }
      for (const id of cardIds) {
        if (!Number.isInteger(ratings[id]) || ratings[id] < 1 || ratings[id] > 7) {
          return { status: 400, message: 'Each rating must be an integer between 1 and 7' };
        }
        if (!Object.hasOwn(VOTE_FIELDS, id)) return { status: 400, message: 'Invalid query in voting session' };
      }

      const vote = {
        participant: req.participant,
        problem: session.problem,
        explanation: typeof explanation === 'string' ? explanation.trim().slice(0, 1000) : null,
        otherQuery: null,
        otherScore: null,
        repairedQuery: null,
        repairedScore: null,
        myCorrectQuery: null,
        myCorrectScore: null,
        myRepairedQuery: null,
        myRepairedScore: null,
      };
      for (const card of session.cards) {
        const field = VOTE_FIELDS[card.id];
        vote[`${field}Query`] = card.query;
        vote[`${field}Score`] = ratings[card.id];
      }

      if (!repo.consumeVotingSession(sessionId, req.participant, now)) {
        return { status: 409, message: 'This voting session has already been submitted or expired' };
      }
      repo.addVote(vote);
      return { status: 200, message: 'Vote submitted' };
    });
    return res.status(outcome.status).json({ status: outcome.status === 200 ? 'success' : 'failed', message: outcome.message });
  });

  return router;
}

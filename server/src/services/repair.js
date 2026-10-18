import { SEED_CORRECT_QUERIES, SEED_REPAIRED_QUERIES } from '../problems.js';

function tokenize(sql) {
  return new Set((sql || '')
    .toUpperCase()
    .replace(/[^A-Z0-9_]+/g, ' ')
    .trim()
    .split(/\s+/)
    .filter(Boolean));
}

function scoreSimilarity(input, candidate) {
  const left = tokenize(input);
  const right = tokenize(candidate);
  if (!left.size || !right.size) return 0;
  let intersection = 0;
  for (const token of left) {
    if (right.has(token)) intersection += 1;
  }
  const union = left.size + right.size - intersection;
  return union ? intersection / union : 0;
}

function dedupeQueries(list) {
  const seen = new Set();
  const unique = [];
  for (const query of list) {
    if (typeof query !== 'string' || !query.trim()) continue;
    const key = query.trim().toUpperCase();
    if (seen.has(key)) continue;
    seen.add(key);
    unique.push(query.trim());
  }
  return unique;
}

export function suggestRepair(repo, problemName, submittedQuery) {
  const seeded = [
    ...(SEED_REPAIRED_QUERIES[problemName] || []),
    ...(SEED_CORRECT_QUERIES[problemName] || []),
  ];
  const fromCorrect = repo.getCorrectStatementsForProblem(problemName).map((row) => row.statement);
  const fromRepairs = repo.getRepairedQueriesForProblem(problemName).map((row) => row.query);
  const candidates = dedupeQueries([...seeded, ...fromCorrect, ...fromRepairs]);
  if (!candidates.length) return null;

  let best = null;
  for (const candidate of candidates) {
    const score = scoreSimilarity(submittedQuery, candidate);
    if (!best || score > best.score) best = { query: candidate, score };
  }
  if (!best || best.score < 0.12) {
    return { query: candidates[0], confidence: 0.12, source: 'fallback' };
  }
  return {
    query: best.query,
    confidence: Number(best.score.toFixed(2)),
    source: 'similarity',
  };
}

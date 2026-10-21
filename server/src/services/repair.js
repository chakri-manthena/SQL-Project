import { getProblem, SEED_CORRECT_QUERIES, SEED_REPAIRED_QUERIES } from '../problems.js';
import { parseStudentQuery, serializeStudentQuery } from '../sql/studentQuery.js';

const COMPARISON_OPERATORS = ['=', '!=', '<', '<=', '>', '>='];
const MAX_GENERATED_CANDIDATES = 80;

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

export function generateQueryCandidates(problemName, submittedQuery, expectedColumns) {
  let original;
  try {
    const problem = getProblem(problemName);
    if (!problem?.repairable) return [];
    original = parseStudentQuery(submittedQuery, problem);
  } catch {
    return [];
  }

  const candidates = [];
  const add = (ast) => {
    if (candidates.length >= MAX_GENERATED_CANDIDATES) return;
    try {
      candidates.push(serializeStudentQuery(ast));
    } catch {
      return;
    }
  };
  const projection = structuredClone(original);
  const hasProjection = expectedColumns?.length > 0 && expectedColumns[0] !== '*';
  if (hasProjection) {
    projection.columns = expectedColumns.map((column) => ({
      expr: { type: 'column_ref', table: null, column, collate: null },
      as: null,
    }));
    add(projection);
  }

  function findPredicates(node, output = []) {
    if (!node || typeof node !== 'object') return output;
    if (node.type === 'binary_expr' && COMPARISON_OPERATORS.includes(node.operator.toUpperCase())) {
      output.push(node);
    }
    for (const value of Object.values(node)) {
      if (Array.isArray(value)) value.forEach((entry) => findPredicates(entry, output));
      else findPredicates(value, output);
    }
    return output;
  }
  const predicates = findPredicates(original.where);

  for (const predicate of predicates) {
    const rightOptions = [predicate.right];
    if (predicate.right?.type === 'number' && Number.isFinite(Number(predicate.right.value))) {
      const value = Number(predicate.right.value);
      for (const next of new Set([0, 1, value - 1, value + 1])) {
        if (next !== value) rightOptions.push({ ...predicate.right, value: next });
      }
    }
    for (const operator of COMPARISON_OPERATORS) {
      for (const right of rightOptions) {
        if (operator === predicate.operator && right.value === predicate.right?.value) continue;
      if (candidates.length >= MAX_GENERATED_CANDIDATES) break;
      const changed = structuredClone(original);
      const changedPredicates = findPredicates(changed.where);
      const target = changedPredicates[predicates.indexOf(predicate)];
      if (!target) continue;
      target.operator = operator;
      target.right = structuredClone(right);
      add(changed);
      if (hasProjection) {
        const projected = structuredClone(changed);
        projected.columns = structuredClone(projection.columns);
        add(projected);
      }
      }
      if (candidates.length >= MAX_GENERATED_CANDIDATES) break;
    }
  }
  return candidates;
}

export function suggestRepair(repo, problemName, submittedQuery, options = {}) {
  const { isValidCandidate = () => true, expectedColumns = [] } = options;
  const problem = getProblem(problemName);
  if (!problem) return null;
  try {
    parseStudentQuery(submittedQuery, problem);
  } catch {
    return null;
  }
  const seeded = [
    ...(SEED_REPAIRED_QUERIES[problemName] || []),
    ...(SEED_CORRECT_QUERIES[problemName] || []),
  ];
  const fromCorrect = repo.getCorrectStatementsForProblem(problemName).map((row) => row.statement);
  const fromRepairs = repo.getRepairedQueriesForProblem(problemName).map((row) => row.query);
  const generated = generateQueryCandidates(problemName, submittedQuery, expectedColumns);
  const candidates = dedupeQueries([...seeded, ...fromCorrect, ...fromRepairs, ...generated])
    .filter((candidate) => isValidCandidate(candidate));
  if (!candidates.length) return null;

  let best = null;
  for (const candidate of candidates) {
    const score = scoreSimilarity(submittedQuery, candidate);
    if (!best || score > best.score) best = { query: candidate, score };
  }
  if (!best || best.score < 0.2) return null;
  return {
    query: best.query,
    confidence: Number(best.score.toFixed(2)),
    source: 'similarity',
  };
}

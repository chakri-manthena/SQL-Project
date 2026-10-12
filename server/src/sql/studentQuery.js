import sqlParser from 'node-sql-parser';
import { QueryError, MAX_QUERY_LENGTH } from './executor.js';

const parser = new sqlParser.Parser();
const aggregates = new Set(['COUNT', 'SUM', 'AVG', 'MIN', 'MAX']);

export function parseStudentQuery(query, problem) {
  if (typeof query !== 'string' || !query.trim() || query.length > MAX_QUERY_LENGTH) {
    throw new QueryError('Enter a SELECT query of at most 5000 characters.');
  }
  let statement;
  try {
    const statements = parser.astify(query, { database: 'MySQL' });
    if (Array.isArray(statements) && statements.length !== 1) {
      throw new Error('Submit one SELECT statement at a time.');
    }
    statement = Array.isArray(statements) ? statements[0] : statements;
  } catch (error) {
    throw new QueryError(error.message);
  }
  if (statement.type !== 'select' || statement.with || statement._next || statement.into?.position) {
    throw new QueryError('Only a single SELECT without CTEs or UNION is supported.');
  }
  const allowed = [problem.sourceTables[0], ...(problem.name === 'Problem 9' ? ['juliett'] : [])];
  if (!statement.from?.length || statement.from.length > allowed.length) {
    throw new QueryError('Select from the source tables for this exercise.');
  }
  for (const source of statement.from) {
    if (!source.table || !allowed.includes(source.table.toLowerCase()) ||
        (source.db && source.db.toLowerCase() !== 'sqlsearchdata')) {
      throw new QueryError('Only this exercise\'s visible source tables may be queried.');
    }
    source.db = null;
  }
  function validate(node) {
    if (!node || typeof node !== 'object') return;
    if (node !== statement && node.type === 'select') {
      throw new QueryError('Subqueries are not supported in these exercises.');
    }
    if (node.type === 'function' || (node.type === 'aggr_func' && !aggregates.has(node.name.toUpperCase()))) {
      throw new QueryError('Only COUNT, SUM, AVG, MIN and MAX functions are supported.');
    }
    for (const value of Object.values(node)) validate(value);
  }
  validate(statement);
  return statement;
}

export function queryForTable(statement, visibleTable, testTable) {
  const copy = structuredClone(statement);
  function replace(node) {
    if (!node || typeof node !== 'object') return;
    if (typeof node.table === 'string' && node.table.toLowerCase() === visibleTable.toLowerCase()) {
      node.table = testTable;
    }
    for (const value of Object.values(node)) replace(value);
  }
  replace(copy);
  return parser.sqlify(copy, { database: 'MySQL' });
}
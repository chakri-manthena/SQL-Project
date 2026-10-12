import { mysqlToSqlite } from './translate.js';

export const MAX_QUERY_LENGTH = 5000;
const MAX_ROWS = 5000;

/** An error caused by the submitted query rather than by the server. */
export class QueryError extends Error {}

/**
 * Executes untrusted SELECT statements against the read-only problem database.
 * Results are returned as `[header, ...rows]`, mirroring the original API.
 */
export function createExecutor(db) {
  function execute(query) {
    if (typeof query !== 'string' || !query.trim()) throw new QueryError('Query is empty');
    if (query.length > MAX_QUERY_LENGTH) throw new QueryError('Query is too long');

    const sql = mysqlToSqlite(query);
    // Recursive CTEs can run forever and SQLite queries cannot be interrupted from Node.
    if (/\bRECURSIVE\b/i.test(sql)) throw new QueryError('Recursive queries are not supported');

    let stmt;
    try {
      stmt = db.prepare(sql);
    } catch (err) {
      throw new QueryError(err.message);
    }
    if (!stmt.reader || !stmt.readonly) throw new QueryError('Only SELECT queries are allowed');

    const result = [stmt.columns().map((c) => c.name)];
    try {
      for (const row of stmt.raw(true).iterate()) {
        if (result.length > MAX_ROWS) throw new QueryError('Query returned too many rows');
        result.push(row);
      }
    } catch (err) {
      if (err instanceof QueryError) throw err;
      throw new QueryError(err.message);
    }
    return result;
  }

  function readTable(table) {
    return execute(`SELECT * FROM "${table.replace(/"/g, '')}"`);
  }

  return { execute, readTable };
}

export function resultsEqual(a, b, { ordered = true } = {}) {
  if (a.length !== b.length) return false;
  const [headA, ...rowsA] = a;
  const [headB, ...rowsB] = b;
  if (headA.length !== headB.length) return false;
  if (headA.some((h, i) => String(h).toUpperCase() !== String(headB[i]).toUpperCase())) return false;
  if (!ordered) {
    const key = (row) => JSON.stringify(row);
    const sortedA = rowsA.map(key).sort();
    const sortedB = rowsB.map(key).sort();
    return sortedA.every((row, i) => row === sortedB[i]);
  }
  return rowsA.every((row, r) => row.every((cell, c) => cell === rowsB[r][c]));
}


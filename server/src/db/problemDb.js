import fs from 'node:fs';
import path from 'node:path';
import Database from 'better-sqlite3';

const TYPE_RANK = { INTEGER: 0, REAL: 1, TEXT: 2 };

function classify(value) {
  if (value === null) return null;
  if (/^-?\d+$/.test(value)) return 'INTEGER';
  if (/^-?\d+\.\d+$/.test(value)) return 'REAL';
  return 'TEXT';
}

/** Reads a parenthesised, comma-separated list of SQL literals starting at `start` (just after "("). */
function readValueList(sql, start) {
  const values = [];
  let i = start;
  while (i < sql.length) {
    while (/\s|,/.test(sql[i])) i++;
    if (sql[i] === ')') return values;
    if (sql[i] === "'") {
      let text = '';
      i++;
      while (i < sql.length) {
        if (sql[i] === "'" && sql[i + 1] === "'") {
          text += "'";
          i += 2;
        } else if (sql[i] === "'") {
          i++;
          break;
        } else {
          text += sql[i++];
        }
      }
      values.push(text);
    } else {
      const match = /^[^,)\s]+/.exec(sql.slice(i));
      const raw = match[0];
      values.push(raw.toUpperCase() === 'NULL' ? null : raw);
      i += raw.length;
    }
  }
  throw new Error('Unterminated VALUES list');
}

/**
 * The original dataset only ships INSERT statements, so table schemas are inferred
 * from the inserted values. Types are unified per column name so source and
 * destination tables always agree.
 */
export function inferSchemas(sql) {
  const insertPattern = /INSERT\s+INTO\s+[`"]?(\w+)[`"]?\s*\(([^)]*)\)\s*VALUES\s*\(/gi;
  const tables = new Map();
  const columnTypes = new Map();

  for (const match of sql.matchAll(insertPattern)) {
    const table = match[1];
    const columns = match[2].split(',').map((c) => c.trim().replace(/[`"]/g, ''));
    const values = readValueList(sql, match.index + match[0].length);

    if (!tables.has(table)) tables.set(table, []);
    const known = tables.get(table);

    columns.forEach((column, idx) => {
      const key = column.toUpperCase();
      if (!known.some((c) => c.toUpperCase() === key)) known.push(column);
      const type = classify(values[idx]);
      if (type && (!columnTypes.has(key) || TYPE_RANK[type] > TYPE_RANK[columnTypes.get(key)])) {
        columnTypes.set(key, type);
      }
    });
  }

  return [...tables.entries()].map(([name, columns]) => ({
    name,
    columns: columns.map((column) => ({
      name: column,
      type: columnTypes.get(column.toUpperCase()) ?? 'TEXT',
    })),
  }));
}

function createTableSql({ name, columns }) {
  // NOCASE mirrors the case-insensitive default collation of MySQL/MariaDB.
  const defs = columns.map((c) => `"${c.name}" ${c.type}${c.type === 'TEXT' ? ' COLLATE NOCASE' : ''}`);
  return `CREATE TABLE "${name}" (${defs.join(', ')})`;
}

export function buildProblemDatabase(dbFile, sqlDir) {
  fs.mkdirSync(path.dirname(dbFile), { recursive: true });
  fs.rmSync(dbFile, { force: true });

  const scripts = fs
    .readdirSync(sqlDir)
    .filter((f) => f.toLowerCase().endsWith('.sql'))
    .sort((a, b) => a.localeCompare(b, undefined, { numeric: true }))
    .map((f) => fs.readFileSync(path.join(sqlDir, f), 'utf8'));

  const schemas = inferSchemas(scripts.join('\n'));
  const db = new Database(dbFile);
  db.transaction(() => {
    for (const schema of schemas) db.exec(createTableSql(schema));
    for (const script of scripts) db.exec(script);
  })();
  db.close();
  return schemas.map((s) => s.name);
}

/** Read-only connection used to run untrusted, student-authored queries. */
export function openProblemDatabase(dbFile) {
  return new Database(dbFile, { readonly: true, fileMustExist: true });
}

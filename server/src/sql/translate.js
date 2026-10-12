/**
 * Students wrote queries for MySQL/MariaDB in the original study. This rewrites the
 * MySQL-only syntax they commonly use into SQLite equivalents, leaving the contents
 * of string literals untouched.
 */
export function mysqlToSqlite(input) {
  let out = '';
  let i = 0;
  const sql = input.trim();

  while (i < sql.length) {
    const ch = sql[i];

    if (ch === "'" || ch === '"') {
      // MySQL treats both quote styles as string literals; SQLite only accepts single quotes.
      const quote = ch;
      let text = '';
      i++;
      while (i < sql.length) {
        if (sql[i] === '\\' && i + 1 < sql.length) {
          text += sql[i + 1];
          i += 2;
        } else if (sql[i] === quote && sql[i + 1] === quote) {
          text += quote;
          i += 2;
        } else if (sql[i] === quote) {
          i++;
          break;
        } else {
          text += sql[i++];
        }
      }
      out += `'${text.replace(/'/g, "''")}'`;
      continue;
    }

    if (ch === '`') {
      const end = sql.indexOf('`', i + 1);
      const ident = end === -1 ? sql.slice(i + 1) : sql.slice(i + 1, end);
      out += `"${ident.replace(/"/g, '""')}"`;
      i = end === -1 ? sql.length : end + 1;
      continue;
    }

    if (sql.startsWith('&&', i)) {
      out += ' AND ';
      i += 2;
      continue;
    }
    if (sql.startsWith('||', i)) {
      out += ' OR ';
      i += 2;
      continue;
    }

    out += ch;
    i++;
  }

  return out.replace(/[\s;]+$/, '');
}

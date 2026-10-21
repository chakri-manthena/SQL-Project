import fs from 'node:fs';
import path from 'node:path';
import Database from 'better-sqlite3';

const SCHEMA = `
CREATE TABLE IF NOT EXISTS statements (
  id               INTEGER PRIMARY KEY AUTOINCREMENT,
  participant      TEXT    NOT NULL,
  problem          TEXT    NOT NULL,
  statement        TEXT    NOT NULL,
  correct          INTEGER NOT NULL,
  count            INTEGER NOT NULL DEFAULT 0,
  can_be_displayed INTEGER NOT NULL DEFAULT 0,
  submitted_at     INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_statements_lookup ON statements (problem, participant);

CREATE TABLE IF NOT EXISTS repaired_queries (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  query       TEXT    NOT NULL,
  participant TEXT    NOT NULL,
  problem     TEXT    NOT NULL,
  count       INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS voting_responses (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  participant       TEXT    NOT NULL,
  problem           TEXT    NOT NULL,
  explanation       TEXT,
  repaired_query    TEXT,
  repaired_score    INTEGER,
  other_query       TEXT,
  other_score       INTEGER,
  my_repaired_query TEXT,
  my_repaired_score INTEGER,
  my_correct_query  TEXT,
  my_correct_score  INTEGER,
  created_at        INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS voting_sessions (
  id           TEXT PRIMARY KEY,
  participant  TEXT NOT NULL,
  problem      TEXT NOT NULL,
  options_json TEXT NOT NULL,
  created_at   INTEGER NOT NULL,
  expires_at   INTEGER NOT NULL,
  used_at      INTEGER
);
CREATE INDEX IF NOT EXISTS idx_voting_sessions_participant ON voting_sessions (participant, problem);
`;

export function openAppDatabase(dbFile) {
  if (dbFile !== ':memory:') fs.mkdirSync(path.dirname(dbFile), { recursive: true });
  const db = new Database(dbFile);
  db.pragma('journal_mode = WAL');
  db.exec(SCHEMA);
  return createRepository(db);
}

function toStatement(row) {
  return row && { ...row, correct: Boolean(row.correct), canBeDisplayed: Boolean(row.can_be_displayed) };
}

function createRepository(db) {
  const q = {
    insertStatement: db.prepare(`
      INSERT INTO statements (participant, problem, statement, correct, count, can_be_displayed, submitted_at)
      VALUES (@participant, @problem, @statement, @correct, 0, @canBeDisplayed, @submittedAt)`),
    myStatements: db.prepare(
      'SELECT * FROM statements WHERE participant = ? AND problem = ? ORDER BY submitted_at ASC, id ASC'),
    myCorrect: db.prepare(
      'SELECT * FROM statements WHERE participant = ? AND problem = ? AND correct = 1 ORDER BY id LIMIT 1'),
    myWrongNewestFirst: db.prepare(
      'SELECT * FROM statements WHERE participant = ? AND problem = ? AND correct = 0 ORDER BY submitted_at DESC, id DESC LIMIT ?'),
    anotherCorrect: db.prepare(`
      SELECT * FROM statements
      WHERE participant <> ? AND problem = ? AND correct = 1 AND can_be_displayed = 1
      ORDER BY count ASC, id ASC LIMIT 1`),
    bumpStatement: db.prepare('UPDATE statements SET count = count + 1 WHERE id = ?'),
    insertRepair: db.prepare(
      'INSERT INTO repaired_queries (query, participant, problem, count) VALUES (?, ?, ?, 0)'),
    findRepair: db.prepare(
      'SELECT * FROM repaired_queries WHERE participant = ? AND problem = ? AND query = ? LIMIT 1'),
    anotherRepair: db.prepare(
      'SELECT * FROM repaired_queries WHERE participant <> ? AND problem = ? ORDER BY count ASC, id ASC LIMIT 1'),
    anyRepair: db.prepare(
      'SELECT * FROM repaired_queries WHERE problem = ? ORDER BY count ASC, id ASC LIMIT 1'),
    repairsForProblem: db.prepare(
      'SELECT * FROM repaired_queries WHERE problem = ? ORDER BY count ASC, id ASC LIMIT 50'),
    correctForProblem: db.prepare(
      'SELECT statement, count FROM statements WHERE problem = ? AND correct = 1 ORDER BY count ASC, id ASC LIMIT 50'),
    bumpRepair: db.prepare('UPDATE repaired_queries SET count = count + 1 WHERE id = ?'),
    insertVote: db.prepare(`
      INSERT INTO voting_responses (participant, problem, explanation, repaired_query, repaired_score,
        other_query, other_score, my_repaired_query, my_repaired_score, my_correct_query, my_correct_score, created_at)
      VALUES (@participant, @problem, @explanation, @repairedQuery, @repairedScore, @otherQuery, @otherScore,
        @myRepairedQuery, @myRepairedScore, @myCorrectQuery, @myCorrectScore, @createdAt)`),
    allVotes: db.prepare('SELECT * FROM voting_responses ORDER BY id'),
    insertVotingSession: db.prepare(`
      INSERT INTO voting_sessions (id, participant, problem, options_json, created_at, expires_at)
      VALUES (@id, @participant, @problem, @optionsJson, @createdAt, @expiresAt)`),
    getVotingSession: db.prepare('SELECT * FROM voting_sessions WHERE id = ? AND participant = ?'),
    consumeVotingSession: db.prepare(`
      UPDATE voting_sessions SET used_at = ?
      WHERE id = ? AND participant = ? AND used_at IS NULL AND expires_at > ?`),
    cleanupVotingSessions: db.prepare(`
      DELETE FROM voting_sessions WHERE expires_at <= ? OR (used_at IS NOT NULL AND used_at < ?)`),
  };

  return {
    db,
    close: () => db.close(),
    transaction: (fn) => db.transaction(fn)(),

    addStatement({ participant, problem, statement, correct, canBeDisplayed = false, submittedAt = Date.now() }) {
      return q.insertStatement.run({
        participant, problem, statement, correct: correct ? 1 : 0, canBeDisplayed: canBeDisplayed ? 1 : 0, submittedAt,
      }).lastInsertRowid;
    },
    getMyStatements: (participant, problem) => q.myStatements.all(participant, problem).map(toStatement),
    getMyCorrectStatement: (participant, problem) => toStatement(q.myCorrect.get(participant, problem)),
    getMyWrongStatements: (participant, problem, limit) =>
      q.myWrongNewestFirst.all(participant, problem, limit).map(toStatement),
    getAnotherCorrectStatement: (participant, problem) => toStatement(q.anotherCorrect.get(participant, problem)),
    incrementStatementCount: (id) => q.bumpStatement.run(id),

    addRepairedQuery(query, participant, problem) {
      if (!q.findRepair.get(participant, problem, query)) q.insertRepair.run(query, participant, problem);
    },
    getAnotherRepairedQuery: (participant, problem) => q.anotherRepair.get(participant, problem) ?? null,
    getAnyRepairedQuery: (problem) => q.anyRepair.get(problem) ?? null,
    getRepairedQueriesForProblem: (problem) => q.repairsForProblem.all(problem),
    getCorrectStatementsForProblem: (problem) => q.correctForProblem.all(problem),
    incrementRepairCount: (id) => q.bumpRepair.run(id),

    addVote: (vote) => q.insertVote.run({ ...vote, createdAt: Date.now() }).lastInsertRowid,
    getVotes: () => q.allVotes.all(),
    createVotingSession({ id, participant, problem, cards, ttlMs }) {
      const createdAt = Date.now();
      q.cleanupVotingSessions.run(createdAt, createdAt - 24 * 60 * 60 * 1000);
      q.insertVotingSession.run({
        id, participant, problem, optionsJson: JSON.stringify(cards), createdAt, expiresAt: createdAt + ttlMs,
      });
    },
    getVotingSession(id, participant) {
      const session = q.getVotingSession.get(id, participant);
      if (!session) return null;
      return { ...session, cards: JSON.parse(session.options_json) };
    },
    consumeVotingSession(id, participant, now = Date.now()) {
      return q.consumeVotingSession.run(now, id, participant, now).changes === 1;
    },
  };
}

import { QueryError, resultsEqual } from '../sql/executor.js';
import { parseStudentQuery, queryForTable } from '../sql/studentQuery.js';

/**
 * Runs a query against every (source, destination) pair of a problem. The query is
 * written against the first source table; hidden tests swap in the other tables.
 */
export function checkQuery(executor, problem, query) {
  const [visibleTable] = problem.sourceTables;
  const total = problem.sourceTables.length;
  let visibleResult;
  let statement;
  try {
    statement = parseStudentQuery(query, problem);
  } catch (error) {
    if (error instanceof QueryError) return { kind: 'error', message: error.message };
    throw error;
  }

  for (let index = 0; index < total; index++) {
    const sourceTable = problem.sourceTables[index];
    let actual;
    try {
      actual = executor.execute(queryForTable(statement, visibleTable, sourceTable));
      if (index === 0) visibleResult = actual;
    } catch (err) {
      if (err instanceof QueryError) return { kind: 'error', message: err.message };
      throw err;
    }

    const expected = executor.readTable(problem.destinationTables[index]);
    if (!resultsEqual(actual, expected, { ordered: Boolean(problem.ordered) })) {
      return {
        kind: 'mismatch',
        message: `An error occurred comparing the output from your query with the expected output in test ${index + 1} of ${total}`,
        sourceTableName: visibleTable,
        destinationTableName: `for test ${index + 1} of ${total}`,
        source: executor.readTable(sourceTable),
        destination: expected,
        actual,
      };
    }
  }
  return { kind: 'success', actual: visibleResult, testsPassed: total };
}

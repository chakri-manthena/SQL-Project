import { SEED_CORRECT_QUERIES, SEED_REPAIRED_QUERIES } from '../problems.js';

export const SYSTEM_PARTICIPANT = 'SYSTEM';

export function seedAppData(repo) {
  repo.transaction(() => {
    for (const [problem, queries] of Object.entries(SEED_CORRECT_QUERIES)) {
      for (const statement of queries) {
        repo.addStatement({ participant: SYSTEM_PARTICIPANT, problem, statement, correct: true, canBeDisplayed: true });
      }
    }
    for (const [problem, queries] of Object.entries(SEED_REPAIRED_QUERIES)) {
      for (const query of queries) repo.addRepairedQuery(query, SYSTEM_PARTICIPANT, problem);
    }
  });
}

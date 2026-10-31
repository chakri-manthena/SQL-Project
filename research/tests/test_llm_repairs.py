import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from llm_repairs import (  # noqa: E402
    edit_script_distance,
    parse_model_answer,
    rank_candidates,
    select_pilot_groups,
)


class LLMRepairTests(unittest.TestCase):
    def test_accepts_single_select_json(self):
        answer = json.dumps(
            {"repaired_sql": "SELECT * FROM alpha", "changed_clauses": ["WHERE"]}
        )

        parsed = parse_model_answer(answer)

        self.assertEqual(parsed["query"], "SELECT * FROM alpha")
        self.assertEqual(parsed["changed_clauses"], ["WHERE"])

    def test_rejects_multiple_statements_and_non_selects(self):
        for query in ("DELETE FROM alpha", "SELECT 1; SELECT 2", "WITH x AS (SELECT 1) SELECT * FROM x"):
            with self.subTest(query=query), self.assertRaises(ValueError):
                parse_model_answer(json.dumps({"repaired_sql": query, "changed_clauses": []}))

    def test_ranks_and_deduplicates_by_edit_script_length(self):
        candidates = [
            {"query": "SELECT * FROM alpha WHERE MIN = 0", "changed_clauses": ["WHERE"]},
            {"query": "SELECT * FROM alpha", "changed_clauses": []},
            {"query": "SELECT * FROM alpha", "changed_clauses": ["FORMAT"]},
        ]

        ranked = rank_candidates("SELECT * FROM alpha", candidates)

        self.assertEqual(len(ranked), 2)
        self.assertEqual(ranked[0]["query"], "SELECT * FROM alpha")
        self.assertEqual(ranked[0]["edit_script_length"], 0)

    def test_invalid_student_sql_uses_token_distance_fallback(self):
        _, measure = edit_script_distance("SELECT * FROM (", "SELECT * FROM alpha")
        self.assertEqual(measure, "token_levenshtein")

    def test_pilot_selection_is_repeatable_and_problem_stratified(self):
        records = [
            {
                "in_e_all": True,
                "group_id": f"p{problem}_{index}",
                "problem": problem,
            }
            for problem in (3, 9)
            for index in range(12)
        ]

        first = select_pilot_groups(records)
        second = select_pilot_groups(records)

        self.assertEqual([row["group_id"] for row in first], [row["group_id"] for row in second])
        self.assertEqual(sum(row["problem"] == 3 for row in first), 10)
        self.assertEqual(sum(row["problem"] == 9 for row in first), 10)


if __name__ == "__main__":
    unittest.main()
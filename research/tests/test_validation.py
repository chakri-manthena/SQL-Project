import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from eval import Problem, QueryResult, TestCase  # noqa: E402
from validation import validate_candidate  # noqa: E402


class ValidationTests(unittest.TestCase):
    def setUp(self):
        self.problem = Problem("Problem 1", (TestCase(("alpha",), "alphad"),))

    def test_candidate_passing_both_levels_is_validated(self):
        candidate = {
            "method": "llm_a",
            "group_id": "p1_x",
            "problem": 1,
            "candidates": [{"candidate_id": 1, "query": "SELECT * FROM alpha"}],
        }
        same = lambda query: QueryResult(("MIN",), ((1,),))
        variant = lambda schema, query, reference: {"status": "pass"}

        result = validate_candidate(
            candidate,
            self.problem,
            "SELECT * FROM alpha",
            [{"schema": "var_p1_f1_alpha_1", "status": "built"}],
            same,
            variant,
        )

        self.assertEqual(result["outcome"], "validated")
        self.assertEqual(result["validated_repair"], 1)
        self.assertFalse(result["first_accepted_wrong"])

    def test_first_accepted_wrong_then_later_candidate_validated(self):
        candidate = {
            "method": "llm_a",
            "group_id": "p1_y",
            "problem": 1,
            "candidates": [
                {"candidate_id": 1, "query": "SELECT * FROM alpha WHERE MIN = 0"},
                {"candidate_id": 2, "query": "SELECT * FROM alpha"},
            ],
        }
        variant_results = iter(("fail", "pass"))

        def level1_execute(query):
            return QueryResult(("MIN",), ((1,),))

        def variant_execute(schema, query, reference):
            return {"status": next(variant_results)}

        result = validate_candidate(
            candidate,
            self.problem,
            "SELECT * FROM alpha",
            [{"schema": "v1", "status": "built"}],
            level1_execute,
            variant_execute,
        )

        self.assertEqual(result["outcome"], "validated")
        self.assertEqual(result["level1_repair"], 1)
        self.assertEqual(result["validated_repair"], 2)
        self.assertTrue(result["first_accepted_wrong"])

    def test_problem10_stops_after_level1(self):
        problem = Problem("Problem 10", (TestCase(("kilo",), "kilod"),), True)
        candidate = {
            "method": "rules",
            "group_id": "p10_x",
            "problem": 10,
            "candidates": [{"candidate_id": 1, "query": "SELECT * FROM kilo"}],
        }
        result = validate_candidate(
            candidate,
            problem,
            "SELECT * FROM kilo GROUP BY LUI",
            [],
            lambda query: QueryResult(("LUI",), (("x",),)),
            lambda *args: self.fail("Problem 10 does not run Level 2"),
        )

        self.assertEqual(result["outcome"], "level1_repaired")
        self.assertIsNone(result["candidate_results"][0]["level2"])

    def test_level2_records_every_failing_variant(self):
        candidate = {
            "method": "rules",
            "group_id": "p1_z",
            "problem": 1,
            "candidates": [{"candidate_id": 1, "query": "SELECT * FROM alpha"}],
        }
        visited = []

        def execute_variant(schema, query, reference):
            visited.append(schema)
            return {"status": "fail", "error_message": "different rows"}

        result = validate_candidate(
            candidate,
            self.problem,
            "SELECT * FROM alpha",
            [
                {"schema": "var1", "status": "built"},
                {"schema": "var2", "status": "built"},
            ],
            lambda query: QueryResult(("MIN",), ((1,),)),
            execute_variant,
        )

        self.assertEqual(visited, ["var1", "var2"])
        self.assertEqual(result["candidate_results"][0]["failing_variants"], ["var1", "var2"])
        self.assertEqual(result["outcome"], "falsely_accepted")


if __name__ == "__main__":
    unittest.main()
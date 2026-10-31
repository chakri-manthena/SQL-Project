import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from prepare_submissions import normalize_query, prepare_submissions  # noqa: E402


class PrepareSubmissionsTests(unittest.TestCase):
    def test_normalizes_one_trailing_semicolon_only(self):
        self.assertEqual(normalize_query(" SELECT 1;  "), "SELECT 1")
        self.assertEqual(normalize_query("SELECT 1;;"), "SELECT 1;")

    def test_builds_groups_error_categories_and_clean_set(self):
        records = [
            {"id": 1, "file": "216_f20_queries.csv", "participant": "p1", "problem": 1, "statement": "SELECT * FROM alpha;", "submit_time": "2020-01-01T00:00:00", "correct_flag": False},
            {"id": 2, "file": "216_f20_queries.csv", "participant": "p1", "problem": 1, "statement": "SELECT * FROM alpha", "submit_time": "2020-01-01T00:01:00", "correct_flag": False},
            {"id": 3, "file": "216_f20_queries.csv", "participant": "p1", "problem": 1, "statement": None, "submit_time": "2020-01-01T00:02:00", "correct_flag": False},
            {"id": 4, "file": "216_f20_queries.csv", "participant": "p2", "problem": 7, "statement": "select distinct sver from golf", "submit_time": "2020-01-01T00:03:00", "correct_flag": False},
        ]
        evaluations = {
            1: {"status": "fail", "error_code": None},
            2: {"status": "fail", "error_code": None},
            3: {"status": "fail", "error_code": 1064, "error_message": "parse error"},
            4: {"status": "fail", "error_code": None, "label_only": True},
        }

        prepared, summary = prepare_submissions(records, evaluations, {1: "Selection", 7: "Distinct"})

        self.assertEqual(prepared[0]["group_id"], prepared[1]["group_id"])
        self.assertTrue(prepared[0]["in_e_clean"])
        self.assertFalse(prepared[1]["in_e_clean"])
        self.assertEqual(prepared[1]["error_category"], "Selection")
        self.assertEqual(prepared[2]["error_category"], "parse_error")
        self.assertEqual(prepared[2]["mysql_error_message"], "parse error")
        self.assertEqual(prepared[3]["error_category"], "label_only")
        self.assertFalse(prepared[3]["in_e_clean"])
        self.assertEqual(summary["unique_query_groups"], 3)

    def test_fall_2020_original_flag_disagreement_fails_closed(self):
        records = [
            {"id": 10, "file": "326_f20_queries.csv", "participant": "p", "problem": 1, "statement": "SELECT 1", "submit_time": "2020-01-01", "correct_flag": True}
        ]

        with self.assertRaisesRegex(ValueError, "disagrees"):
            prepare_submissions(records, {10: {"status": "fail"}}, {1: "Selection"})


if __name__ == "__main__":
    unittest.main()
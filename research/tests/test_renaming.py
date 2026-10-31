import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from renaming import (  # noqa: E402
    build_identifier_maps,
    rename_problem_metadata,
    rename_query,
    rename_submissions,
)


class RenamingTests(unittest.TestCase):
    def setUp(self):
        self.table_map, self.column_map = build_identifier_maps(
            {"alpha": ["MIN", "COL"], "alphad": ["MIN", "COL"]}
        )

    def test_maps_are_deterministic_and_consistent(self):
        self.assertEqual(self.table_map, {"alpha": "t1", "alphad": "t2"})
        self.assertEqual(self.column_map, {"col": "c1", "min": "c2"})

    def test_ast_renaming_updates_table_columns_and_schema(self):
        renamed = rename_query(
            "SELECT MIN FROM sqlsearchdata.alpha WHERE MIN >= 0",
            self.table_map,
            self.column_map,
        )

        self.assertIn("sqlsearchdata_renamed.t1", renamed)
        self.assertIn("c2", renamed)
        self.assertNotIn("MIN", renamed)

    def test_token_fallback_renames_unparseable_identifier_tokens(self):
        renamed = rename_query(
            "SELECT * FROM alpha WHERE MIN >",
            self.table_map,
            self.column_map,
        )

        self.assertIn("t1", renamed)
        self.assertIn("c2", renamed)

    def test_metadata_and_clean_submissions_preserve_original_group_pairing(self):
        problems = [
            {
                "problem": 1,
                "name": "Problem 1",
                "reference_solution": "SELECT * FROM alpha WHERE MIN = 0",
                "test_cases": [{"source_tables": ["alpha"], "destination_table": "alphad"}],
                "compare_as_multiset": False,
            }
        ]
        renamed_problems = rename_problem_metadata(problems, self.table_map, self.column_map)
        records = [
            {
                "id": 1,
                "problem": 1,
                "statement": "SELECT * FROM alpha WHERE MIN = 1",
                "group_id": "p1_original",
                "in_e_clean": True,
            },
            {
                "id": 2,
                "problem": 1,
                "statement": None,
                "group_id": "p1_null",
                "in_e_clean": False,
            },
        ]
        renamed_submissions = rename_submissions(records, self.table_map, self.column_map)

        self.assertEqual(renamed_problems[0]["test_cases"][0]["source_tables"], ["t1"])
        self.assertEqual(renamed_submissions[0]["source_group_id"], "p1_original")
        self.assertEqual(len(renamed_submissions), 1)
        self.assertNotEqual(renamed_submissions[0]["group_id"], "p1_original")


if __name__ == "__main__":
    unittest.main()
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from build_database import (  # noqa: E402
    _infer_type,
    build_problem_metadata,
    clean_create_table_sql,
    extract_reference_solution,
    expected_table_names,
)
from mysql_database import create_table_statement  # noqa: E402


class DatabaseBuildTests(unittest.TestCase):
    def test_create_table_statement_uses_explicit_types_and_nullability(self):
        statement = create_table_statement(
            "alpha",
            [
                {"name": "MIN", "type": "INT", "nullable": False},
                {"name": "AV", "type": "DECIMAL(4,2)", "nullable": True},
            ],
        )

        self.assertIn("`MIN` INT NOT NULL", statement)
        self.assertIn("`AV` DECIMAL(4,2) NULL", statement)

    def test_infers_integer_decimal_text_and_nullability(self):
        self.assertEqual(_infer_type(["1", "-2"]), ("INT", False))
        self.assertEqual(_infer_type(["1.2", "12.34"]), ("DECIMAL(4,2)", False))
        self.assertEqual(_infer_type(["1", None]), ("INT", True))
        self.assertEqual(_infer_type(["text", "2"]), ("VARCHAR(255)", False))

    def test_removes_all_mysql_ddl_conflict_markers(self):
        cleaned = clean_create_table_sql(
            "CREATE TABLE a (id int);\n<<<<<<< HEAD\n=======\n>>>>>>> branch\nCREATE TABLE b (id int);"
        )

        self.assertNotRegex(cleaned, r"(?m)^\s*(<<<<<<<|=======|>>>>>>>)")
        self.assertIn("CREATE TABLE b", cleaned)

    def test_extracts_reference_with_or_without_colon(self):
        self.assertEqual(
            extract_reference_solution("-- SOLUTION: SELECT * FROM alpha;", 1),
            "SELECT * FROM alpha",
        )
        self.assertEqual(
            extract_reference_solution("-- SOLUTION  SELECT * FROM india;", 9),
            "SELECT * FROM india",
        )

    def test_metadata_keeps_problem9_join_sources_and_problem10_multiset(self):
        sql_dir = Path(__file__).parents[1] / "data" / "raw" / "SQLRepair" / "sqlsearcher" / "sql"
        if not sql_dir.exists():
            self.skipTest("Pinned SQLRepair source checkout is not present")

        metadata = build_problem_metadata(sql_dir)

        self.assertEqual(metadata[8]["test_cases"][0]["source_tables"], ["india", "juliett"])
        self.assertTrue(metadata[9]["compare_as_multiset"])
        self.assertEqual(metadata[9]["reference_solution"], "SELECT * FROM sqlsearchdata.kilo GROUP BY LUI")

    def test_pinned_source_defines_exactly_41_tables(self):
        sql_dir = Path(__file__).parents[1] / "data" / "raw" / "SQLRepair" / "sqlsearcher" / "sql"
        if not sql_dir.exists():
            self.skipTest("Pinned SQLRepair source checkout is not present")

        names = expected_table_names(sql_dir)

        self.assertEqual(len(names), 41)
        self.assertIn("kilo2d", names)
        self.assertIn("juliett", names)


if __name__ == "__main__":
    unittest.main()
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from rules import repair_query  # noqa: E402


class RuleBaselineTests(unittest.TestCase):
    def test_r1_normalizes_double_equals(self):
        result = repair_query("SELECT * FROM alpha WHERE MIN == 0", ["MIN"], ["alpha"])
        self.assertIn("MIN = 0", result["query"])
        self.assertEqual(result["rules"], ["R1"])

    def test_r2_normalizes_mysql_boolean_operators(self):
        result = repair_query("SELECT * FROM alpha WHERE MIN = 0 && MAX > 1", ["MIN", "MAX"], ["alpha"])
        self.assertIn("AND", result["query"])
        self.assertEqual(result["rules"], ["R2"])

    def test_r3_rewrites_null_comparisons(self):
        result = repair_query("SELECT * FROM alpha WHERE AUI1 = NULL OR AUI2 != NULL", ["AUI1", "AUI2"], ["alpha"])
        self.assertIn("AUI1 IS NULL", result["query"])
        self.assertIn("AUI2 IS NOT NULL", result["query"])
        self.assertEqual(result["rules"], ["R3"])

    def test_r4_removes_trailing_projection_comma(self):
        result = repair_query("SELECT SVER, FROM golf", ["SVER"], ["golf"])
        self.assertIn("SELECT SVER FROM golf", result["query"])
        self.assertEqual(result["rules"], ["R4"])

    def test_r5_repairs_unique_nearby_keyword(self):
        result = repair_query("SELECT * FROM golf GROUPED BY LUI", ["LUI"], ["golf"])
        self.assertIn("GROUP BY", result["query"])
        self.assertEqual(result["rules"], ["R5"])

    def test_r6_quotes_identifier_compared_with_known_column(self):
        result = repair_query("SELECT * FROM bravo WHERE REL = RO", ["REL"], ["bravo"])
        self.assertIn("REL = 'RO'", result["query"])
        self.assertEqual(result["rules"], ["R6"])

    def test_r6_preserves_qualified_join_columns(self):
        result = repair_query(
            "SELECT * FROM india a, juliett b WHERE a.CUI = b.CUI",
            ["CUI", "CVF"],
            ["india", "juliett"],
            ["a", "b"],
        )

        self.assertIsNone(result["query"])

    def test_no_candidate_is_explicit(self):
        self.assertIsNone(repair_query("SELECT * FROM alpha", ["MIN"], ["alpha"])["query"])


if __name__ == "__main__":
    unittest.main()
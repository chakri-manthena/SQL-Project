import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from minimality import (  # noqa: E402
    compute_minimality,
    quadratic_weighted_kappa,
    select_annotation_sample,
)


class MinimalityTests(unittest.TestCase):
    def test_computes_student_and_reference_edit_metrics(self):
        result = compute_minimality(
            "SELECT * FROM alpha WHERE MIN > 0",
            "SELECT * FROM alpha WHERE MIN = 0",
            "SELECT * FROM alpha WHERE MIN = 0",
        )

        self.assertTrue(result["student_comparable"])
        self.assertTrue(result["identical_to_reference"])
        self.assertEqual(result["repair_to_reference"]["distance"], 0)
        self.assertIsNotNone(result["student_component_similarity"])
        self.assertAlmostEqual(result["reference_component_similarity"], 1.0)

    def test_unparseable_student_is_marked_not_comparable(self):
        result = compute_minimality(
            "SELECT * FROM (",
            "SELECT * FROM alpha",
            "SELECT * FROM alpha",
        )

        self.assertFalse(result["student_comparable"])
        self.assertEqual(result["repair_to_student"]["measure"], "token_levenshtein")

    def test_weighted_kappa_and_sample_selection(self):
        self.assertEqual(quadratic_weighted_kappa([0, 1, 2], [0, 1, 2]), 1.0)
        rows = [
            {"method": method, "problem": problem, "group_id": f"{method}-{problem}-{index}"}
            for method in ("llm_a", "llm_b")
            for problem in range(1, 6)
            for index in range(4)
        ]

        first = select_annotation_sample(rows, per_model=8, seed=42)
        second = select_annotation_sample(rows, per_model=8, seed=42)

        self.assertEqual([item["group_id"] for item in first], [item["group_id"] for item in second])
        self.assertEqual(len(first), 16)
        self.assertEqual(sum(item["method"] == "llm_a" for item in first), 8)


if __name__ == "__main__":
    unittest.main()
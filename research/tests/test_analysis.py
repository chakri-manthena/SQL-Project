import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from analyze_results import (  # noqa: E402
    build_results_report,
    holm_adjust,
    mcnemar_pvalue,
    wilson_interval,
)


class AnalysisTests(unittest.TestCase):
    def test_wilson_and_mcnemar_edges(self):
        self.assertIsNone(wilson_interval(0, 0))
        self.assertEqual(mcnemar_pvalue([True, True, True], [False, False, False]), (3, 0, 0.25))
        balanced_first = [True] * 13 + [False] * 12
        balanced_second = [False] * 13 + [True] * 12
        self.assertEqual(mcnemar_pvalue(balanced_first, balanced_second), (13, 12, 1.0))
        self.assertEqual(holm_adjust([0.01, 0.04]), [0.02, 0.04])

    def test_report_contains_core_tables_and_unrun_stage_notes(self):
        submissions = [
            {
                "id": 1,
                "participant": "p1",
                "problem": 1,
                "group_id": "p1_a",
                "in_e_all": True,
                "in_e_clean": True,
                "error_kind": "semantic",
                "error_category": "Selection",
                "label_only": False,
            }
        ]
        validation = [
            {
                "record_type": "group",
                "group_id": "p1_a",
                "problem": 1,
                "outcome": "validated",
                "level1_repair": 1,
                "validated_repair": 1,
                "first_accepted_wrong": False,
                "candidate_results": [
                    {
                        "level1": {"status": "pass"},
                        "level2": {"status": "pass"},
                        "stress_fail": True,
                    }
                ],
            },
            {
                "record_type": "submission",
                "id": 1,
                "group_id": "p1_a",
                "outcome": "validated",
            },
        ]

        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / "results.md"
            report = build_results_report(
                submissions,
                {"rules": validation},
                output_path,
                bootstrap_draws=20,
            )

            self.assertTrue(output_path.exists())
            self.assertIn("Table 2. Main Results", report)
            self.assertIn("Table 8. LLM Cost and Latency", report)
            self.assertIn("Table 5. Paired Query-Group Tests", report)
            self.assertIn("Stress failure", report)
            self.assertIn("100.0% (1/1)", report)
            self.assertIn("29.1%", report)
            figures = output_path.parent / "figures"
            for name in (
                "figure1_level1_level2.svg",
                "figure2_false_acceptance_families.svg",
                "figure3_minimality_distributions.svg",
            ):
                self.assertTrue((figures / name).exists())
                self.assertIn("<svg", (figures / name).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
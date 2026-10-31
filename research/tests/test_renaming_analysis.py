import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from analyze_renaming import build_rq4_report  # noqa: E402


class RenamingAnalysisTests(unittest.TestCase):
    def test_paired_rate_report_matches_original_groups_and_excludes_problem10_from_level2(self):
        clean = [
            {"id": 1, "participant": "p1", "group_id": "p1_a", "problem": 1},
            {"id": 2, "participant": "p1", "group_id": "p10_b", "problem": 10},
        ]
        original = [
            {"record_type": "group", "group_id": "p1_a", "problem": 1, "outcome": "validated"},
            {"record_type": "group", "group_id": "p10_b", "problem": 10, "outcome": "level1_repaired"},
            {"record_type": "submission", "id": 1, "outcome": "validated"},
            {"record_type": "submission", "id": 2, "outcome": "level1_repaired"},
        ]
        renamed = [
            {"record_type": "group", "source_group_id": "p1_a", "problem": 1, "outcome": "not_repaired"},
            {"record_type": "group", "source_group_id": "p10_b", "problem": 10, "outcome": "not_repaired"},
            {"record_type": "submission", "id": 1, "outcome": "not_repaired"},
            {"record_type": "submission", "id": 2, "outcome": "not_repaired"},
        ]

        with tempfile.TemporaryDirectory() as directory:
            report = build_rq4_report(
                clean,
                {"llm_a": original},
                {"llm_a": renamed},
                Path(directory) / "rq4.md",
            )

        self.assertIn("2/2", report)
        self.assertIn("0/1", report)
        self.assertIn("identifier-dependent behavior", report)

    def test_missing_model_artifacts_are_reported_unavailable(self):
        with tempfile.TemporaryDirectory() as directory:
            report = build_rq4_report(
                [],
                {"llm_a": None, "llm_b": None},
                {"llm_a": None, "llm_b": None},
                Path(directory) / "rq4.md",
            )

        self.assertIn("unavailable", report)


if __name__ == "__main__":
    unittest.main()
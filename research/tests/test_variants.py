import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from variants import (  # noqa: E402
    VariantPlan,
    build_variant_rows,
    extract_constants,
    map_base_to_visible_names,
    plan_variants,
)


class VariantTests(unittest.TestCase):
    def test_planner_matches_all_99_documented_variant_slots(self):
        problems = []
        for number, bases in enumerate(
            (
                [("alpha",), ("alpha2",), ("alpha3",)],
                [("bravo",), ("bravo2",)],
                [("charlie",), ("charlie2",), ("charlie3",)],
                [("delta",)],
                [("echo",), ("echo2",)],
                [("foxtrot",), ("foxtrot2",)],
                [("golf",), ("golf2",)],
                [("hotel",), ("hotel2",)],
                [("india", "juliett")],
            ),
            start=1,
        ):
            problems.append(
                {
                    "problem": number,
                    "test_cases": [
                        {"source_tables": list(base)} for base in bases
                    ],
                }
            )

        plans = plan_variants(problems)

        self.assertEqual(len(plans), 99)
        self.assertEqual(
            [sum(plan.problem == number for plan in plans) for number in range(1, 10)],
            [15, 10, 15, 5, 14, 14, 10, 10, 6],
        )

    def test_row_subset_generation_is_seed_reproducible(self):
        plan = VariantPlan(1, "F1", ("alpha",), 2, 42)
        rows = {"alpha": [{"MIN": value} for value in range(10)]}

        first = build_variant_rows(plan, rows, {}, {})
        second = build_variant_rows(plan, rows, {}, {})

        self.assertEqual(first, second)
        self.assertEqual(len(first["alpha"]), 5)

    def test_hidden_base_is_copied_under_visible_first_case_name(self):
        plan = VariantPlan(3, "F1", ("charlie2",), 1, 42)
        rows, types = map_base_to_visible_names(
            plan,
            ("charlie",),
            {"charlie2": [{"CFR": 12}]},
            {"charlie2": {"CFR": "int"}},
        )

        self.assertIn("charlie", rows)
        self.assertNotIn("charlie2", rows)
        self.assertEqual(types["charlie"]["CFR"], "int")

    def test_f4_problem6_covers_all_satisfiable_truth_combinations(self):
        plan = VariantPlan(6, "F4", ("foxtrot",), 1, 42)
        rows = {"foxtrot": [{"MRRANK_RANK": 400, "TTY": "XX"}]}

        generated = build_variant_rows(plan, rows, {}, {})["foxtrot"][1:]
        combinations = {
            (
                row["MRRANK_RANK"] > 400,
                row["TTY"] == "SY",
                row["TTY"] == "PT",
            )
            for row in generated
        }

        self.assertEqual(len(combinations), 6)
        self.assertTrue(all(not (is_sy and is_pt) for _, is_sy, is_pt in combinations))

    def test_constants_include_comparisons_in_and_between_predicates(self):
        constants = extract_constants(
            [
                "SELECT * FROM alpha WHERE MIN = 1",
                "SELECT * FROM alpha WHERE MIN BETWEEN 2 AND 3 AND TTY IN ('SY', 'PT')",
            ]
        )

        self.assertEqual(constants["MIN"], ["1", "2", "3"])
        self.assertEqual(constants["TTY"], ["SY", "PT"])


if __name__ == "__main__":
    unittest.main()
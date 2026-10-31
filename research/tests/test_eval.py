import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from eval import (  # noqa: E402
    EvaluationExecutionError,
    Problem,
    QueryResult,
    TestCase,
    level1,
    match_on,
)


class EvaluatorTests(unittest.TestCase):
    def test_level1_rewrites_source_names_and_compares_in_order(self):
        problem = Problem(
            "Problem 1",
            (TestCase(("alpha",), "alphad"), TestCase(("alpha2",), "alpha2d")),
        )
        results = {
            "alpha": QueryResult(("MIN",), ((0,), (1,))),
            "alphad": QueryResult(("MIN",), ((0,), (1,))),
            "alpha2": QueryResult(("MIN",), ((2,), (3,))),
            "alpha2d": QueryResult(("MIN",), ((2,), (3,))),
        }
        calls = []

        def execute(query):
            calls.append(query)
            return results[query.rsplit(" ", 1)[-1]]

        result = level1("SELECT * FROM alpha", problem, execute)

        self.assertEqual(result["status"], "pass")
        self.assertEqual(calls[2], "SELECT * FROM alpha2")

    def test_level1_flags_label_only_failure_case_sensitively(self):
        problem = Problem("Problem 7", (TestCase(("golf",), "golfd"),))
        results = {
            "golf": QueryResult(("sver",), ((1995,),)),
            "golfd": QueryResult(("SVER",), ((1995,),)),
        }

        result = level1(
            "SELECT DISTINCT sver FROM golf",
            problem,
            lambda query: results[query.rsplit(" ", 1)[-1]],
        )

        self.assertEqual(result["status"], "fail")
        self.assertTrue(result["label_only"])

    def test_level1_keeps_destination_read_artifact(self):
        problem = Problem(
            "Problem 1",
            (TestCase(("alpha",), "alphad"), TestCase(("alpha2",), "alpha2d")),
        )
        data = QueryResult(("MIN",), ((0,),))
        result = level1("SELECT * FROM alphad", problem, lambda query: data)

        self.assertEqual(result["status"], "pass")
        self.assertTrue(result["reads_destination"])

    def test_destination_name_inside_string_is_not_a_destination_read(self):
        problem = Problem("Problem 1", (TestCase(("alpha",), "alphad"),))
        result = level1("SELECT 'alphad' FROM alpha", problem, lambda query: QueryResult(("alphad",), (("alphad",),)))

        self.assertFalse(result["reads_destination"])

    def test_problem10_compares_rows_as_a_multiset(self):
        problem = Problem(
            "Problem 10",
            (TestCase(("kilo",), "kilod"),),
            compare_as_multiset=True,
        )
        results = {
            "kilo": QueryResult(("LUI", "CUI"), (("a", "1"), ("b", "2"))),
            "kilod": QueryResult(("LUI", "CUI"), (("b", "2"), ("a", "1"))),
        }

        result = level1(
            "SELECT * FROM kilo",
            problem,
            lambda query: results[query.rsplit(" ", 1)[-1]],
        )
        self.assertEqual(result["status"], "pass")

    def test_empty_query_returns_mysql_parse_error_code(self):
        problem = Problem("Problem 1", (TestCase(("alpha",), "alphad"),))
        result = level1(None, problem, lambda query: self.fail("must not execute"))

        self.assertEqual(result["error_code"], 1064)

    def test_match_on_ignores_row_order_but_checks_order_keys(self):
        results = {
            "SELECT * FROM hotel": QueryResult(
                ("TUI", "CUI"), (("t2", "c2"), ("t1", "c1"))
            ),
            "SELECT * FROM hotel_ref": QueryResult(
                ("TUI", "CUI"), (("t1", "c1"), ("t2", "c2"))
            ),
        }

        result = match_on(
            "SELECT * FROM hotel",
            "SELECT * FROM sqlsearchdata.hotel_ref",
            results.__getitem__,
            order_columns=("TUI", "CUI"),
        )

        self.assertEqual(result["status"], "fail")
        self.assertIn("ORDER BY", result["error_message"])

    def test_match_on_extracts_order_keys_from_reference(self):
        candidate = QueryResult(
            ("TUI", "CUI"), (("t2", "c2"), ("t1", "c1"))
        )
        reference_result = QueryResult(
            ("TUI", "CUI"), (("t1", "c1"), ("t2", "c2"))
        )
        calls = iter((candidate, reference_result))

        result = match_on(
            "SELECT * FROM hotel ORDER BY TUI DESC, CUI ASC",
            "SELECT * FROM sqlsearchdata.hotel ORDER BY TUI DESC, CUI ASC",
            lambda query: next(calls),
        )

        self.assertEqual(result["status"], "fail")
        self.assertIn("ORDER BY", result["error_message"])

    def test_match_on_ignores_row_order_without_order_keys(self):
        expected = QueryResult(("VALUE",), ((1,), (2,)))
        actual = QueryResult(("value",), ((2,), (1,)))
        result = match_on("SELECT * FROM t", "SELECT * FROM sqlsearchdata.t", lambda q: actual if q.endswith("FROM t") else expected)

        self.assertEqual(result["status"], "pass")

    def test_execution_errors_fail_level2_with_error_code(self):
        def execute(query):
            raise EvaluationExecutionError(1146, "unknown table")

        result = match_on("SELECT * FROM missing", "SELECT * FROM t", execute)

        self.assertEqual(result["status"], "fail")
        self.assertEqual(result["error_code"], 1146)


if __name__ == "__main__":
    unittest.main()
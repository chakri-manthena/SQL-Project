from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Sequence


@dataclass(frozen=True)
class TestCase:
    source_tables: tuple[str, ...]
    destination_table: str


@dataclass(frozen=True)
class Problem:
    name: str
    test_cases: tuple[TestCase, ...]
    compare_as_multiset: bool = False


@dataclass(frozen=True)
class QueryResult:
    columns: tuple[str, ...]
    rows: tuple[tuple[Any, ...], ...]


class EvaluationExecutionError(Exception):
    def __init__(self, code: int | None, message: str):
        super().__init__(message)
        self.code = code


def _read_destination(query: str, problem: Problem) -> bool:
    from sqlglot import Dialect

    destinations = {case.destination_table.lower() for case in problem.test_cases}
    try:
        tokens = Dialect.get_or_raise("mysql").tokenizer().tokenize(query)
    except Exception:
        return False
    names = (
        token.text.strip("`\"'")
        for token in tokens
        if token.token_type.name in {"VAR", "IDENTIFIER"}
    )
    return any(name.lower() in destinations for name in names)


def _same_rows(actual: Sequence[tuple[Any, ...]], expected: Sequence[tuple[Any, ...]], unordered: bool) -> bool:
    if unordered:
        return Counter(actual) == Counter(expected)
    return tuple(actual) == tuple(expected)


def level1(
    query: str | None,
    problem: Problem,
    execute: Callable[[str], QueryResult],
) -> dict[str, Any]:
    """Apply the benchmark's text substitution and source/destination comparison."""
    reads_destination = _read_destination(query or "", problem)
    if not isinstance(query, str) or not query.strip():
        return {
            "status": "fail",
            "error_code": 1064,
            "error_message": "Query is empty",
            "label_only": False,
            "reads_destination": reads_destination,
        }

    visible_table = problem.test_cases[0].source_tables[0]
    rows_match_everywhere = True
    labels_differ = False
    first_mismatch = None

    for index, case in enumerate(problem.test_cases):
        source_table = case.source_tables[0]
        rewritten = query.replace(visible_table, source_table)
        try:
            actual = execute(rewritten)
            expected = execute(f"SELECT * FROM {case.destination_table}")
        except EvaluationExecutionError as error:
            return {
                "status": "fail",
                "error_code": error.code,
                "error_message": str(error),
                "label_only": False,
                "reads_destination": reads_destination,
            }

        rows_match = len(actual.columns) == len(expected.columns) and _same_rows(
            actual.rows, expected.rows, problem.compare_as_multiset
        )
        labels_match = actual.columns == expected.columns
        if not rows_match:
            rows_match_everywhere = False
            if first_mismatch is None:
                first_mismatch = index
        if not labels_match:
            labels_differ = True
            if first_mismatch is None:
                first_mismatch = index

    label_only = rows_match_everywhere and labels_differ
    if first_mismatch is not None:
        return {
            "status": "fail",
            "error_code": None,
            "error_message": f"Output differs in test {first_mismatch + 1} of {len(problem.test_cases)}",
            "label_only": label_only,
            "reads_destination": reads_destination,
        }
    return {
        "status": "pass",
        "error_code": None,
        "error_message": None,
        "label_only": False,
        "reads_destination": reads_destination,
    }


def _parse_mysql(query: str):
    from sqlglot import parse_one

    return parse_one(query, read="mysql")


def _without_schema_qualifier(query: str) -> str:
    from sqlglot import exp

    statement = _parse_mysql(query)
    for table in statement.find_all(exp.Table):
        if table.db and table.db.lower() == "sqlsearchdata":
            table.set("db", None)
    return statement.sql(dialect="mysql")


def _reference_order_columns(reference: str) -> tuple[str, ...]:
    from sqlglot import exp

    statement = _parse_mysql(reference)
    order = statement.args.get("order")
    if order is None:
        return ()
    columns = []
    for ordered in order.expressions:
        expression = ordered.this if isinstance(ordered, exp.Ordered) else ordered
        if not isinstance(expression, exp.Column):
            raise ValueError("ORDER BY expressions must identify output columns")
        columns.append(expression.name)
    return tuple(columns)


def match_on(
    query: str,
    reference: str,
    execute: Callable[[str], QueryResult],
    order_columns: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Compare a candidate and reference on one variant database."""
    try:
        actual = execute(_without_schema_qualifier(query))
        expected = execute(_without_schema_qualifier(reference))
    except EvaluationExecutionError as error:
        return {"status": "fail", "error_code": error.code, "error_message": str(error)}
    except Exception as error:
        return {"status": "fail", "error_code": None, "error_message": str(error)}

    if len(actual.columns) != len(expected.columns) or not _same_rows(actual.rows, expected.rows, True):
        return {"status": "fail", "error_code": None, "error_message": "Rows differ"}

    try:
        keys = tuple(order_columns) if order_columns is not None else _reference_order_columns(reference)
    except Exception as error:
        return {"status": "fail", "error_code": None, "error_message": str(error)}
    if keys:
        positions = []
        for key in keys:
            matches = [i for i, label in enumerate(expected.columns) if label.lower() == key.lower()]
            if len(matches) != 1:
                return {"status": "fail", "error_code": None, "error_message": f"ORDER BY key not found: {key}"}
            positions.append(matches[0])
        expected_keys = tuple(tuple(row[position] for position in positions) for row in expected.rows)
        actual_keys = tuple(tuple(row[position] for position in positions) for row in actual.rows)
        if actual_keys != expected_keys:
            return {"status": "fail", "error_code": None, "error_message": "ORDER BY key sequence differs"}

    return {"status": "pass", "error_code": None, "error_message": None}
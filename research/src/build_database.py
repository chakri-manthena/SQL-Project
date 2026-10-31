from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path

from sqlglot import exp, parse


EXPECTED_INSERTS = (55, 38, 77, 25, 93, 117, 43, 90, 44, 81)
NUMERIC_COLUMNS = {"MIN", "MAX", "TFR", "CFR", "MRRANK_RANK", "SVER"}
PROBLEM_CONCEPTS = (
    "Selection",
    "Projection and selection",
    "Inequality",
    "Projection and inequality",
    "OR condition",
    "AND/OR precedence",
    "DISTINCT and inequality",
    "Two-key ORDER BY",
    "Join and inequality",
    "GROUP BY without aggregates",
)
TEST_SOURCES = (
    (("alpha",), ("alpha2",), ("alpha3",)),
    (("bravo",), ("bravo2",)),
    (("charlie",), ("charlie2",), ("charlie3",)),
    (("delta",),),
    (("echo",), ("echo2",)),
    (("foxtrot",), ("foxtrot2",)),
    (("golf",), ("golf2",)),
    (("hotel",), ("hotel2",)),
    (("india", "juliett"),),
    (("kilo",), ("kilo2",)),
)
TEST_DESTINATIONS = (
    ("alphad", "alpha2d", "alpha3d"),
    ("bravod", "bravo2d"),
    ("charlied", "charlie2d", "charlie3d"),
    ("deltad",),
    ("echod", "echo2d"),
    ("foxtrotd", "foxtrot2d"),
    ("golfd", "golf2d"),
    ("hoteld", "hotel2d"),
    ("indiad",),
    ("kilod", "kilo2d"),
)


def _without_line_comments(sql: str) -> str:
    return "\n".join(
        line for line in sql.splitlines() if not line.lstrip().startswith("--")
    )


def _insert_values(statement: exp.Insert):
    if not isinstance(statement.this, exp.Schema) or not isinstance(statement.expression, exp.Values):
        raise ValueError("Expected INSERT with an explicit column list and VALUES rows")
    table_name = statement.this.this.name
    columns = [column.name for column in statement.this.expressions]
    for row in statement.expression.expressions:
        yield table_name, columns, row.expressions


def _literal_text(value: exp.Expression) -> str | None:
    if isinstance(value, exp.Null):
        return None
    if isinstance(value, exp.Literal):
        return str(value.this)
    raise ValueError(f"Unsupported inserted value: {value.sql(dialect='mysql')}")


def _infer_type(values: list[str | None]) -> tuple[str, bool]:
    nullable = any(value is None for value in values)
    concrete = [value for value in values if value is not None]
    if concrete and all(re.fullmatch(r"-?\d+", value) for value in concrete):
        return "INT", nullable
    if concrete and all(re.fullmatch(r"-?\d+(?:\.\d+)?", value) for value in concrete):
        scale = max((len(value.partition(".")[2]) for value in concrete), default=0)
        integer_digits = max(
            (len(value.lstrip("-").partition(".")[0]) for value in concrete),
            default=1,
        )
        precision = max(1, integer_digits) + scale
        if precision > 65:
            raise ValueError(f"Inferred DECIMAL precision exceeds MySQL limit: {precision}")
        return f"DECIMAL({precision},{scale})", nullable
    return "VARCHAR(255)", nullable


def infer_insert_schemas(sql_dir: Path) -> tuple[dict[str, list[dict]], tuple[int, ...]]:
    """Infer table columns/types for Problems 1–8 from all inserted values."""
    tables_by_problem: dict[int, dict[str, list[str]]] = {}
    values_by_problem: dict[int, dict[str, list[str | None]]] = {}
    insert_counts = []

    for problem_number in range(1, 9):
        sql = _without_line_comments((sql_dir / f"Problem{problem_number}.sql").read_text(encoding="utf-8-sig"))
        statements = parse(sql, read="mysql")
        table_columns: dict[str, list[str]] = defaultdict(list)
        column_values: dict[str, list[str | None]] = defaultdict(list)
        count = 0
        for statement in statements:
            if not isinstance(statement, exp.Insert):
                continue
            for table, columns, row_values in _insert_values(statement):
                count += 1
                for column, value_expression in zip(columns, row_values, strict=True):
                    if column not in table_columns[table]:
                        table_columns[table].append(column)
                    column_values[column.upper()].append(_literal_text(value_expression))
        if count != EXPECTED_INSERTS[problem_number - 1]:
            raise ValueError(
                f"Problem {problem_number} has {count} INSERT rows; "
                f"expected {EXPECTED_INSERTS[problem_number - 1]}"
            )
        tables_by_problem[problem_number] = dict(table_columns)
        values_by_problem[problem_number] = dict(column_values)
        insert_counts.append(count)

    schemas = {}
    for problem_number, tables in tables_by_problem.items():
        column_values = values_by_problem[problem_number]
        for table, columns in tables.items():
            schemas[table] = []
            for column in columns:
                sql_type, nullable = _infer_type(column_values[column.upper()])
                if column.upper() in NUMERIC_COLUMNS:
                    sql_type = "INT"
                elif column.upper() == "AV":
                    sql_type = "DECIMAL(4,2)"
                schemas[table].append(
                    {"name": column, "type": sql_type, "nullable": nullable}
                )
    return schemas, tuple(insert_counts)


def clean_create_table_sql(sql: str) -> str:
    return "\n".join(
        line
        for line in sql.splitlines()
        if not line.lstrip().startswith(("<<<<<<<", "=======", ">>>>>>>"))
    )


def extract_reference_solution(sql: str, problem_number: int) -> str:
    for line in sql.splitlines():
        match = re.match(r"^\s*--\s*SOLUTION\b\s*:?(.*)$", line, re.IGNORECASE)
        if match:
            solution = match.group(1).strip()
            if solution.upper().startswith("SELECT "):
                return solution.rstrip().removesuffix(";").strip()
    raise ValueError(f"Reference solution not found in Problem{problem_number}.sql")


def build_problem_metadata(sql_dir: Path) -> list[dict]:
    metadata = []
    for index in range(10):
        problem_number = index + 1
        sql = (sql_dir / f"Problem{problem_number}.sql").read_text(encoding="utf-8-sig")
        sources = TEST_SOURCES[index]
        destinations = TEST_DESTINATIONS[index]
        metadata.append(
            {
                "problem": problem_number,
                "name": f"Problem {problem_number}",
                "concept": PROBLEM_CONCEPTS[index],
                "reference_solution": extract_reference_solution(sql, problem_number),
                "test_cases": [
                    {"source_tables": list(source), "destination_table": destination}
                    for source, destination in zip(sources, destinations, strict=True)
                ],
                "ordered": problem_number != 10,
                "compare_as_multiset": problem_number == 10,
            }
        )
    return metadata


def write_problem_metadata(sql_dir: Path, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(build_problem_metadata(sql_dir), indent=2) + "\n",
        encoding="utf-8",
    )


def expected_table_names(sql_dir: Path) -> set[str]:
    schemas, _ = infer_insert_schemas(sql_dir)
    create_sql = clean_create_table_sql(
        (sql_dir / "createTables.sql").read_text(encoding="utf-8-sig")
    )
    names = set(schemas)
    for statement in parse(create_sql, read="mysql"):
        if isinstance(statement, exp.Create):
            target = statement.this.this if isinstance(statement.this, exp.Schema) else statement.this
            if isinstance(target, exp.Table):
                names.add(target.name)
    if len(names) != 41:
        raise ValueError(f"Expected 41 benchmark tables, found {len(names)}")
    return names
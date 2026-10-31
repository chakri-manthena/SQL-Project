from __future__ import annotations

import hashlib
import json
from pathlib import Path

import sqlglot
from sqlglot import Dialect, exp

from mysql_database import quote_identifier
from prepare_submissions import normalize_query
from variants import expected_output_hash


def build_identifier_maps(table_columns: dict[str, list[str]]) -> tuple[dict[str, str], dict[str, str]]:
    tables = sorted(table_columns, key=str.lower)
    columns = sorted(
        {column for names in table_columns.values() for column in names},
        key=str.lower,
    )
    table_map = {name.lower(): f"t{index}" for index, name in enumerate(tables, start=1)}
    column_map = {name.lower(): f"c{index}" for index, name in enumerate(columns, start=1)}
    return table_map, column_map


def rename_query(
    query: str | None,
    table_map: dict[str, str],
    column_map: dict[str, str],
) -> str | None:
    if not isinstance(query, str):
        return query
    try:
        statement = sqlglot.parse_one(query, read="mysql")
        for table in statement.find_all(exp.Table):
            table_name = table.name.lower()
            if table_name in table_map:
                table.set("this", exp.to_identifier(table_map[table_name]))
            if table.db and table.db.lower() == "sqlsearchdata":
                table.set("db", exp.to_identifier("sqlsearchdata_renamed"))
        for column in statement.find_all(exp.Column):
            column_name = column.name.lower()
            if column_name in column_map:
                column.set("this", exp.to_identifier(column_map[column_name]))
        return statement.sql(dialect="mysql")
    except Exception:
        tokenizer = Dialect.get_or_raise("mysql").tokenizer()
        tokens = tokenizer.tokenize(query)
        edits = []
        combined = {**table_map, **column_map, "sqlsearchdata": "sqlsearchdata_renamed"}
        for token in tokens:
            if token.token_type.name not in {"VAR", "IDENTIFIER"}:
                continue
            name = token.text.strip("`\"'").lower()
            replacement = combined.get(name)
            if replacement is not None:
                edits.append((token.start, token.end, replacement))
        renamed = query
        for start, end, replacement in sorted(edits, reverse=True):
            renamed = renamed[:start] + replacement + renamed[end + 1 :]
        return renamed


def rename_problem_metadata(
    problems: list[dict], table_map: dict[str, str], column_map: dict[str, str]
) -> list[dict]:
    renamed = []
    for source in problems:
        item = dict(source)
        item["reference_solution"] = rename_query(
            source["reference_solution"], table_map, column_map
        )
        item["test_cases"] = [
            {
                "source_tables": [table_map[table.lower()] for table in case["source_tables"]],
                "destination_table": table_map[case["destination_table"].lower()],
            }
            for case in source["test_cases"]
        ]
        renamed.append(item)
    return renamed


def rename_submissions(
    submissions: list[dict], table_map: dict[str, str], column_map: dict[str, str]
) -> list[dict]:
    renamed = []
    for source in submissions:
        if not source.get("in_e_clean"):
            continue
        item = dict(source)
        item["source_group_id"] = source["group_id"]
        item["statement"] = rename_query(source.get("statement"), table_map, column_map)
        normalized = normalize_query(item["statement"])
        digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
        item["group_id"] = f"p{int(item['problem'])}_{digest}"
        item["in_e_all"] = True
        item["in_e_clean"] = True
        renamed.append(item)
    return renamed


def _column_names(connection, schema: str, table: str) -> list[str]:
    with connection.cursor() as cursor:
        cursor.execute(
            f"SHOW COLUMNS FROM {quote_identifier(schema)}.{quote_identifier(table)}"
        )
        return [row[0] for row in cursor.fetchall()]


def clone_schema_with_renamed_identifiers(
    admin_connection,
    judge_connection,
    source_schema: str,
    target_schema: str,
    source_tables: list[str],
    table_map: dict[str, str],
    column_map: dict[str, str],
) -> None:
    if target_schema != "sqlsearchdata_renamed" and not target_schema.startswith("var_renamed_p"):
        raise ValueError(f"Refusing unexpected renamed schema: {target_schema}")
    with admin_connection.cursor() as cursor:
        cursor.execute(f"DROP DATABASE IF EXISTS {quote_identifier(target_schema)}")
        cursor.execute(f"CREATE DATABASE {quote_identifier(target_schema)} CHARACTER SET utf8mb4")
        for source_table in source_tables:
            target_table = table_map[source_table.lower()]
            cursor.execute(
                f"CREATE TABLE {quote_identifier(target_schema)}.{quote_identifier(target_table)} "
                f"LIKE {quote_identifier(source_schema)}.{quote_identifier(source_table)}"
            )
            for source_column in _column_names(admin_connection, source_schema, source_table):
                target_column = column_map[source_column.lower()]
                cursor.execute(
                    f"ALTER TABLE {quote_identifier(target_schema)}.{quote_identifier(target_table)} "
                    f"RENAME COLUMN {quote_identifier(source_column)} TO {quote_identifier(target_column)}"
                )
            cursor.execute(
                f"INSERT INTO {quote_identifier(target_schema)}.{quote_identifier(target_table)} "
                f"SELECT * FROM {quote_identifier(source_schema)}.{quote_identifier(source_table)}"
            )
        cursor.execute(
            f"GRANT SELECT ON {quote_identifier(target_schema)}.* TO 'judge'@'%'"
        )
    admin_connection.commit()
    with judge_connection.cursor() as cursor:
        cursor.execute(f"USE {quote_identifier(target_schema)}")


def clone_renamed_variant_suite(
    admin_connection,
    judge_connection,
    executor,
    manifest: list[dict],
    problems: list[dict],
    table_map: dict[str, str],
    column_map: dict[str, str],
) -> list[dict]:
    problem_by_number = {int(problem["problem"]): problem for problem in problems}
    renamed_manifest = []
    for record in manifest:
        item = dict(record)
        if record.get("status") != "built":
            item["schema"] = f"var_renamed_{record['schema'][4:]}"
            renamed_manifest.append(item)
            continue
        source_schema = record["schema"]
        target_schema = f"var_renamed_{source_schema[4:]}"
        problem = problem_by_number[int(record["problem"])]
        source_tables = problem["test_cases"][0]["source_tables"]
        clone_schema_with_renamed_identifiers(
            admin_connection,
            judge_connection,
            source_schema,
            target_schema,
            source_tables,
            table_map,
            column_map,
        )
        renamed_reference = rename_query(problem["reference_solution"], table_map, column_map)
        try:
            result = executor.execute(renamed_reference)
        finally:
            with judge_connection.cursor() as cursor:
                cursor.execute("USE sqlsearchdata")
        item["schema"] = target_schema
        item["base"] = [table_map[name.lower()] for name in record["base"]]
        item["row_counts"] = {
            table_map[name.lower()]: count
            for name, count in record["row_counts"].items()
        }
        item["expected_output_sha256"] = expected_output_hash(
            {"columns": result.columns, "rows": result.rows}
        )
        renamed_manifest.append(item)
    return renamed_manifest


def prepare_renaming_artifacts(
    admin_connection,
    judge_connection,
    executor,
    problems: list[dict],
    submissions: list[dict],
    manifest: list[dict],
) -> tuple[dict[str, str], dict[str, str], list[dict], list[dict], list[dict]]:
    all_tables = {
        table
        for problem in problems
        for case in problem["test_cases"]
        for table in (*case["source_tables"], case["destination_table"])
    }
    table_columns = {
        table: _column_names(admin_connection, "sqlsearchdata", table)
        for table in sorted(all_tables)
    }
    table_map, column_map = build_identifier_maps(table_columns)
    clone_schema_with_renamed_identifiers(
        admin_connection,
        judge_connection,
        "sqlsearchdata",
        "sqlsearchdata_renamed",
        sorted(all_tables),
        table_map,
        column_map,
    )
    renamed_problems = rename_problem_metadata(problems, table_map, column_map)
    renamed_submissions = rename_submissions(submissions, table_map, column_map)
    renamed_manifest = clone_renamed_variant_suite(
        admin_connection,
        judge_connection,
        executor,
        manifest,
        problems,
        table_map,
        column_map,
    )
    return table_map, column_map, renamed_problems, renamed_submissions, renamed_manifest


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
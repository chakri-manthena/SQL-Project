from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import replace
from pathlib import Path

from build_database import build_problem_metadata
from eval import EvaluationExecutionError
from mysql_database import MySQLExecutor, _connect, _load_config, quote_identifier
from variants import (
    build_variant_rows,
    collect_constants,
    manifest_record,
    map_base_to_visible_names,
    plan_variants,
)


SKIPPABLE_INSERT_ERRORS = {1048, 1264, 1366}


def _read_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as source:
        return [json.loads(line) for line in source if line.strip()]


def _base_rows(connection, tables: list[str]) -> tuple[dict[str, list[dict]], dict[str, dict[str, str]]]:
    rows_by_table = {}
    types_by_table = {}
    with connection.cursor() as cursor:
        for table in tables:
            cursor.execute(f"SHOW COLUMNS FROM sqlsearchdata.{quote_identifier(table)}")
            description = cursor.fetchall()
            if not description:
                raise ValueError(f"Source table has no columns: {table}")
            types_by_table[table] = {row[0]: row[1] for row in description}
            cursor.execute(f"SELECT * FROM sqlsearchdata.{quote_identifier(table)}")
            columns = [item[0] for item in cursor.description]
            rows_by_table[table] = [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]
    return rows_by_table, types_by_table


def _recreate_schema(admin_connection, judge_connection, schema: str) -> None:
    if not schema.startswith("var_p") or not schema.replace("_", "").isalnum():
        raise ValueError(f"Refusing unexpected variant schema name: {schema}")
    with judge_connection.cursor() as cursor:
        cursor.execute("USE sqlsearchdata")
    with admin_connection.cursor() as cursor:
        cursor.execute(f"DROP DATABASE IF EXISTS {quote_identifier(schema)}")
        cursor.execute(
            f"CREATE DATABASE {quote_identifier(schema)} CHARACTER SET utf8mb4"
        )
        cursor.execute(
            f"GRANT SELECT ON {quote_identifier(schema)}.* TO 'judge'@'%'"
        )
    admin_connection.commit()


def _insert_variant_rows(admin_connection, schema: str, rows_by_table: dict[str, list[dict]]):
    inserted = {}
    skipped = []
    with admin_connection.cursor() as cursor:
        for table, rows in rows_by_table.items():
            cursor.execute(
                f"CREATE TABLE {quote_identifier(schema)}.{quote_identifier(table)} "
                f"LIKE sqlsearchdata.{quote_identifier(table)}"
            )
            if not rows:
                inserted[table] = 0
                continue
            columns = list(rows[0])
            column_sql = ", ".join(quote_identifier(column) for column in columns)
            placeholders = ", ".join(["%s"] * len(columns))
            statement = (
                f"INSERT INTO {quote_identifier(schema)}.{quote_identifier(table)} "
                f"({column_sql}) VALUES ({placeholders})"
            )
            inserted_count = 0
            for row in rows:
                try:
                    cursor.execute(statement, tuple(row[column] for column in columns))
                    inserted_count += 1
                except Exception as error:
                    try:
                        code = int(error.args[0])
                    except (IndexError, TypeError, ValueError):
                        raise
                    if code not in SKIPPABLE_INSERT_ERRORS:
                        raise
                    skipped.append({"table": table, "code": code, "message": str(error)})
            inserted[table] = inserted_count
    admin_connection.commit()
    return inserted, skipped


def _evaluate_reference(judge_connection, executor: MySQLExecutor, schema: str, reference: str):
    with judge_connection.cursor() as cursor:
        cursor.execute(f"USE {quote_identifier(schema)}")
    return executor.execute(reference)


def build_suite(
    admin_connection,
    judge_connection,
    problems: list[dict],
    submissions: list[dict],
    executor: MySQLExecutor,
    seed: int = 42,
) -> list[dict]:
    references = {int(problem["problem"]): problem["reference_solution"] for problem in problems}
    constants = collect_constants(problems, submissions)
    plans = plan_variants(problems, seed=seed)
    manifest = []

    for plan in plans:
        problem = next(item for item in problems if int(item["problem"]) == plan.problem)
        reference = references[plan.problem]
        raw_base_rows, raw_types_by_table = _base_rows(admin_connection, list(plan.base))
        base_rows, types_by_table = map_base_to_visible_names(
            plan,
            tuple(problem["test_cases"][0]["source_tables"]),
            raw_base_rows,
            raw_types_by_table,
        )
        last_reason = "reference output was empty after five deterministic seeds"
        for attempt in range(5):
            attempt_plan = replace(plan, seed=plan.seed + attempt)
            rows = build_variant_rows(
                attempt_plan,
                base_rows,
                constants.get(plan.problem, {}),
                types_by_table,
            )
            _recreate_schema(admin_connection, judge_connection, plan.schema)
            actual_counts, skipped = _insert_variant_rows(
                admin_connection, plan.schema, rows
            )
            try:
                expected = _evaluate_reference(
                    judge_connection, executor, plan.schema, reference
                )
            except EvaluationExecutionError as error:
                raise RuntimeError(
                    f"Reference failed in {plan.schema}: {error} (MySQL {error.code})"
                ) from error
            if expected.rows:
                record = manifest_record(
                    attempt_plan,
                    {table: [None] * count for table, count in actual_counts.items()},
                    {"columns": expected.columns, "rows": expected.rows},
                )
                record["row_counts"] = actual_counts
                record["skipped_rows"] = skipped
                manifest.append(record)
                break
            last_reason = f"empty reference output after attempt {attempt + 1}; skipped={len(skipped)}"
        else:
            _recreate_schema(admin_connection, judge_connection, plan.schema)
            manifest.append(
                manifest_record(
                    plan,
                    {table: [] for table in plan.base},
                    None,
                    dropped_reason=last_reason,
                )
            )
    return manifest


def write_manifest(path: Path, manifest: list[dict]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "".join(
        json.dumps(record, sort_keys=True, ensure_ascii=False, default=str) + "\n"
        for record in manifest
    )
    path.write_text(content, encoding="utf-8", newline="\n")
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    path.with_suffix(path.suffix + ".sha256").write_text(
        f"{digest}  {path.name}\n", encoding="ascii"
    )
    return digest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path(__file__).parents[1] / "config.yaml")
    args = parser.parse_args()
    research_root = Path(__file__).parents[1]
    config = _load_config(args.config)
    processed = research_root / "data" / "processed"
    problems = json.loads((processed / "problems.json").read_text(encoding="utf-8"))
    submissions = _read_jsonl(processed / "submissions.jsonl")
    admin = _connect(config["database"]["admin"])
    judge = _connect(config["database"]["judge"], read_timeout=int(config["execution_timeout_seconds"]))
    try:
        executor = MySQLExecutor(judge, int(config["execution_timeout_seconds"]))
        manifest = build_suite(
            admin,
            judge,
            problems,
            submissions,
            executor,
            seed=int(config["seed"]),
        )
    finally:
        admin.close()
        judge.close()
    manifest_path = research_root / "outputs" / "variants" / "manifest.jsonl"
    digest = write_manifest(manifest_path, manifest)
    print(f"Manifest entries: {len(manifest)}; SHA-256: {digest}")


if __name__ == "__main__":
    main()
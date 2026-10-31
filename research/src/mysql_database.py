from __future__ import annotations

import argparse
import os
from pathlib import Path

from build_database import (
    EXPECTED_INSERTS,
    build_problem_metadata,
    clean_create_table_sql,
    expected_table_names,
    infer_insert_schemas,
    write_problem_metadata,
)
from eval import EvaluationExecutionError, QueryResult


def quote_identifier(identifier: str) -> str:
    return "`" + identifier.replace("`", "``") + "`"


def create_table_statement(table: str, columns: list[dict]) -> str:
    definitions = []
    for column in columns:
        nullability = "NULL" if column["nullable"] else "NOT NULL"
        definitions.append(
            f"{quote_identifier(column['name'])} {column['type']} {nullability}"
        )
    return f"CREATE TABLE {quote_identifier(table)} ({', '.join(definitions)}) CHARACTER SET utf8mb4"


def _statements(sql: str):
    for statement in sql.split(";"):
        statement = statement.strip()
        if statement:
            yield statement


def _mysql_error_code(error: Exception) -> int | None:
    try:
        return int(error.args[0])
    except (IndexError, TypeError, ValueError):
        return None


def build_problem_database(connection, sql_dir: Path, reset: bool = False) -> dict:
    schemas, inferred_counts = infer_insert_schemas(sql_dir)
    required_tables = expected_table_names(sql_dir)
    if inferred_counts != EXPECTED_INSERTS[:8]:
        raise ValueError(f"Unexpected insert totals for Problems 1–8: {inferred_counts}")

    with connection.cursor() as cursor:
        cursor.execute("CREATE DATABASE IF NOT EXISTS sqlsearchdata CHARACTER SET utf8mb4")
        cursor.execute("USE sqlsearchdata")
        if reset:
            cursor.execute("SHOW TABLES")
            existing_tables = [row[0] for row in cursor.fetchall()]
            cursor.execute("SET FOREIGN_KEY_CHECKS = 0")
            for table in existing_tables:
                cursor.execute(f"DROP TABLE {quote_identifier(table)}")
            cursor.execute("SET FOREIGN_KEY_CHECKS = 1")

        for table, columns in schemas.items():
            cursor.execute(create_table_statement(table, columns))

        create_tables = clean_create_table_sql(
            (sql_dir / "createTables.sql").read_text(encoding="utf-8-sig")
        )
        for statement in _statements(create_tables):
            try:
                cursor.execute(statement)
            except Exception as error:
                if _mysql_error_code(error) != 1050:
                    raise

        inserted_by_problem = []
        for problem_number in range(1, 11):
            script = (sql_dir / f"Problem{problem_number}.sql").read_text(encoding="utf-8-sig")
            script = "\n".join(
                line for line in script.splitlines() if not line.lstrip().startswith("--")
            )
            inserted = 0
            for statement in _statements(script):
                cursor.execute(statement)
                inserted += 1
            if inserted != EXPECTED_INSERTS[problem_number - 1]:
                raise ValueError(
                    f"Problem {problem_number} inserted {inserted} rows; "
                    f"expected {EXPECTED_INSERTS[problem_number - 1]}"
                )
            inserted_by_problem.append(inserted)

        cursor.execute("SHOW TABLES")
        table_names = [row[0] for row in cursor.fetchall()]
        missing_tables = required_tables - set(table_names)
        unexpected_tables = set(table_names) - required_tables
        if missing_tables or unexpected_tables:
            raise ValueError(
                f"Problem database table mismatch; missing={sorted(missing_tables)}, "
                f"unexpected={sorted(unexpected_tables)}"
            )
        row_counts = {}
        for table in table_names:
            cursor.execute(f"SELECT COUNT(*) FROM {quote_identifier(table)}")
            row_counts[table] = cursor.fetchone()[0]
    connection.commit()
    return {"inserted_by_problem": inserted_by_problem, "row_counts": row_counts}


def verify_reference_solutions(connection, problems: list[dict]) -> None:
    from eval import Problem, TestCase, level1

    executor = MySQLExecutor(connection)
    with connection.cursor() as cursor:
        cursor.execute("USE sqlsearchdata")
    for item in problems:
        problem = Problem(
            item["name"],
            tuple(
                TestCase(tuple(case["source_tables"]), case["destination_table"])
                for case in item["test_cases"]
            ),
            compare_as_multiset=item["compare_as_multiset"],
        )
        result = level1(item["reference_solution"], problem, executor.execute)
        if result["status"] != "pass":
            raise RuntimeError(
                f"Reference for {item['name']} failed Level 1: {result['error_message']}"
            )


def create_judge_account(admin_connection, password: str) -> None:
    with admin_connection.cursor() as cursor:
        cursor.execute(
            "CREATE USER IF NOT EXISTS 'judge'@'%' IDENTIFIED BY %s",
            (password,),
        )
        cursor.execute("GRANT SELECT ON sqlsearchdata.* TO 'judge'@'%'")
        cursor.execute("GRANT SELECT ON sqlsearchdata_renamed.* TO 'judge'@'%'")
    admin_connection.commit()


class MySQLExecutor:
    def __init__(self, connection, timeout_seconds: int = 10):
        self.connection = connection
        self.timeout_seconds = timeout_seconds

    def execute(self, query: str | None) -> QueryResult:
        if not isinstance(query, str) or not query.strip():
            raise EvaluationExecutionError(1064, "Query is empty")
        try:
            with self.connection.cursor() as cursor:
                cursor.execute(f"SET SESSION max_execution_time = {int(self.timeout_seconds * 1000)}")
                cursor.execute(query)
                if cursor.description is None:
                    raise EvaluationExecutionError(1142, "Read-only judge accepts SELECT queries only")
                columns = tuple(description[0] for description in cursor.description)
                rows = tuple(tuple(row) for row in cursor.fetchall())
                return QueryResult(columns, rows)
        except EvaluationExecutionError:
            raise
        except Exception as error:
            raise EvaluationExecutionError(_mysql_error_code(error), str(error)) from error


def _load_config(path: Path) -> dict:
    import yaml

    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _connect(settings: dict, read_timeout: int = 10):
    import pymysql

    password_env = settings["password_env"]
    password = os.environ.get(password_env)
    if not password:
        raise RuntimeError(f"Set {password_env} in the environment")
    return pymysql.connect(
        host=settings["host"],
        port=int(settings["port"]),
        user=settings["user"],
        password=password,
        database=settings["database"],
        charset="utf8mb4",
        autocommit=False,
        read_timeout=read_timeout,
        write_timeout=read_timeout,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path(__file__).parents[1] / "config.yaml")
    parser.add_argument("--sql-dir", type=Path)
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args()
    config = _load_config(args.config)
    sql_dir = args.sql_dir or Path(__file__).parents[1] / "data" / "raw" / "SQLRepair" / "sqlsearcher" / "sql"
    output = Path(__file__).parents[1] / "data" / "processed" / "problems.json"

    connection = _connect(config["database"]["admin"])
    try:
        summary = build_problem_database(connection, sql_dir, reset=args.reset)
        create_judge_account(connection, os.environ[config["database"]["judge"]["password_env"]])
    finally:
        connection.close()
    problems = build_problem_metadata(sql_dir)
    judge_connection = _connect(config["database"]["judge"])
    try:
        verify_reference_solutions(judge_connection, problems)
    finally:
        judge_connection.close()
    write_problem_metadata(sql_dir, output)
    print(f"Built {len(summary['row_counts'])} tables; wrote {output}")


if __name__ == "__main__":
    main()
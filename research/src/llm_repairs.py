from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import time
from datetime import datetime, timezone
from pathlib import Path

import sqlglot
from sqlglot import exp
from sqlglot.diff import diff

from mysql_database import _connect, _load_config, quote_identifier


PROMPT_VERSION = "beyond-test-cases-v1"
SYSTEM_MESSAGE = "You repair SQL queries written by students learning SQL."
INSTRUCTIONS = (
    "Repair the student's query so that, for every example, it returns exactly the expected output "
    "in the same row order, with column names that match the header of the expected output exactly, "
    "including letter case. Change as little of the student's query as possible and keep the student's "
    "approach. Use the table and column names exactly as written in the schema, MySQL 8 syntax and a "
    "single SELECT statement. Answer only with JSON: "
    '{"repaired_sql": "...", "changed_clauses": ["..."]}.'
)


def _literal(value) -> str:
    if value is None:
        return "NULL"
    return str(value).replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def _format_table(columns: list[str], rows: list[tuple]) -> str:
    lines = ["| " + " | ".join(_literal(value) for value in columns) + " |"]
    lines.extend("| " + " | ".join(_literal(value) for value in row) + " |" for row in rows)
    return "\n".join(lines)


def _table_data(connection, table: str, schema: str):
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT * FROM {quote_identifier(schema)}.{quote_identifier(table)}")
        columns = [description[0] for description in cursor.description]
        rows = cursor.fetchall()
    return columns, rows


def build_prompt(
    connection,
    problem: dict,
    statement: str,
    error_code: int | None,
    error_message: str | None,
    schema: str = "sqlsearchdata",
):
    first_sources = problem["test_cases"][0]["source_tables"]
    schema_blocks = []
    for table in first_sources:
        with connection.cursor() as cursor:
            cursor.execute(f"SHOW CREATE TABLE {quote_identifier(schema)}.{quote_identifier(table)}")
            create_statement = cursor.fetchone()[1]
        schema_blocks.append(create_statement)

    example_blocks = [
        "In every example, the source table(s) are called "
        + ", ".join(first_sources)
        + "."
    ]
    for index, case in enumerate(problem["test_cases"], start=1):
        example_blocks.append(f"Example {index}:")
        for visible_name, actual_name in zip(first_sources, case["source_tables"], strict=True):
            columns, rows = _table_data(connection, actual_name, schema)
            example_blocks.append(f"Source table {visible_name}:\n{_format_table(columns, rows)}")
        expected_columns, expected_rows = _table_data(connection, case["destination_table"], schema)
        example_blocks.append(
            "Expected output:\n" + _format_table(expected_columns, expected_rows)
        )

    error_block = ""
    if error_code is not None:
        error_block = f"\nMySQL error {error_code}: {error_message or ''}"
    user_message = (
        "Schema:\n"
        + "\n\n".join(schema_blocks)
        + "\n\nExamples:\n"
        + "\n\n".join(example_blocks)
        + "\n\nStudent query:\n"
        + statement
        + error_block
        + "\n\n"
        + INSTRUCTIONS
    )
    return SYSTEM_MESSAGE, user_message


def parse_model_answer(response: str) -> dict:
    payload = json.loads(response)
    if not isinstance(payload, dict) or not isinstance(payload.get("repaired_sql"), str):
        raise ValueError("Response JSON must contain a string repaired_sql")
    changed = payload.get("changed_clauses", [])
    if not isinstance(changed, list) or not all(isinstance(item, str) for item in changed):
        raise ValueError("changed_clauses must be a list of strings")
    statements = sqlglot.parse(payload["repaired_sql"], read="mysql")
    if len(statements) != 1 or not isinstance(statements[0], exp.Select):
        raise ValueError("Repair must be one SELECT statement")
    statement = statements[0]
    if statement.args.get("with_") or statement.args.get("_next"):
        raise ValueError("Repair must be a single SELECT without CTE or UNION")
    return {
        "query": statement.sql(dialect="mysql"),
        "changed_clauses": changed,
    }


def _token_distance(left: str, right: str) -> int:
    from sqlglot import Dialect

    tokenizer = Dialect.get_or_raise("mysql").tokenizer()
    left_tokens = [(token.token_type.name, token.text.upper()) for token in tokenizer.tokenize(left)]
    right_tokens = [(token.token_type.name, token.text.upper()) for token in tokenizer.tokenize(right)]
    previous = list(range(len(right_tokens) + 1))
    for left_index, left_token in enumerate(left_tokens, start=1):
        current = [left_index]
        for right_index, right_token in enumerate(right_tokens, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[right_index] + 1,
                    previous[right_index - 1] + (left_token != right_token),
                )
            )
        previous = current
    return previous[-1]


def edit_script_distance(student: str, candidate: str) -> tuple[int, str]:
    try:
        left = sqlglot.parse_one(student, read="mysql")
        right = sqlglot.parse_one(candidate, read="mysql")
        return sum(type(action).__name__ != "Keep" for action in diff(left, right)), "sqlglot_diff"
    except Exception:
        return _token_distance(student, candidate), "token_levenshtein"


def rank_candidates(student: str, candidates: list[dict]) -> list[dict]:
    unique = {}
    for candidate in candidates:
        formatted = candidate["query"]
        if formatted in unique:
            continue
        distance, measure = edit_script_distance(student, formatted)
        unique[formatted] = {
            **candidate,
            "edit_script_length": distance,
            "distance_measure": measure,
        }
    return sorted(unique.values(), key=lambda item: (item["edit_script_length"], item["query"]))[:3]


def select_pilot_groups(submissions: list[dict], seed: int = 42, per_problem: int = 10) -> list[dict]:
    unique = {}
    for record in submissions:
        if record.get("in_e_all"):
            unique.setdefault(record["group_id"], record)
    randomizer = random.Random(seed)
    selected = []
    for problem in (3, 9):
        pool = [record for record in unique.values() if int(record["problem"]) == problem]
        if len(pool) < per_problem:
            raise ValueError(f"Pilot needs {per_problem} unique groups for Problem {problem}; found {len(pool)}")
        selected.extend(randomizer.sample(pool, per_problem))
    return selected


def _transient(error: Exception) -> bool:
    status = getattr(error, "status_code", None)
    return status in {408, 409, 425, 429} or status is None or status >= 500


def _call_model(client, model: str, messages: list[dict], temperature: float, max_tokens: int, timeout: int):
    started = time.monotonic()
    transient_retries = 0
    while True:
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=timeout,
            )
            elapsed_ms = round((time.monotonic() - started) * 1000)
            return response, elapsed_ms, transient_retries
        except Exception as error:
            if not _transient(error) or transient_retries >= 3:
                raise
            time.sleep(min(2 ** transient_retries, 8))
            transient_retries += 1


def _client(model_settings: dict, timeout: int):
    from openai import OpenAI

    key_name = model_settings.get("api_key_env")
    api_key = os.environ.get(key_name) if key_name else None
    if not api_key:
        raise RuntimeError(f"Set API key environment variable {key_name}")
    if not model_settings.get("model") or not model_settings.get("endpoint"):
        raise RuntimeError("Set the model and endpoint in research/config.yaml before calling an LLM")
    return OpenAI(
        api_key=api_key,
        base_url=model_settings["endpoint"],
        timeout=timeout,
        max_retries=0,
    )


def _call_record(**fields):
    return {"timestamp_utc": datetime.now(timezone.utc).isoformat(), **fields}


def run_model(
    connection,
    model_name: str,
    model_settings: dict,
    groups: list[dict],
    problems: dict[int, dict],
    error_by_group: dict[str, tuple[int | None, str | None]],
    output_path: Path,
    log_path: Path,
    config: dict,
    schema: str = "sqlsearchdata",
) -> list[dict]:
    timeout = int(config["request_timeout_seconds"])
    client = _client(model_settings, timeout)
    generated = []
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8", newline="\n") as logs:
        for group in groups:
            problem = problems[int(group["problem"])]
            code, message = error_by_group.get(group["group_id"], (None, None))
            system, prompt = build_prompt(
                connection, problem, group.get("statement") or "", code, message, schema
            )
            candidates = []
            failures = []
            call_temperatures = [0.0, 0.7, 0.7]
            for call_index, temperature in enumerate(call_temperatures, start=1):
                valid_answer = None
                for invalid_retry in range(int(config["invalid_answer_retries"]) + 1):
                    started_at = datetime.now(timezone.utc).isoformat()
                    try:
                        response, latency_ms, retries = _call_model(
                            client,
                            model_settings["model"],
                            [
                                {"role": "system", "content": system},
                                {"role": "user", "content": prompt},
                            ],
                            temperature,
                            int(config["max_output_tokens"]),
                            timeout,
                        )
                        text = response.choices[0].message.content or ""
                        usage = response.usage
                        try:
                            valid_answer = parse_model_answer(text)
                        except Exception as error:
                            failures.append(str(error))
                            logs.write(
                                json.dumps(
                                    _call_record(
                                        prompt_version=PROMPT_VERSION,
                                        model_name=model_name,
                                        model_id=model_settings["model"],
                                        group_id=group["group_id"],
                                        call_index=call_index,
                                        temperature=temperature,
                                        started_at=started_at,
                                        prompt=prompt,
                                        response=text,
                                        input_tokens=getattr(usage, "prompt_tokens", None),
                                        output_tokens=getattr(usage, "completion_tokens", None),
                                        latency_ms=latency_ms,
                                        transient_retries=retries,
                                        invalid_answer_retry=invalid_retry,
                                        failure=str(error),
                                    ),
                                    ensure_ascii=False,
                                )
                                + "\n"
                            )
                            logs.flush()
                            continue
                        logs.write(
                            json.dumps(
                                _call_record(
                                    prompt_version=PROMPT_VERSION,
                                    model_name=model_name,
                                    model_id=model_settings["model"],
                                    group_id=group["group_id"],
                                    call_index=call_index,
                                    temperature=temperature,
                                    started_at=started_at,
                                    prompt=prompt,
                                    response=text,
                                    input_tokens=getattr(usage, "prompt_tokens", None),
                                    output_tokens=getattr(usage, "completion_tokens", None),
                                    latency_ms=latency_ms,
                                    transient_retries=retries,
                                    invalid_answer_retry=invalid_retry,
                                    failure=None,
                                ),
                                ensure_ascii=False,
                            )
                            + "\n"
                        )
                        logs.flush()
                        break
                    except Exception as error:
                        failures.append(str(error))
                        logs.write(
                            json.dumps(
                                _call_record(
                                    prompt_version=PROMPT_VERSION,
                                    model_name=model_name,
                                    model_id=model_settings.get("model"),
                                    group_id=group["group_id"],
                                    call_index=call_index,
                                    temperature=temperature,
                                    started_at=started_at,
                                    prompt=prompt,
                                    response=None,
                                    latency_ms=None,
                                    transient_retries=None,
                                    invalid_answer_retry=invalid_retry,
                                    failure=str(error),
                                ),
                                ensure_ascii=False,
                            )
                            + "\n"
                        )
                        logs.flush()
                        break
                if valid_answer:
                    candidates.append(valid_answer)

            group_candidates = rank_candidates(group.get("statement") or "", candidates)
            generated.append(
                {
                    "method": model_name,
                    "group_id": group["group_id"],
                    "source_group_id": group.get("source_group_id", group["group_id"]),
                    "problem": int(group["problem"]),
                    "student_query": group.get("statement"),
                    "candidates": [
                        {"candidate_id": index, **candidate}
                        for index, candidate in enumerate(group_candidates, start=1)
                    ],
                    "no_candidate_reason": "; ".join(failures) if not group_candidates else None,
                }
            )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in generated),
        encoding="utf-8",
        newline="\n",
    )
    return generated


def _prompt_hash() -> str:
    return hashlib.sha256((PROMPT_VERSION + SYSTEM_MESSAGE + INSTRUCTIONS).encode("utf-8")).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--pilot", action="store_true")
    mode.add_argument("--full", action="store_true")
    parser.add_argument("--config", type=Path, default=Path(__file__).parents[1] / "config.yaml")
    parser.add_argument("--model", action="append", choices=("llm_a", "llm_b"))
    parser.add_argument("--renamed", action="store_true", help="Run on E_clean with renamed identifiers")
    args = parser.parse_args()
    research_root = Path(__file__).parents[1]
    config = _load_config(args.config)
    processed = research_root / "data" / "processed"
    submission_file = "submissions_renamed.jsonl" if args.renamed else "submissions.jsonl"
    problem_file = "problems_renamed.json" if args.renamed else "problems.json"
    submissions = [json.loads(line) for line in (processed / submission_file).read_text(encoding="utf-8").splitlines() if line]
    problems = {int(item["problem"]): item for item in json.loads((processed / problem_file).read_text(encoding="utf-8"))}
    group_map = {}
    for record in submissions:
        if record.get("in_e_clean" if args.renamed else "in_e_all"):
            group_map.setdefault(record["group_id"], record)
    groups = list(group_map.values())
    if args.pilot:
        groups = select_pilot_groups(submissions, int(config["seed"]))
    else:
        marker = research_root / "logs" / "llm" / "prompt.sha256"
        if not marker.exists() or marker.read_text(encoding="ascii").strip() != _prompt_hash():
            raise RuntimeError("Run the pilot and freeze this prompt before starting the full LLM run")

    error_by_group = {}
    for record in submissions:
        if record.get("mysql_error_code") is not None:
            error_by_group.setdefault(
                record["group_id"],
                (record["mysql_error_code"], record.get("mysql_error_message")),
            )

    database_settings = dict(config["database"]["judge"])
    database_schema = "sqlsearchdata_renamed" if args.renamed else "sqlsearchdata"
    database_settings["database"] = database_schema
    connection = _connect(database_settings)
    selected_models = args.model or ["llm_a", "llm_b"]
    try:
        for model_name in selected_models:
            settings = config["llm"][model_name]
            suffix = "pilot_" if args.pilot else ""
            if args.renamed:
                output_path = research_root / "outputs" / "renaming" / f"{model_name}_candidates.jsonl"
                log_path = research_root / "logs" / "llm" / f"renamed_{model_name}_calls.jsonl"
            else:
                output_path = research_root / "outputs" / "llm" / f"{suffix}{model_name}_candidates.jsonl"
                log_path = research_root / "logs" / "llm" / f"{model_name}_calls.jsonl"
            run_model(
                connection,
                model_name,
                settings,
                groups,
                problems,
                error_by_group,
                output_path,
                log_path,
                config["llm"],
                schema=database_schema,
            )
    finally:
        connection.close()

    if args.pilot and set(selected_models) == {"llm_a", "llm_b"}:
        marker = research_root / "logs" / "llm" / "prompt.sha256"
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(_prompt_hash() + "\n", encoding="ascii")


if __name__ == "__main__":
    main()
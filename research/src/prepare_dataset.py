from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from build_database import build_problem_metadata
from eval import Problem, TestCase, level1
from mysql_database import MySQLExecutor, _connect, _load_config
from prepare_submissions import prepare_submissions
from submissions import csv_quote_diagnostics, parse_2019_export, parse_2020_exports


def load_benchmark_records(data_dir: Path) -> list[dict]:
    records = []
    records.extend(
        parse_2019_export(
            (data_dir / "216_su19_queries.csv").read_text(encoding="utf-8-sig"),
            "216_su19_queries.csv",
        )
    )
    diagnostics = {}
    for filename in ("216_f20_queries.csv", "326_f20_queries.csv"):
        text = (data_dir / filename).read_text(encoding="utf-8-sig")
        diagnostics[filename] = csv_quote_diagnostics(text)
        records.extend(
            parse_2020_exports(text, filename)
        )
    if len(records) != 2782:
        raise ValueError(f"Loaded {len(records)} submissions; expected 2782")
    fall_2020 = [record for record in records if "f20" in record["file"].lower()]
    inner_quotes = sum(record["had_inner_quotes"] for record in fall_2020)
    null_statements = sum(record["statement"] is None for record in fall_2020)
    malformed_rows = sum(
        item["records_with_11_or_12_fields"] for item in diagnostics.values()
    )
    if (inner_quotes, null_statements, malformed_rows) != (178, 24, 16):
        raise ValueError(
            "Pinned 2020 CSV diagnostics changed: "
            f"inner_quotes={inner_quotes}, null_statements={null_statements}, "
            f"11/12-field rows={malformed_rows}"
        )
    return records


def evaluate_records(records: list[dict], metadata: list[dict], execute) -> dict[int, dict]:
    problems = {
        item["problem"]: Problem(
            name=item["name"],
            test_cases=tuple(
                TestCase(tuple(case["source_tables"]), case["destination_table"])
                for case in item["test_cases"]
            ),
            compare_as_multiset=item["compare_as_multiset"],
        )
        for item in metadata
    }
    return {
        int(record["id"]): level1(
            record["statement"], problems[int(record["problem"])], execute
        )
        for record in records
    }


def write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as output:
        for record in records:
            output.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")


def main() -> None:
    research_root = Path(__file__).parents[1]
    config_path = research_root / "config.yaml"
    config = _load_config(config_path)
    repository = research_root / "data" / "raw" / "SQLRepair"
    data_dir = repository / "data"
    sql_dir = repository / "sqlsearcher" / "sql"
    records = load_benchmark_records(data_dir)
    metadata = build_problem_metadata(sql_dir)
    concepts = {item["problem"]: item["concept"] for item in metadata}

    connection = _connect(
        config["database"]["judge"],
        read_timeout=int(config["execution_timeout_seconds"]),
    )
    try:
        executor = MySQLExecutor(
            connection,
            timeout_seconds=int(config["execution_timeout_seconds"]),
        )
        evaluations = evaluate_records(records, metadata, executor.execute)
    finally:
        connection.close()

    prepared, summary = prepare_submissions(records, evaluations, concepts)
    raw_diagnostics = {
        filename: csv_quote_diagnostics(
            (data_dir / filename).read_text(encoding="utf-8-sig")
        )
        for filename in ("216_f20_queries.csv", "326_f20_queries.csv")
    }
    summary["csv_quote_diagnostics"] = raw_diagnostics
    output_dir = research_root / "data" / "processed"
    write_jsonl(output_dir / "submissions.jsonl", prepared)
    (output_dir / "preparation_report.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
from __future__ import annotations

import argparse
import json
from pathlib import Path

from mysql_database import _connect, _load_config
from rules import repair_query


def _read_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as source:
        return [json.loads(line) for line in source if line.strip()]


def generate_rule_candidates(submissions: list[dict], problems: list[dict], columns_by_table: dict[str, list[str]]) -> list[dict]:
    problems_by_number = {int(problem["problem"]): problem for problem in problems}
    groups = {}
    for submission in submissions:
        if not submission.get("in_e_all"):
            continue
        group_id = submission.get("group_id")
        if group_id in groups:
            continue
        problem = problems_by_number[int(submission["problem"])]
        source_tables = [
            table
            for case in problem["test_cases"]
            for table in case["source_tables"]
        ]
        known_columns = {
            column
            for table in source_tables
            for column in columns_by_table.get(table, [])
        }
        query = submission.get("statement")
        repair = repair_query(
            query,
            known_columns=known_columns,
            known_tables=source_tables,
        )
        groups[group_id] = {
            "method": "rules",
            "group_id": group_id,
            "problem": int(submission["problem"]),
            "student_query": query,
            "candidates": [] if repair["query"] is None else [
                {
                    "candidate_id": 1,
                    "query": repair["query"],
                    "rules": repair["rules"],
                }
            ],
            "no_candidate_reason": repair["reason"],
        }
    return list(groups.values())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path(__file__).parents[1] / "config.yaml")
    args = parser.parse_args()
    research_root = Path(__file__).parents[1]
    config = _load_config(args.config)
    processed = research_root / "data" / "processed"
    submissions = _read_jsonl(processed / "submissions.jsonl")
    problems = json.loads((processed / "problems.json").read_text(encoding="utf-8"))
    source_tables = {
        table
        for problem in problems
        for case in problem["test_cases"]
        for table in case["source_tables"]
    }
    connection = _connect(config["database"]["judge"])
    try:
        columns_by_table = {}
        with connection.cursor() as cursor:
            for table in source_tables:
                cursor.execute(f"SHOW COLUMNS FROM sqlsearchdata.`{table}`")
                columns_by_table[table] = [row[0] for row in cursor.fetchall()]
    finally:
        connection.close()

    candidates = generate_rule_candidates(submissions, problems, columns_by_table)
    output = research_root / "outputs" / "rules" / "candidates.jsonl"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in candidates),
        encoding="utf-8",
        newline="\n",
    )
    print(f"Wrote candidates for {len(candidates)} unique incorrect-query groups to {output}")


if __name__ == "__main__":
    main()
from __future__ import annotations

import argparse
import json
from pathlib import Path

from eval import Problem, TestCase, match_on
from mysql_database import MySQLExecutor, _connect, _load_config
from stress import run_candidate_stress
from validation import validate_candidate
from variants import collect_constants


def _read_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as source:
        return [json.loads(line) for line in source if line.strip()]


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(record, ensure_ascii=False, default=str) + "\n" for record in records),
        encoding="utf-8",
        newline="\n",
    )


def _problem(item: dict) -> Problem:
    return Problem(
        item["name"],
        tuple(
            TestCase(tuple(case["source_tables"]), case["destination_table"])
            for case in item["test_cases"]
        ),
        compare_as_multiset=item["compare_as_multiset"],
    )


def _variant_executor(connection, executor: MySQLExecutor, base_schema: str = "sqlsearchdata"):
    def run(schema: str, query: str, reference: str):
        with connection.cursor() as cursor:
            cursor.execute(f"USE `{schema}`")
        try:
            return match_on(query, reference, executor.execute)
        finally:
            with connection.cursor() as cursor:
                cursor.execute(f"USE `{base_schema}`")

    return run


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path(__file__).parents[1] / "config.yaml")
    parser.add_argument("--method", action="append", help="Method name; may be supplied more than once")
    parser.add_argument("--pilot", action="store_true", help="Validate the fixed pilot candidate files")
    parser.add_argument("--renamed", action="store_true", help="Validate renamed E_clean candidates")
    args = parser.parse_args()
    research_root = Path(__file__).parents[1]
    config = _load_config(args.config)
    processed = research_root / "data" / "processed"
    problem_file = "problems_renamed.json" if args.renamed else "problems.json"
    submission_file = "submissions_renamed.jsonl" if args.renamed else "submissions.jsonl"
    problems = json.loads((processed / problem_file).read_text(encoding="utf-8"))
    submissions = _read_jsonl(processed / submission_file)
    manifest_path = (
        research_root / "outputs" / "renaming" / "variants_manifest.jsonl"
        if args.renamed
        else research_root / "outputs" / "variants" / "manifest.jsonl"
    )
    variants = _read_jsonl(manifest_path)
    candidates_dir = research_root / "outputs"
    selected_methods = args.method or (
        ["llm_a", "llm_b"] if args.pilot or args.renamed else ["rules", "sqlrepair", "llm_a", "llm_b"]
    )
    problem_by_number = {int(item["problem"]): item for item in problems}
    variants_by_problem = {}
    for variant in variants:
        variants_by_problem.setdefault(int(variant["problem"]), []).append(variant)

    problem_constants = collect_constants(problems, submissions)
    database_settings = dict(config["database"]["judge"])
    base_schema = "sqlsearchdata"
    if args.renamed:
        base_schema = "sqlsearchdata_renamed"
        database_settings["database"] = base_schema
    connection = _connect(
        database_settings,
        read_timeout=int(config["execution_timeout_seconds"]),
    )
    admin_connection = _connect(config["database"]["admin"]) if not args.renamed else None
    try:
        with connection.cursor() as cursor:
            cursor.execute(f"USE `{base_schema}`")
        executor = MySQLExecutor(connection, int(config["execution_timeout_seconds"]))
        for method in selected_methods:
            if method in {"llm_a", "llm_b"}:
                if args.renamed:
                    candidate_path = candidates_dir / "renaming" / f"{method}_candidates.jsonl"
                else:
                    candidate_name = f"pilot_{method}_candidates.jsonl" if args.pilot else f"{method}_candidates.jsonl"
                    candidate_path = candidates_dir / "llm" / candidate_name
            else:
                candidate_path = candidates_dir / method / "candidates.jsonl"
            if not candidate_path.exists():
                continue
            candidate_records = _read_jsonl(candidate_path)
            group_results = []
            for candidate_record in candidate_records:
                number = int(candidate_record["problem"])
                problem_item = problem_by_number[number]
                group_results.append(
                    validate_candidate(
                        candidate_record,
                        _problem(problem_item),
                        problem_item["reference_solution"],
                        variants_by_problem.get(number, []),
                        executor.execute,
                        _variant_executor(connection, executor, base_schema),
                    )
                )
                group_result = group_results[-1]
                candidate_by_id = {
                    candidate.get("candidate_id"): candidate
                    for candidate in candidate_record.get("candidates", [])
                }
                for candidate_result in group_result["candidate_results"]:
                    if (
                        candidate_result["level1"]["status"] == "pass"
                        and candidate_result.get("level2")
                        and candidate_result["level2"]["status"] == "pass"
                    ):
                        candidate = dict(candidate_by_id[candidate_result["candidate_id"]])
                        candidate["group_id"] = candidate_record["group_id"]
                        if not args.renamed and admin_connection is not None:
                            stress = run_candidate_stress(
                                admin_connection,
                                connection,
                                executor,
                                problem_item,
                                candidate,
                                problem_constants.get(number, {}),
                            )
                            candidate_result.update(stress)
                group_result["stress_fail"] = any(
                    candidate_result.get("stress_fail") is True
                    for candidate_result in group_result["candidate_results"]
                )

            by_group = {item["group_id"]: item for item in group_results}
            output_records = [
                {"record_type": "group", **result} for result in group_results
            ]
            for submission in submissions:
                if not submission.get("in_e_all"):
                    continue
                status = by_group.get(submission.get("group_id"))
                if status is not None:
                    output_records.append(
                        {
                            "record_type": "submission",
                            "id": submission["id"],
                            "group_id": submission["group_id"],
                            "source_group_id": submission.get("source_group_id"),
                            "method": method,
                            "outcome": status["outcome"],
                            "level1_repair": status["level1_repair"],
                            "validated_repair": status["validated_repair"],
                            "first_accepted_wrong": status["first_accepted_wrong"],
                            "stress_fail": status.get("stress_fail"),
                        }
                    )
            if args.renamed:
                output_name = f"renaming_{method}.jsonl"
            else:
                output_name = f"pilot_{method}.jsonl" if args.pilot else f"{method}.jsonl"
            _write_jsonl(research_root / "outputs" / "validation" / output_name, output_records)
    finally:
        connection.close()
        if admin_connection is not None:
            admin_connection.close()


if __name__ == "__main__":
    main()
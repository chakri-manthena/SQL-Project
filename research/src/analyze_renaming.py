from __future__ import annotations

import argparse
import json
from pathlib import Path

from analyze_results import _participant_bootstrap, mcnemar_pvalue, wilson_interval


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _group_outcomes(records: list[dict], original: bool) -> dict[str, dict]:
    key = "group_id" if original else "source_group_id"
    return {
        record[key]: record
        for record in records
        if record.get("record_type") == "group" and record.get(key)
    }


def _level1(outcome: dict | None) -> bool:
    return bool(
        outcome
        and outcome.get("outcome") in {"validated", "falsely_accepted", "level1_repaired"}
    )


def _level2(outcome: dict | None, problem: int) -> bool:
    return problem != 10 and bool(outcome and outcome.get("outcome") == "validated")


def _interval(successes: int, total: int) -> str:
    interval = wilson_interval(successes, total)
    return "n/a" if interval is None else f"{interval[0]:.1%}–{interval[1]:.1%}"


def _submission_statuses(records: list[dict]) -> dict[int, dict]:
    return {
        int(record["id"]): record
        for record in records
        if record.get("record_type") == "submission"
    }


def build_rq4_report(
    clean_submissions: list[dict],
    original_by_method: dict[str, list[dict]],
    renamed_by_method: dict[str, list[dict]],
    output_path: Path,
    bootstrap_draws: int = 2000,
) -> str:
    group_problem = {}
    for submission in clean_submissions:
        group_problem.setdefault(submission["group_id"], int(submission["problem"]))
    group_ids = sorted(group_problem)
    lines = [
        "# RQ4: Identifier Sensitivity",
        "",
        "Repair rates use E_clean submissions; paired tests use unique E_clean query groups. Problem 10 is excluded from Level 2.",
        "",
        "| Model | Level | Original repair (Wilson 95%) | Renamed repair (Wilson 95%) | Participant bootstrap 95% (original / renamed) | Discordant groups original-only / renamed-only | McNemar p |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for method in ("llm_a", "llm_b"):
        original_rows = original_by_method.get(method)
        renamed_rows = renamed_by_method.get(method)
        if original_rows is None or renamed_rows is None:
            lines.append(f"| {method} | both | unavailable | unavailable | unavailable | unavailable |")
            continue
        original = _group_outcomes(original_rows, original=True)
        renamed = _group_outcomes(renamed_rows, original=False)
        original_submissions = _submission_statuses(original_rows)
        renamed_submissions = _submission_statuses(renamed_rows)
        for level in ("level1", "level2"):
            eligible = [
                group_id
                for group_id in group_ids
                if level == "level1" or group_problem[group_id] != 10
            ]
            original_values = [
                _level1(original.get(group_id))
                if level == "level1"
                else _level2(original.get(group_id), group_problem[group_id])
                for group_id in eligible
            ]
            renamed_values = [
                _level1(renamed.get(group_id))
                if level == "level1"
                else _level2(renamed.get(group_id), group_problem[group_id])
                for group_id in eligible
            ]
            original_successes = sum(original_values)
            renamed_successes = sum(renamed_values)
            original_only, renamed_only, p_value = mcnemar_pvalue(original_values, renamed_values)
            eligible_submissions = [
                record
                for record in clean_submissions
                if level == "level1" or int(record["problem"]) != 10
            ]
            def submission_success(statuses, record):
                outcome = statuses.get(int(record["id"]), {}).get("outcome", "not_repaired")
                return (
                    outcome in {"validated", "falsely_accepted", "level1_repaired"}
                    if level == "level1"
                    else outcome == "validated"
                )
            original_submission_successes = sum(
                submission_success(original_submissions, record) for record in eligible_submissions
            )
            renamed_submission_successes = sum(
                submission_success(renamed_submissions, record) for record in eligible_submissions
            )
            original_bootstrap = _participant_bootstrap(
                eligible_submissions, original_submissions, level, draws=bootstrap_draws
            )
            renamed_bootstrap = _participant_bootstrap(
                eligible_submissions, renamed_submissions, level, draws=bootstrap_draws
            )
            bootstrap_text = (
                "n/a" if original_bootstrap is None or renamed_bootstrap is None
                else f"{original_bootstrap[0]:.1%}–{original_bootstrap[1]:.1%} / "
                f"{renamed_bootstrap[0]:.1%}–{renamed_bootstrap[1]:.1%}"
            )
            lines.append(
                f"| {method} | {level} | {original_submission_successes}/{len(eligible_submissions)} "
                f"({_interval(original_submission_successes, len(eligible_submissions))}) | "
                f"{renamed_submission_successes}/{len(eligible_submissions)} "
                f"({_interval(renamed_submission_successes, len(eligible_submissions))}) | "
                f"{bootstrap_text} | {original_only}/{renamed_only} | {p_value:.4g} |"
            )
    lines.extend(
        [
            "",
            "A decrease after renaming is consistent with identifier-dependent behavior; it does not by itself establish memorization.",
            "Repair rates use E_clean submissions; paired tests count each source query group once. Wilson intervals are descriptive, with participant-level cluster bootstrap intervals as the primary uncertainty estimate.",
        ]
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).parents[1])
    args = parser.parse_args()
    root = args.root
    submissions = _read_jsonl(root / "data" / "processed" / "submissions.jsonl")
    clean = [record for record in submissions if record.get("in_e_clean")]
    original_by_method = {}
    renamed_by_method = {}
    for method in ("llm_a", "llm_b"):
        original_path = root / "outputs" / "validation" / f"{method}.jsonl"
        renamed_path = root / "outputs" / "validation" / f"renaming_{method}.jsonl"
        original_by_method[method] = _read_jsonl(original_path) if original_path.exists() else None
        renamed_by_method[method] = _read_jsonl(renamed_path) if renamed_path.exists() else None
    output = root / "outputs" / "rq4_renaming.md"
    build_rq4_report(clean, original_by_method, renamed_by_method, output)
    print(f"Wrote {output}")


if __name__ == "__main__":
    main()
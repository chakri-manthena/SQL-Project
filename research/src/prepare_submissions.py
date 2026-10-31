from __future__ import annotations

import hashlib
import re
from collections import Counter
from datetime import datetime


SYNTAX_CATEGORIES = {
    1064: "parse_error",
    1054: "unknown_column",
    1146: "unknown_table",
    1052: "ambiguous_column",
    1111: "invalid_group_function",
}


def normalize_query(statement: str | None) -> str:
    if not isinstance(statement, str):
        return ""
    normalized = statement.strip()
    if normalized.endswith(";"):
        normalized = normalized[:-1].rstrip()
    return normalized


def _group_key(problem: int, statement: str | None) -> tuple[int, str]:
    return problem, normalize_query(statement)


def _group_id(key: tuple[int, str]) -> str:
    problem, statement = key
    digest = hashlib.sha256(statement.encode("utf-8")).hexdigest()[:16]
    return f"p{problem}_{digest}"


def _mysql_error_category(code: int | None) -> str:
    return SYNTAX_CATEGORIES.get(code, "other_syntax")


def _starts_with_select(statement: str | None) -> bool:
    return isinstance(statement, str) and statement.lstrip().upper().startswith("SELECT")


def _timestamp_key(record: dict):
    value = record["submit_time"]
    try:
        return datetime.fromisoformat(value).isoformat(), int(record["id"])
    except (TypeError, ValueError):
        return str(value), int(record["id"])


def prepare_submissions(
    records: list[dict],
    evaluations: dict[int, dict],
    concepts: dict[int, str],
) -> tuple[list[dict], dict]:
    """Attach evaluator outcomes and form E_all, E_clean, and query groups."""
    prepared = []
    for source in records:
        record = dict(source)
        submission_id = int(record["id"])
        if submission_id not in evaluations:
            raise ValueError(f"Missing Level 1 result for submission {submission_id}")
        evaluation = evaluations[submission_id]
        correct = evaluation.get("status") == "pass"
        error_code = evaluation.get("error_code")
        label_only = bool(evaluation.get("label_only", False))
        statement = record.get("statement")
        error_kind = None if correct else (
            "syntax" if statement is None or error_code is not None else "semantic"
        )
        if error_kind == "syntax":
            error_category = _mysql_error_category(error_code)
        elif label_only:
            error_category = "label_only"
        elif error_kind == "semantic":
            try:
                error_category = concepts[int(record["problem"])]
            except KeyError as error:
                raise ValueError(f"No concept configured for Problem {record['problem']}") from error
        else:
            error_category = None

        record.update(
            {
                "is_correct": correct,
                "error_kind": error_kind,
                "mysql_error_code": error_code,
                "mysql_error_message": evaluation.get("error_message"),
                "error_category": error_category,
                "label_only": label_only,
                "in_e_all": not correct,
                "in_e_clean": False,
                "group_id": None,
            }
        )
        prepared.append(record)

    fall_2020 = [record for record in prepared if "f20" in record["file"].lower()]
    flag_disagreements = [
        record["id"]
        for record in fall_2020
        if record["correct_flag"] is None or record["is_correct"] != record["correct_flag"]
    ]
    if flag_disagreements:
        raise ValueError(
            f"Level 1 disagrees with {len(flag_disagreements)} Fall 2020 flags; "
            f"first IDs: {flag_disagreements[:10]}"
        )

    group_ids = {}
    for record in prepared:
        if not record["in_e_all"]:
            continue
        key = _group_key(int(record["problem"]), record["statement"])
        group_ids.setdefault(key, _group_id(key))
        record["group_id"] = group_ids[key]

    by_participant_problem: dict[tuple[str, int], list[dict]] = {}
    for record in prepared:
        if record["in_e_all"]:
            key = (str(record["participant"]), int(record["problem"]))
            by_participant_problem.setdefault(key, []).append(record)

    repeated_ids = set()
    for participant_records in by_participant_problem.values():
        ordered = sorted(participant_records, key=_timestamp_key)
        previous_statement = object()
        for record in ordered:
            statement = normalize_query(record["statement"])
            if statement == previous_statement:
                repeated_ids.add(record["id"])
            previous_statement = statement

    for record in prepared:
        record["in_e_clean"] = bool(
            record["in_e_all"]
            and _starts_with_select(record["statement"])
            and not record["label_only"]
            and record["id"] not in repeated_ids
        )

    incorrect = [record for record in prepared if record["in_e_all"]]
    summary = {
        "submission_count": len(prepared),
        "correct_count": sum(record["is_correct"] for record in prepared),
        "syntax_count": sum(record["error_kind"] == "syntax" for record in prepared),
        "semantic_count": sum(record["error_kind"] == "semantic" for record in prepared),
        "label_only_count": sum(record["label_only"] for record in prepared),
        "e_all_count": len(incorrect),
        "e_clean_count": sum(record["in_e_clean"] for record in prepared),
        "unique_query_groups": len(group_ids),
        "fall_2020_count": len(fall_2020),
        "fall_2020_flag_agreement": len(fall_2020) - len(flag_disagreements),
        "error_categories": dict(Counter(record["error_category"] for record in incorrect)),
    }
    return prepared, summary
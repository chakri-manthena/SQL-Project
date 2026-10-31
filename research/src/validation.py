from __future__ import annotations

from typing import Callable

from eval import Problem, level1, match_on


def validate_group(
    candidate_record: dict,
    problem: Problem,
    reference: str,
    variants: list[dict],
    execute_level1: Callable[[str], object],
    execute_variant: Callable[[str, str], object],
) -> dict:
    candidate_results = []
    for candidate in candidate_record.get("candidates", []):
        level1_result = level1(candidate.get("query"), problem, execute_level1)
        level2_result = None
        failed_variants = []
        if level1_result["status"] == "pass" and problem.name != "Problem 10":
            built_variants = [variant for variant in variants if variant.get("status") == "built"]
            if not built_variants:
                level2_result = {
                    "status": "fail",
                    "error_code": None,
                    "error_message": "No built independent variants are available",
                }
            else:
                level2_result = {"status": "pass", "error_code": None, "error_message": None}
                for variant in built_variants:
                    result = execute_variant(
                        variant["schema"],
                        candidate["query"],
                        reference,
                    )
                    if result["status"] != "pass":
                        failed_variants.append(variant["schema"])
                        if level2_result["status"] == "pass":
                            level2_result = result
        candidate_results.append(
            {
                "candidate_id": candidate.get("candidate_id"),
                "query": candidate.get("query"),
                "level1": level1_result,
                "level2": level2_result,
                "failing_variants": failed_variants,
            }
        )

    first_level1 = next(
        (result for result in candidate_results if result["level1"]["status"] == "pass"),
        None,
    )
    validated = next(
        (
            result
            for result in candidate_results
            if result["level1"]["status"] == "pass"
            and (
                problem.name == "Problem 10"
                or result["level2"] is not None
                and result["level2"]["status"] == "pass"
            )
        ),
        None,
    )

    if problem.name == "Problem 10":
        outcome = "level1_repaired" if first_level1 else "not_repaired"
    elif validated:
        outcome = "validated"
    elif first_level1:
        outcome = "falsely_accepted"
    else:
        outcome = "not_repaired"

    return {
        "method": candidate_record.get("method"),
        "group_id": candidate_record.get("group_id"),
        "source_group_id": candidate_record.get("source_group_id"),
        "problem": int(candidate_record.get("problem", 0)),
        "candidate_results": candidate_results,
        "outcome": outcome,
        "level1_repair": first_level1.get("candidate_id") if first_level1 else None,
        "validated_repair": validated.get("candidate_id") if validated else None,
        "first_accepted_wrong": bool(
            problem.name != "Problem 10"
            and first_level1
            and first_level1["level2"] is not None
            and first_level1["level2"]["status"] != "pass"
        ),
    }


def validate_candidate(
    candidate_record: dict,
    problem: Problem,
    reference: str,
    variants: list[dict],
    execute_level1: Callable[[str], object],
    execute_variant: Callable[[str, str], object],
) -> dict:
    """Public wrapper used by tests and the MySQL batch runner."""
    return validate_group(
        candidate_record,
        problem,
        reference,
        variants,
        execute_level1,
        execute_variant,
    )
from __future__ import annotations

import argparse
import csv
import json
import random
from collections import defaultdict
from pathlib import Path

import sqlglot
from sqlglot import exp

from llm_repairs import edit_script_distance


COMPONENTS = (
    "select_list",
    "from_tables",
    "join_conditions",
    "where_predicates",
    "group_by",
    "order_by",
    "distinct",
)
ANNOTATION_LABELS = {
    "preserves_student_approach": 0,
    "partially_changes_approach": 1,
    "reproduces_reference_approach": 2,
}


def _parse(query: str):
    return sqlglot.parse_one(query, read="mysql")


def _normalized(expression) -> str:
    return expression.sql(dialect="mysql", pretty=False).upper()


def _expressions(expressions) -> tuple[str, ...]:
    if expressions is None:
        return ()
    return tuple(_normalized(expression) for expression in expressions)


def clause_components(query: str) -> dict[str, object]:
    statement = _parse(query)
    select = statement if isinstance(statement, exp.Select) else statement.find(exp.Select)
    if select is None:
        raise ValueError("Query has no SELECT expression")

    from_clause = select.args.get("from_")
    from_tables = []
    if from_clause is not None:
        from_tables.extend(table.name.upper() for table in from_clause.find_all(exp.Table))
    for join in select.args.get("joins") or []:
        from_tables.extend(table.name.upper() for table in join.find_all(exp.Table))
    join_conditions = tuple(
        sorted(_normalized(join.args["on"]) for join in select.args.get("joins") or [] if join.args.get("on") is not None)
    )

    where = select.args.get("where")
    predicates = []
    if where is not None:
        predicates = sorted(
            _normalized(node)
            for node in where.find_all(exp.Binary)
            if not isinstance(node, (exp.And, exp.Or))
        )

    group = select.args.get("group")
    order = select.args.get("order")
    distinct = select.args.get("distinct") is not None
    return {
        "select_list": _expressions(select.expressions),
        "from_tables": tuple(sorted(from_tables)),
        "join_conditions": join_conditions,
        "where_predicates": tuple(predicates),
        "group_by": _expressions(group.expressions if group is not None else None),
        "order_by": _expressions(order.expressions if order is not None else None),
        "distinct": distinct,
    }


def _normalized_edit_distance(left: str, right: str) -> dict:
    distance, measure = edit_script_distance(left, right)
    try:
        left_tree = _parse(left)
        right_tree = _parse(right)
        denominator = sum(1 for _ in left_tree.walk()) + sum(1 for _ in right_tree.walk())
    except Exception:
        from sqlglot import Dialect

        tokenizer = Dialect.get_or_raise("mysql").tokenizer()
        denominator = max(
            len(tokenizer.tokenize(left)),
            len(tokenizer.tokenize(right)),
            1,
        )
    return {
        "distance": distance,
        "normalized": distance / denominator if denominator else 0.0,
        "measure": measure,
    }


def compute_minimality(student: str | None, repair: str, reference: str) -> dict:
    result = {
        "repair_to_reference": _normalized_edit_distance(repair, reference),
        "identical_to_reference": False,
        "student_comparable": False,
        "repair_to_student": None,
        "student_component_similarity": None,
        "reference_component_similarity": None,
        "component_comparisons": {},
    }
    try:
        formatted_repair = _parse(repair).sql(dialect="mysql")
        formatted_reference = _parse(reference).sql(dialect="mysql")
        result["identical_to_reference"] = formatted_repair == formatted_reference
    except Exception:
        pass

    try:
        repair_components = clause_components(repair)
        reference_components = clause_components(reference)
    except Exception:
        repair_components = None
        reference_components = None
    if repair_components is not None and reference_components is not None:
        result["reference_component_similarity"] = sum(
            repair_components[key] == reference_components[key] for key in COMPONENTS
        ) / len(COMPONENTS)
        result["component_comparisons"] = {
            key: {
                "matches_reference": repair_components[key] == reference_components[key],
                "repair": repair_components[key],
                "reference": reference_components[key],
            }
            for key in COMPONENTS
        }

    if not student:
        return result
    try:
        result["repair_to_student"] = _normalized_edit_distance(student, repair)
        student_components = clause_components(student)
        if repair_components is None:
            repair_components = clause_components(repair)
        result["student_comparable"] = True
        result["student_component_similarity"] = sum(
            repair_components[key] == student_components[key] for key in COMPONENTS
        ) / len(COMPONENTS)
        for key in COMPONENTS:
            result["component_comparisons"].setdefault(key, {})[
                "matches_student"
            ] = repair_components[key] == student_components[key]
    except Exception:
        result["student_comparable"] = False
    return result


def quadratic_weighted_kappa(first: list[int], second: list[int], categories: int = 3) -> float | None:
    if len(first) != len(second):
        raise ValueError("Annotator arrays must have equal lengths")
    if not first:
        return None
    observed = [[0] * categories for _ in range(categories)]
    first_counts = [0] * categories
    second_counts = [0] * categories
    for left, right in zip(first, second, strict=True):
        if left not in range(categories) or right not in range(categories):
            raise ValueError("Annotation values must be valid category indices")
        observed[left][right] += 1
        first_counts[left] += 1
        second_counts[right] += 1
    total = len(first)
    observed_disagreement = 0.0
    expected_disagreement = 0.0
    for left in range(categories):
        for right in range(categories):
            weight = ((left - right) / (categories - 1)) ** 2
            observed_disagreement += weight * observed[left][right] / total
            expected_disagreement += weight * first_counts[left] * second_counts[right] / (total * total)
    if expected_disagreement == 0:
        return 1.0 if observed_disagreement == 0 else None
    return 1 - observed_disagreement / expected_disagreement


def select_annotation_sample(records: list[dict], per_model: int = 25, seed: int = 42) -> list[dict]:
    rng = random.Random(seed)
    sample = []
    for method in ("llm_a", "llm_b"):
        by_problem = defaultdict(list)
        for record in records:
            if record["method"] == method:
                by_problem[int(record["problem"])].append(record)
        for values in by_problem.values():
            rng.shuffle(values)
        chosen = []
        problem_numbers = sorted(by_problem)
        while len(chosen) < per_model and any(by_problem.values()):
            for problem in problem_numbers:
                if by_problem[problem] and len(chosen) < per_model:
                    chosen.append(by_problem[problem].pop())
        sample.extend(chosen)
    return sample


def _candidate_index(records: list[dict]) -> dict[tuple[str, str], dict]:
    return {
        (record["group_id"], record["method"]): record
        for record in records
        if record.get("group_id") and record.get("method")
    }


def gather_validated_repairs(research_root: Path) -> list[dict]:
    processed = research_root / "data" / "processed"
    submissions = [
        json.loads(line)
        for line in (processed / "submissions.jsonl").read_text(encoding="utf-8").splitlines()
        if line
    ]
    problems = {
        int(item["problem"]): item
        for item in json.loads((processed / "problems.json").read_text(encoding="utf-8"))
    }
    repairs = []
    for method in ("llm_a", "llm_b"):
        candidates_path = research_root / "outputs" / "llm" / f"{method}_candidates.jsonl"
        validation_path = research_root / "outputs" / "validation" / f"{method}.jsonl"
        if not candidates_path.exists() or not validation_path.exists():
            continue
        candidate_groups = _candidate_index(
            [json.loads(line) for line in candidates_path.read_text(encoding="utf-8").splitlines() if line]
        )
        group_results = [
            json.loads(line)
            for line in validation_path.read_text(encoding="utf-8").splitlines()
            if line and json.loads(line).get("record_type") == "group"
        ]
        submissions_by_group = {}
        for submission in submissions:
            if submission.get("in_e_all"):
                submissions_by_group.setdefault(submission["group_id"], submission)
        for validation in group_results:
            number = int(validation["problem"])
            candidate_id = validation.get("validated_repair")
            if number == 10:
                candidate_id = validation.get("level1_repair")
            if candidate_id is None:
                continue
            source = candidate_groups.get((validation["group_id"], method))
            if source is None:
                continue
            candidate = next(
                (item for item in source.get("candidates", []) if item.get("candidate_id") == candidate_id),
                None,
            )
            if candidate is None:
                continue
            submission = submissions_by_group.get(validation["group_id"], {})
            repairs.append(
                {
                    "method": method,
                    "group_id": validation["group_id"],
                    "problem": number,
                    "student_query": submission.get("statement"),
                    "repair": candidate["query"],
                    "reference": problems[number]["reference_solution"],
                }
            )
    return repairs


def write_rq3_outputs(research_root: Path, annotation_paths: tuple[Path, Path] | None = None) -> None:
    repairs = gather_validated_repairs(research_root)
    metrics = [
        {
            **repair,
            **compute_minimality(repair["student_query"], repair["repair"], repair["reference"]),
        }
        for repair in repairs
    ]
    output_dir = research_root / "outputs"
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "rq3_metrics.jsonl").write_text(
        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in metrics),
        encoding="utf-8",
        newline="\n",
    )
    sample = select_annotation_sample(metrics)
    sample_path = output_dir / "rq3_annotation_sample.jsonl"
    sample_path.write_text(
        "".join(
            json.dumps(
                {
                    "group_id": item["group_id"],
                    "method": item["method"],
                    "problem": item["problem"],
                    "student_query": item["student_query"],
                    "repair": item["repair"],
                    "reference": item["reference"],
                    "annotator_1": "",
                    "annotator_2": "",
                },
                ensure_ascii=False,
            )
            + "\n"
            for item in sample
        ),
        encoding="utf-8",
        newline="\n",
    )
    annotation_kappa = None
    if annotation_paths and all(path.exists() for path in annotation_paths):
        labels = []
        for path in annotation_paths:
            with path.open(encoding="utf-8-sig", newline="") as source:
                rows = {row["group_id"]: ANNOTATION_LABELS[row["annotation"]] for row in csv.DictReader(source)}
            labels.append(rows)
        common = sorted(set(labels[0]) & set(labels[1]))
        annotation_kappa = quadratic_weighted_kappa(
            [labels[0][group] for group in common],
            [labels[1][group] for group in common],
        )

    by_method = defaultdict(list)
    for item in metrics:
        by_method[item["method"]].append(item)
    lines = [
        "# RQ3: Repair Minimality",
        "",
        "| Method | Problem | Repairs | Mean d_student raw / normalized | Mean d_reference raw / normalized | Student token fallback pairs | Clause similarity to student | Clause similarity to reference | Identical to reference |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for method in ("llm_a", "llm_b"):
        for problem_number in [*range(1, 11), "All"]:
            rows = [
                row for row in by_method[method]
                if problem_number == "All" or int(row["problem"]) == problem_number
            ]
            comparable = [row for row in rows if row["student_comparable"]]
            student_raw = [row["repair_to_student"]["distance"] for row in comparable]
            student_normalized = [row["repair_to_student"]["normalized"] for row in comparable]
            reference_raw = [row["repair_to_reference"]["distance"] for row in rows]
            reference_normalized = [row["repair_to_reference"]["normalized"] for row in rows]
            student_similarity = [row["student_component_similarity"] for row in comparable]
            reference_similarity = [
                row["reference_component_similarity"]
                for row in rows
                if row["reference_component_similarity"] is not None
            ]

            def mean(values):
                return "n/a" if not values else f"{sum(values) / len(values):.3f}"

            student_edit = f"{mean(student_raw)} / {mean(student_normalized)}"
            reference_edit = f"{mean(reference_raw)} / {mean(reference_normalized)}"
            student_clause = "n/a" if not student_similarity else f"{sum(student_similarity) / len(student_similarity):.1%}"
            reference_clause = "n/a" if not reference_similarity else f"{sum(reference_similarity) / len(reference_similarity):.1%}"
            identical = "n/a" if not rows else f"{sum(row['identical_to_reference'] for row in rows)}/{len(rows)}"
            fallback_pairs = sum(
                row.get("repair_to_student", {}).get("measure") == "token_levenshtein"
                for row in rows
                if row.get("repair_to_student")
            )
            lines.append(
                f"| {method} | {problem_number} | {len(rows)} | {student_edit} | {reference_edit} | "
                f"{fallback_pairs} | {student_clause} | {reference_clause} | {identical} |"
            )
    lines.extend(
        [
            "",
            f"Annotation sample: {len(sample)} validated repairs (up to 25 per model), in `{sample_path.name}`.",
            "Annotators independently label each repair as `preserves_student_approach`, `partially_changes_approach`, or `reproduces_reference_approach`.",
            f"Quadratic-weighted Cohen's kappa: {annotation_kappa if annotation_kappa is not None else 'pending two annotation CSVs'}.",
            "Student queries that do not parse are excluded from student-relative clause similarity and are reported separately in `rq3_metrics.jsonl`.",
        ]
    )
    (output_dir / "rq3_minimality.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--annotator-1", type=Path)
    parser.add_argument("--annotator-2", type=Path)
    args = parser.parse_args()
    paths = (args.annotator_1, args.annotator_2) if args.annotator_1 and args.annotator_2 else None
    write_rq3_outputs(Path(__file__).parents[1], paths)


if __name__ == "__main__":
    main()
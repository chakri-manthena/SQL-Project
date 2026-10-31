from __future__ import annotations

import hashlib
import json
import math
import random
from collections import Counter, defaultdict
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlglot import exp, parse_one


@dataclass(frozen=True)
class VariantPlan:
    problem: int
    family: str
    base: tuple[str, ...]
    index: int
    seed: int

    @property
    def schema(self) -> str:
        base_name = "_".join(self.base)
        return f"var_p{self.problem}_{self.family.lower()}_{base_name}_{self.index}"


def _families(problem: int) -> tuple[str, ...]:
    if problem == 1:
        return ("F1", "F2", "F5")
    if problem == 2:
        return ("F1", "F3", "F5")
    if problem == 3:
        return ("F1", "F2", "F5")
    if problem == 4:
        return ("F1", "F2", "F5")
    if problem in (5, 6):
        return ("F1", "F2", "F3", "F4", "F5")
    if problem == 7:
        return ("F1", "F2", "F5")
    if problem == 8:
        return ("F1", "F5", "F6")
    if problem == 9:
        return ("F1", "F2", "F5", "F7")
    return ()


def plan_variants(problems: list[dict], seed: int = 42) -> list[VariantPlan]:
    """Plan the fixed independent suite using only problem metadata."""
    plans = []
    for problem in problems:
        number = int(problem["problem"])
        for case_index, case in enumerate(problem["test_cases"]):
            base = tuple(case["source_tables"])
            for family in _families(number):
                copies = 3 if family == "F1" else 1
                for index in range(1, copies + 1):
                    variant_seed = seed + number * 10000 + case_index * 100 + sum(map(ord, family)) + index
                    plans.append(VariantPlan(number, family, base, index, variant_seed))
    return plans


def _column_name(row: dict, column: str) -> str | None:
    return next((name for name in row if name.lower() == column.lower()), None)


def _clone(row: dict) -> dict:
    return dict(row)


def _copy_with_value(rows: list[dict], column: str, value: Any, rng: random.Random) -> dict | None:
    if not rows:
        return None
    row = _clone(rng.choice(rows))
    key = _column_name(row, column)
    if key is None:
        return None
    row[key] = value
    return row


def extract_constants(queries: list[str | None]) -> dict[str, list[Any]]:
    """Collect constants compared with columns, retaining the ten most frequent per column."""
    student_counts: dict[str, Counter] = defaultdict(Counter)
    reference_values: dict[str, list[Any]] = defaultdict(list)
    for query_index, query in enumerate(queries):
        if not query:
            continue
        try:
            statement = parse_one(query, read="mysql")
        except Exception:
            continue
        where = statement.args.get("where")
        if where is None:
            continue

        def record_constant(column: str, literal: exp.Literal) -> None:
            key = column.upper()
            value = literal.this
            if query_index == 0:
                if value not in reference_values[key]:
                    reference_values[key].append(value)
            else:
                student_counts[key][value] += 1

        for comparison in where.find_all(exp.Binary):
            left, right = comparison.this, comparison.expression
            if isinstance(left, exp.Column) and isinstance(right, exp.Literal):
                record_constant(left.name, right)
            elif isinstance(right, exp.Column) and isinstance(left, exp.Literal):
                record_constant(right.name, left)

        for predicate in where.find_all(exp.In):
            if isinstance(predicate.this, exp.Column):
                for literal in predicate.expressions:
                    if isinstance(literal, exp.Literal):
                        record_constant(predicate.this.name, literal)

        for predicate in where.find_all(exp.Between):
            if isinstance(predicate.this, exp.Column):
                for literal in (predicate.args.get("low"), predicate.args.get("high")):
                    if isinstance(literal, exp.Literal):
                        record_constant(predicate.this.name, literal)

    constants = {}
    for column in set(reference_values) | set(student_counts):
        selected = list(reference_values[column])
        selected.extend(
            value
            for value, _ in student_counts[column].most_common(10)
            if value not in selected
        )
        constants[column] = selected
    return constants


def _all_constants(queries_by_problem: dict[int, list[str | None]], references: dict[int, str]) -> dict[int, dict[str, list[Any]]]:
    result = {}
    for number, reference in references.items():
        result[number] = extract_constants(
            [reference, *queries_by_problem.get(number, [])]
        )
    return result


def _type_for(column_types: dict[str, str], column: str) -> str:
    return next((value for name, value in column_types.items() if name.lower() == column.lower()), "")


def _numeric_delta(type_name: str) -> Decimal:
    if type_name.upper().startswith("DECIMAL"):
        scale = int(type_name.rsplit(",", 1)[1].rstrip(")"))
        return Decimal(1).scaleb(-scale)
    return Decimal(1)


def _numeric_boundaries(
    rows_by_table: dict[str, list[dict]],
    constants: dict[str, list[Any]],
    types_by_table: dict[str, dict[str, str]],
    rng: random.Random,
) -> dict[str, list[dict]]:
    output = {table: [_clone(row) for row in rows] for table, rows in rows_by_table.items()}
    for table, rows in rows_by_table.items():
        types = types_by_table.get(table, {})
        for column, values in constants.items():
            key = _column_name(rows[0], column) if rows else None
            if key is None:
                continue
            type_name = _type_for(types, column)
            if not (type_name.upper().startswith(("INT", "DECIMAL", "NUMERIC"))):
                continue
            delta = _numeric_delta(type_name)
            for value in values:
                try:
                    center = Decimal(str(value))
                except Exception:
                    continue
                for boundary in (center - delta, center, center + delta):
                    if type_name.upper().startswith("INT"):
                        boundary_value: Any = int(boundary)
                    else:
                        boundary_value = float(boundary)
                    row = _copy_with_value(rows, column, boundary_value, rng)
                    if row is not None:
                        output[table].append(row)
    return output


def _string_variants(
    rows_by_table: dict[str, list[dict]], constants: dict[str, list[Any]], rng: random.Random
) -> dict[str, list[dict]]:
    output = {table: [_clone(row) for row in rows] for table, rows in rows_by_table.items()}
    for table, rows in rows_by_table.items():
        for column, values in constants.items():
            if not rows or _column_name(rows[0], column) is None:
                continue
            existing = []
            key = _column_name(rows[0], column)
            for row in rows:
                if row[key] is not None and row[key] not in existing:
                    existing.append(row[key])
            for value in values:
                if str(value).lstrip("+-").replace(".", "", 1).isdigit():
                    continue
                matching = _copy_with_value(rows, column, value, rng)
                if matching is not None:
                    output[table].append(matching)
                alternatives = [current for current in existing if str(current) != str(value)]
                if alternatives:
                    contrasting = _copy_with_value(rows, column, rng.choice(alternatives), rng)
                    if contrasting is not None:
                        output[table].append(contrasting)
    return output


def _predicate_combinations(
    problem: int, rows_by_table: dict[str, list[dict]], rng: random.Random
) -> dict[str, list[dict]]:
    output = {table: [_clone(row) for row in rows] for table, rows in rows_by_table.items()}
    for table, rows in rows_by_table.items():
        if not rows:
            continue
        for mask in range(4 if problem == 5 else 6):
            row = _clone(rng.choice(rows))
            if problem == 5:
                rank_column = _column_name(row, "MRRANK_RANK")
                tty_column = _column_name(row, "TTY")
                if rank_column:
                    row[rank_column] = 379 if mask & 1 else 380
                if tty_column:
                    row[tty_column] = "CD" if mask & 2 else "SY"
            else:
                rank_column = _column_name(row, "MRRANK_RANK")
                tty_column = _column_name(row, "TTY")
                if rank_column:
                    row[rank_column] = 401 if mask >= 3 else 400
                if tty_column:
                    row[tty_column] = ("SY", "PT", "XX")[mask % 3]
            output[table].append(row)
    return output


def _duplicate_rows(
    problem: int, rows_by_table: dict[str, list[dict]], rng: random.Random
) -> dict[str, list[dict]]:
    output = {table: [_clone(row) for row in rows] for table, rows in rows_by_table.items()}
    for table, rows in rows_by_table.items():
        if not rows:
            continue
        duplicate_count = max(2, math.ceil(len(rows) * 0.2))
        for row in rng.choices(rows, k=duplicate_count):
            output[table].append(_clone(row))
        if problem == 7:
            sver_column = _column_name(rows[0], "SVER")
            other_columns = [column for column in rows[0] if column.lower() != "sver"]
            for row in rows:
                if sver_column is None or not other_columns:
                    continue
                varied = _clone(row)
                target = other_columns[0]
                alternatives = [candidate[target] for candidate in rows if candidate[target] != row[target]]
                if alternatives:
                    varied[target] = rng.choice(alternatives)
                    output[table].append(varied)
    return output


def _ordering_ties(rows_by_table: dict[str, list[dict]], rng: random.Random) -> dict[str, list[dict]]:
    output = {table: [_clone(row) for row in rows] for table, rows in rows_by_table.items()}
    for table, rows in rows_by_table.items():
        if not rows:
            continue
        tui_column = _column_name(rows[0], "TUI")
        cui_column = _column_name(rows[0], "CUI")
        if tui_column is None or cui_column is None:
            continue
        existing_cuis = list(dict.fromkeys(row[cui_column] for row in rows))
        cuis_by_tui = defaultdict(set)
        for row in rows:
            cuis_by_tui[row[tui_column]].add(row[cui_column])
        for tui, used_cuis in cuis_by_tui.items():
            alternatives = [cui for cui in existing_cuis if cui not in used_cuis]
            if alternatives:
                row = _clone(rng.choice([item for item in rows if item[tui_column] == tui]))
                row[cui_column] = rng.choice(alternatives)
                output[table].append(row)
        rng.shuffle(output[table])
    return output


def _join_variants(rows_by_table: dict[str, list[dict]], rng: random.Random) -> dict[str, list[dict]]:
    output = {table: [_clone(row) for row in rows] for table, rows in rows_by_table.items()}
    india = output.get("india", [])
    juliett = output.get("juliett", [])
    if not india or not juliett:
        return output
    india_cui = _column_name(india[0], "CUI")
    juliett_cui = _column_name(juliett[0], "CUI")
    cvf = _column_name(india[0], "CVF")
    if not india_cui or not juliett_cui or not cvf:
        return output
    india_keys = {row[india_cui] for row in india}
    juliett_keys = {row[juliett_cui] for row in juliett}
    unmatched_india = _clone(rng.choice(india))
    unmatched_india[india_cui] = "C9999901"
    output["india"].append(unmatched_india)
    unmatched_juliett = _clone(rng.choice(juliett))
    unmatched_juliett[juliett_cui] = "C9999902"
    output["juliett"].append(unmatched_juliett)

    shared = "C9999903"
    for _ in range(2):
        left = _clone(rng.choice(india))
        left[india_cui] = shared
        output["india"].append(left)
        right = _clone(rng.choice(juliett))
        right[juliett_cui] = shared
        output["juliett"].append(right)

    for value in (255, 256, 257, None):
        row = _clone(rng.choice(india))
        row[india_cui] = "C99999" + str(10 + (value or 0))[-2:]
        row[cvf] = value
        output["india"].append(row)
    return output


def build_variant_rows(
    plan: VariantPlan,
    base_rows: dict[str, list[dict]],
    constants: dict[str, list[Any]],
    types_by_table: dict[str, dict[str, str]],
) -> dict[str, list[dict]]:
    """Construct one independent variant; this function accepts no candidate inputs."""
    rng = random.Random(plan.seed)
    rows = {table: [_clone(row) for row in values] for table, values in base_rows.items()}
    if plan.family == "F1":
        return {
            table: rng.sample(values, max(1, math.ceil(len(values) / 2)))
            for table, values in rows.items()
        }
    if plan.family == "F2":
        return _numeric_boundaries(rows, constants, types_by_table, rng)
    if plan.family == "F3":
        return _string_variants(rows, constants, rng)
    if plan.family == "F4":
        return _predicate_combinations(plan.problem, rows, rng)
    if plan.family == "F5":
        return _duplicate_rows(plan.problem, rows, rng)
    if plan.family == "F6":
        return _ordering_ties(rows, rng)
    if plan.family == "F7":
        return _join_variants(rows, rng)
    raise ValueError(f"Unknown variant family: {plan.family}")


def map_base_to_visible_names(
    plan: VariantPlan,
    visible_tables: tuple[str, ...],
    rows_by_base: dict[str, list[dict]],
    types_by_base: dict[str, dict[str, str]],
) -> tuple[dict[str, list[dict]], dict[str, dict[str, str]]]:
    if len(plan.base) != len(visible_tables):
        raise ValueError("Base and visible test cases must have the same number of tables")
    return (
        {visible: rows_by_base[base] for base, visible in zip(plan.base, visible_tables, strict=True)},
        {visible: types_by_base[base] for base, visible in zip(plan.base, visible_tables, strict=True)},
    )


def expected_output_hash(result: dict) -> str:
    encoded = json.dumps(result, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def manifest_record(
    plan: VariantPlan,
    rows: dict[str, list[dict]],
    expected_output: Any | None,
    dropped_reason: str | None = None,
) -> dict:
    record = {
        "schema": plan.schema,
        "problem": plan.problem,
        "family": plan.family,
        "base": list(plan.base),
        "index": plan.index,
        "seed": plan.seed,
        "row_counts": {table: len(table_rows) for table, table_rows in rows.items()},
        "status": "dropped" if dropped_reason else "built",
    }
    if dropped_reason:
        record["dropped_reason"] = dropped_reason
    else:
        record["expected_output_sha256"] = expected_output_hash(expected_output)
    return record


def collect_constants(problems: list[dict], submissions: list[dict]) -> dict[int, dict[str, list[Any]]]:
    queries_by_problem = defaultdict(list)
    for submission in submissions:
        if submission.get("in_e_all"):
            queries_by_problem[int(submission["problem"])].append(submission.get("statement"))
    references = {int(problem["problem"]): problem["reference_solution"] for problem in problems}
    return _all_constants(queries_by_problem, references)
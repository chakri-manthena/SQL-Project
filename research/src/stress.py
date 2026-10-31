from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass
from typing import Any

from eval import EvaluationExecutionError, match_on
from mysql_database import MySQLExecutor, quote_identifier
from variants import _numeric_boundaries, _string_variants, extract_constants


@dataclass(frozen=True)
class StressVariantPlan:
	problem: int
	family: str
	base: tuple[str, ...]
	index: int
	seed: int
	group_id: str
	candidate_id: int

	@property
	def schema(self) -> str:
		digest = hashlib.sha256(
			f"{self.group_id}:{self.candidate_id}".encode("utf-8")
		).hexdigest()[:10]
		base_name = "_".join(self.base)
		return f"var_p{self.problem}_stress_{digest}_{self.family.lower()}_{base_name}_{self.index}"


def build_candidate_stress_rows(
	problem_number: int,
	candidate_query: str,
	group_id: str,
	candidate_id: int,
	base_tables: tuple[str, ...],
	base_rows: dict[str, list[dict]],
	problem_constants: dict[str, list[Any]],
	types_by_table: dict[str, dict[str, str]],
	seed: int = 42,
) -> list[tuple[StressVariantPlan, dict[str, list[dict]]]]:
	"""Build candidate-targeted boundary/string variants, separate from the independent suite."""
	candidate_constants = extract_constants([candidate_query])
	novel = {
		column: [
			value
			for value in values
			if str(value) not in {str(existing) for existing in problem_constants.get(column, [])}
		]
		for column, values in candidate_constants.items()
	}
	novel = {column: values for column, values in novel.items() if values}
	if not novel:
		return []

	numeric = {}
	strings = {}
	for column, values in novel.items():
		column_type = next(
			(
				type_name
				for table in base_tables
				for name, type_name in types_by_table.get(table, {}).items()
				if name.lower() == column.lower()
			),
			"",
		).upper()
		if column_type.startswith(("INT", "DECIMAL", "NUMERIC")):
			numeric[column] = values
		else:
			strings[column] = values

	plans = []
	ordinal = 0
	for family, family_constants in (("F2", numeric), ("F3", strings)):
		if not family_constants:
			continue
		ordinal += 1
		variant_seed = seed + int(hashlib.sha256(group_id.encode("utf-8")).hexdigest()[:8], 16) + candidate_id + ordinal
		plan = StressVariantPlan(
			problem_number,
			family,
			base_tables,
			ordinal,
			variant_seed,
			group_id,
			candidate_id,
		)
		rng = random.Random(variant_seed)
		if family == "F2":
			rows = _numeric_boundaries(base_rows, family_constants, types_by_table, rng)
		else:
			rows = _string_variants(base_rows, family_constants, rng)
		plans.append((plan, rows))
	return plans


def _read_base(connection, tables: tuple[str, ...]):
	rows_by_table = {}
	types_by_table = {}
	with connection.cursor() as cursor:
		for table in tables:
			cursor.execute(f"SHOW COLUMNS FROM sqlsearchdata.{quote_identifier(table)}")
			types_by_table[table] = {row[0]: row[1] for row in cursor.fetchall()}
			cursor.execute(f"SELECT * FROM sqlsearchdata.{quote_identifier(table)}")
			columns = [item[0] for item in cursor.description]
			rows_by_table[table] = [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]
	return rows_by_table, types_by_table


def run_candidate_stress(
	admin_connection,
	judge_connection,
	executor: MySQLExecutor,
	problem: dict,
	candidate: dict,
	problem_constants: dict[str, list[Any]],
	base_schema: str = "sqlsearchdata",
) -> dict:
	if int(problem["problem"]) == 10:
		return {"stress_fail": None, "stress_variants": [], "reason": "Problem 10 is Level 1 only"}
	candidate_id = int(candidate["candidate_id"])
	query = candidate["query"]
	group_id = candidate["group_id"]
	base_tables = tuple(problem["test_cases"][0]["source_tables"])
	base_rows, types_by_table = _read_base(admin_connection, base_tables)
	plans = build_candidate_stress_rows(
		int(problem["problem"]),
		query,
		group_id,
		candidate_id,
		base_tables,
		base_rows,
		problem_constants,
		types_by_table,
	)

	from build_variant_suite import _insert_variant_rows, _recreate_schema

	results = []
	for plan, rows in plans:
		_recreate_schema(admin_connection, judge_connection, plan.schema)
		counts, skipped = _insert_variant_rows(admin_connection, plan.schema, rows)
		with judge_connection.cursor() as cursor:
			cursor.execute(f"USE `{plan.schema}`")
		try:
			result = match_on(query, problem["reference_solution"], executor.execute)
		except Exception as error:
			result = {
				"status": "fail",
				"error_code": None,
				"error_message": str(error),
			}
		finally:
			with judge_connection.cursor() as cursor:
				cursor.execute(f"USE `{base_schema}`")
		results.append(
			{
				"schema": plan.schema,
				"family": plan.family,
				"seed": plan.seed,
				"row_counts": counts,
				"skipped_rows": skipped,
				"result": result,
			}
		)
	return {
		"stress_fail": any(item["result"]["status"] != "pass" for item in results),
		"stress_variants": results,
		"reason": None if results else "No novel candidate constants to target",
	}
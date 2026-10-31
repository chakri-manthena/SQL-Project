from __future__ import annotations

import csv
import io
import re


_RECORD_START = re.compile(r"(?m)(?=^\d+,NULL,)")
_PROBLEM_NUMBER = re.compile(r"^Problem\s+(\d+)$", re.IGNORECASE)
_PROBLEM_BY_DESTINATION = {
    table: problem
    for problem, table in enumerate(
        (
            "alphad",
            "bravod",
            "charlied",
            "deltad",
            "echod",
            "foxtrotd",
            "golfd",
            "hoteld",
            "indiad",
            "kilod",
        ),
        start=1,
    )
}


def _parse_bool(value: str, field: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"true", "1"}:
        return True
    if normalized in {"false", "0"}:
        return False
    raise ValueError(f"Invalid {field} flag: {value!r}")


def _strip_outer_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        return value[1:-1]
    return value


def parse_2020_exports(text: str, filename: str) -> list[dict]:
    """Parse the unescaped-quote 2020 export without CSV quote interpretation."""
    records = []
    for raw_record in _RECORD_START.split(text.lstrip("\ufeff")):
        record = raw_record.strip("\r\n")
        if not re.match(r"^\d+,NULL,", record):
            continue

        split_record = record.rsplit(",", 5)
        if len(split_record) != 6:
            raise ValueError(f"Malformed record in {filename}: expected five trailing fields")
        statement_prefix, submit_time, can_be_displayed, correct, count, problem_text = split_record
        prefix_fields = statement_prefix.split(",", 4)
        if len(prefix_fields) != 5:
            raise ValueError(f"Malformed record in {filename}: expected four leading separators")

        submission_id, destination_table, participant, source_table, raw_statement = prefix_fields
        statement_field = raw_statement.strip()
        if len(statement_field) >= 2 and statement_field[0] == '"' and statement_field[-1] == '"':
            statement = statement_field[1:-1]
        elif statement_field.upper() == "NULL":
            statement = None
        else:
            statement = statement_field

        submit_time = _strip_outer_quotes(submit_time)
        problem_text = _strip_outer_quotes(problem_text)
        problem_match = _PROBLEM_NUMBER.fullmatch(problem_text)
        if not problem_match:
            raise ValueError(f"Invalid problem label in {filename}: {problem_text!r}")

        records.append(
            {
                "id": int(submission_id),
                "file": filename,
                "participant": participant,
                "destination_table": destination_table,
                "source_table": source_table,
                "statement": statement,
                "had_inner_quotes": statement is not None and '"' in statement,
                "submit_time": submit_time,
                "can_be_displayed": _parse_bool(can_be_displayed, "canBeDisplayed"),
                "correct_flag": _parse_bool(correct, "correct"),
                "count": int(count),
                "problem": int(problem_match.group(1)),
            }
        )
    return records


def parse_2019_export(text: str, filename: str) -> list[dict]:
    """Read the correctly quoted six-column 2019 CSV export."""
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise ValueError(f"Missing CSV header in {filename}")
    fields = {name.strip().lower(): name for name in reader.fieldnames}
    required = {
        "id",
        "destinationtable",
        "participant",
        "sourcetable",
        "statement",
        "submittime",
    }
    missing = required - fields.keys()
    if missing:
        raise ValueError(f"Missing columns in {filename}: {', '.join(sorted(missing))}")

    records = []
    for row in reader:
        if None in row:
            raise ValueError(f"Unexpected extra CSV field in {filename}")
        destination_table = row[fields["destinationtable"]]
        problem = _PROBLEM_BY_DESTINATION.get(destination_table.lower())
        if problem is None:
            raise ValueError(f"Unknown destination table in {filename}: {destination_table!r}")
        statement = row[fields["statement"]]
        records.append(
            {
                "id": int(row[fields["id"]]),
                "file": filename,
                "participant": row[fields["participant"]],
                "destination_table": destination_table,
                "source_table": row[fields["sourcetable"]],
                "statement": statement,
                "had_inner_quotes": '"' in statement,
                "submit_time": row[fields["submittime"]],
                "can_be_displayed": None,
                "correct_flag": None,
                "count": None,
                "problem": problem,
            }
        )
    return records


def csv_quote_diagnostics(text: str) -> dict:
    field_counts = {}
    for line in text.lstrip("\ufeff").splitlines()[1:]:
        try:
            count = len(next(csv.reader([line])))
        except (csv.Error, StopIteration):
            count = 0
        field_counts[count] = field_counts.get(count, 0) + 1
    return {
        "physical_records": sum(field_counts.values()),
        "field_counts": {str(count): total for count, total in sorted(field_counts.items())},
        "records_with_11_or_12_fields": field_counts.get(11, 0) + field_counts.get(12, 0),
    }
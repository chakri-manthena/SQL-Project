from __future__ import annotations

import argparse
import json
from pathlib import Path

from build_variant_suite import _read_jsonl, write_manifest
from mysql_database import MySQLExecutor, _connect, _load_config
from renaming import prepare_renaming_artifacts, write_json


def _write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(record, ensure_ascii=False, default=str) + "\n" for record in records),
        encoding="utf-8",
        newline="\n",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path(__file__).parents[1] / "config.yaml")
    args = parser.parse_args()
    root = Path(__file__).parents[1]
    config = _load_config(args.config)
    processed = root / "data" / "processed"
    problems = json.loads((processed / "problems.json").read_text(encoding="utf-8"))
    submissions = _read_jsonl(processed / "submissions.jsonl")
    manifest = _read_jsonl(root / "outputs" / "variants" / "manifest.jsonl")
    admin = _connect(config["database"]["admin"])
    judge = _connect(config["database"]["judge"], read_timeout=int(config["execution_timeout_seconds"]))
    try:
        executor = MySQLExecutor(judge, int(config["execution_timeout_seconds"]))
        table_map, column_map, renamed_problems, renamed_submissions, renamed_manifest = prepare_renaming_artifacts(
            admin,
            judge,
            executor,
            problems,
            submissions,
            manifest,
        )
    finally:
        admin.close()
        judge.close()

    write_json(processed / "renaming_map.json", {"tables": table_map, "columns": column_map})
    write_json(processed / "problems_renamed.json", renamed_problems)
    _write_jsonl(processed / "submissions_renamed.jsonl", renamed_submissions)
    write_manifest(root / "outputs" / "renaming" / "variants_manifest.jsonl", renamed_manifest)
    print(
        f"Prepared renamed schemas, {len(renamed_submissions)} E_clean submissions, "
        f"and {len(renamed_manifest)} variant manifest rows"
    )


if __name__ == "__main__":
    main()
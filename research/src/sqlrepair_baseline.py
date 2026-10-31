from pathlib import Path


def write_historical_summary(output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        "# SQLRepair Baseline\n\n"
        "The published SQLRepair result repaired 737 of 2,531 incorrect submissions "
        "(29.1%). This is historical context only: it was measured using the original "
        "tool and judging procedure, not this project's Level 1/Level 2 validators.\n\n"
        "The same-validator SQLRepair Java/Z3 baseline has not been run. No per-problem "
        "or paired comparison is available yet.\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    research_root = Path(__file__).parents[1]
    write_historical_summary(research_root / "outputs" / "sqlrepair" / "summary.md")
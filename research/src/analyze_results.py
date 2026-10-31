from __future__ import annotations

import json
import math
import random
import html
from collections import Counter, defaultdict
from pathlib import Path


HISTORICAL_SQLREPAIR_RATE = (737, 2531)
METHOD_LABELS = {
    "rules": "Rules",
    "sqlrepair": "SQLRepair (same validator)",
    "llm_a": "LLM A",
    "llm_b": "LLM B",
}
PROBLEM_CONCEPTS = {
    1: "Selection",
    2: "Projection and selection",
    3: "Inequality",
    4: "Projection and inequality",
    5: "OR condition",
    6: "AND/OR precedence",
    7: "DISTINCT and inequality",
    8: "Two-key ORDER BY",
    9: "Join and inequality",
    10: "GROUP BY without aggregates",
}


def wilson_interval(successes: int, total: int, z: float = 1.96) -> tuple[float, float] | None:
    if total <= 0:
        return None
    proportion = successes / total
    denominator = 1 + z * z / total
    center = (proportion + z * z / (2 * total)) / denominator
    margin = z * math.sqrt(
        proportion * (1 - proportion) / total + z * z / (4 * total * total)
    ) / denominator
    return max(0.0, center - margin), min(1.0, center + margin)


def _metric_counts(records: list[dict], statuses: dict[int, dict], measure: str) -> tuple[int, int]:
    if measure == "level2":
        records = [record for record in records if int(record["problem"]) != 10]
    denominator = len(records)
    success_outcomes = {"validated", "falsely_accepted", "level1_repaired"}
    successes = 0
    for record in records:
        outcome = statuses.get(int(record["id"]), {}).get("outcome", "not_repaired")
        if measure == "level1" and outcome in success_outcomes:
            successes += 1
        elif measure == "level2" and outcome == "validated":
            successes += 1
    return successes, denominator


def _participant_bootstrap(
    records: list[dict], statuses: dict[int, dict], measure: str, seed: int = 42, draws: int = 2000
) -> tuple[float, float] | None:
    if measure == "level2":
        records = [record for record in records if int(record["problem"]) != 10]
    by_participant = defaultdict(list)
    for record in records:
        by_participant[str(record["participant"])].append(record)
    participants = sorted(by_participant)
    if not participants:
        return None
    rng = random.Random(seed)
    rates = []
    valid_outcomes = {"validated", "falsely_accepted", "level1_repaired"}
    for _ in range(draws):
        sample = [rng.choice(participants) for _ in participants]
        successes = 0
        total = 0
        for participant in sample:
            for record in by_participant[participant]:
                outcome = statuses.get(int(record["id"]), {}).get("outcome", "not_repaired")
                total += 1
                if measure == "level1" and outcome in valid_outcomes:
                    successes += 1
                elif measure == "level2" and outcome == "validated":
                    successes += 1
        if total:
            rates.append(successes / total)
    rates.sort()
    return rates[int(0.025 * (len(rates) - 1))], rates[int(0.975 * (len(rates) - 1))]


def _exact_mcnemar(discordant_first: int, discordant_second: int) -> float:
    total = discordant_first + discordant_second
    if total == 0:
        return 1.0
    tail = sum(math.comb(total, index) for index in range(min(discordant_first, discordant_second) + 1)) / (2**total)
    return min(1.0, 2 * tail)


def mcnemar_pvalue(first: list[bool], second: list[bool]) -> tuple[int, int, float]:
    if len(first) != len(second):
        raise ValueError("Paired outcomes must have equal lengths")
    first_only = sum(left and not right for left, right in zip(first, second, strict=True))
    second_only = sum(right and not left for left, right in zip(first, second, strict=True))
    discordant = first_only + second_only
    if discordant < 25:
        return first_only, second_only, _exact_mcnemar(first_only, second_only)
    statistic = max(abs(first_only - second_only) - 1, 0) ** 2 / discordant
    return first_only, second_only, math.erfc(math.sqrt(statistic / 2))


def holm_adjust(pvalues: list[float]) -> list[float]:
    if not pvalues:
        return []
    order = sorted(range(len(pvalues)), key=lambda index: pvalues[index])
    adjusted = [0.0] * len(pvalues)
    running = 0.0
    count = len(pvalues)
    for rank, index in enumerate(order):
        running = max(running, (count - rank) * pvalues[index])
        adjusted[index] = min(1.0, running)
    return adjusted


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as source:
        return [json.loads(line) for line in source if line.strip()]


def _status_maps(records: list[dict]) -> tuple[dict[int, dict], dict[str, dict]]:
    submissions = {}
    groups = {}
    for record in records:
        if record.get("record_type") == "submission":
            submissions[int(record["id"])] = record
        elif record.get("record_type") == "group":
            groups[record["group_id"]] = record
    return submissions, groups


def _rate(successes: int, total: int) -> str:
    return "n/a" if total == 0 else f"{successes / total:.1%} ({successes}/{total})"


def _wilson_text(successes: int, total: int) -> str:
    interval = wilson_interval(successes, total)
    if interval is None:
        return "n/a"
    return f"{interval[0]:.1%}–{interval[1]:.1%}"


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return ordered[index]


def _svg_text(x: float, y: float, text: str, size: int = 12, anchor: str = "middle") -> str:
    return (
        f'<text x="{x:.1f}" y="{y:.1f}" font-family="Arial,sans-serif" '
        f'font-size="{size}" text-anchor="{anchor}" fill="#263238">'
        f"{html.escape(str(text))}</text>"
    )


def _svg_frame(title: str, width: int = 900, height: int = 520) -> list[str]:
    return [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        _svg_text(width / 2, 30, title, 18),
    ]


def _write_level_rate_figure(path: Path, values: dict[str, tuple[float | None, float | None]]) -> None:
    width, height = 900, 520
    parts = _svg_frame("Figure 1. Level 1 vs Level 2 repair rate", width, height)
    left, top, chart_width, chart_height = 85, 65, 760, 350
    for tick in range(0, 101, 20):
        y = top + chart_height * (1 - tick / 100)
        parts.append(f'<line x1="{left}" y1="{y:.1f}" x2="{left + chart_width}" y2="{y:.1f}" stroke="#d7dee2"/>')
        parts.append(_svg_text(left - 12, y + 4, f"{tick}%", 11, "end"))
    methods = list(values)
    group_width = chart_width / max(1, len(methods))
    colors = ("#087f8c", "#e07a2d")
    legend = (("Level 1", colors[0]), ("Level 2", colors[1]))
    for index, method in enumerate(methods):
        l1, l2 = values[method]
        center = left + group_width * (index + 0.5)
        for series_index, value in enumerate((l1, l2)):
            if value is None:
                continue
            bar_width = 48
            x = center - 52 + series_index * 54
            bar_height = chart_height * max(0, min(1, value))
            y = top + chart_height - bar_height
            parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_width}" height="{bar_height:.1f}" fill="{colors[series_index]}"/>')
            parts.append(_svg_text(x + bar_width / 2, y - 7, f"{value:.1%}", 10))
        parts.append(_svg_text(center, top + chart_height + 24, method, 12))
    for index, (label, color) in enumerate(legend):
        x = left + index * 140
        parts.append(f'<rect x="{x}" y="455" width="14" height="14" fill="{color}"/>')
        parts.append(_svg_text(x + 22, 467, label, 12, "start"))
    if not any(value is not None for pair in values.values() for value in pair):
        parts.append(_svg_text(width / 2, 245, "No validation results available", 16))
    parts.append("</svg>")
    path.write_text("\n".join(parts), encoding="utf-8")


def _false_acceptance_families(groups_by_method: dict[str, dict[str, dict]]) -> dict[str, Counter]:
    counts = {}
    for method, groups in groups_by_method.items():
        family_counts = Counter()
        for group in groups.values():
            if int(group.get("problem", 0)) == 10:
                continue
            for candidate in group.get("candidate_results", []):
                if candidate.get("level1", {}).get("status") != "pass":
                    continue
                if candidate.get("level2", {}).get("status") == "pass":
                    continue
                failed = candidate.get("failing_variants") or []
                first = failed[0] if failed else ""
                family = next((name for name in ("F1", "F2", "F3", "F4", "F5", "F6", "F7") if f"_{name.lower()}_" in first.lower()), None)
                if family:
                    family_counts[family] += 1
                elif candidate.get("level2", {}).get("error_code") is not None:
                    family_counts["execution error"] += 1
                else:
                    family_counts["unknown"] += 1
        counts[method] = family_counts
    return counts


def _write_false_acceptance_figure(path: Path, groups_by_method: dict[str, dict[str, dict]]) -> None:
    width, height = 900, 520
    parts = _svg_frame("Figure 2. First independent variant family catching Level 1 false acceptances", width, height)
    counts = _false_acceptance_families(groups_by_method)
    methods = list(METHOD_LABELS)
    categories = ["F1", "F2", "F3", "F4", "F5", "F6", "F7", "execution error", "unknown"]
    colors = ["#087f8c", "#2d6a9f", "#6b8e23", "#b56576", "#e07a2d", "#7b6d8d", "#5c677d", "#c44536", "#9aa0a6"]
    max_value = max((sum(counts.get(method, {}).values()) for method in methods), default=0)
    max_value = max(1, max_value)
    left, top, chart_width, chart_height = 85, 65, 760, 350
    for tick in range(0, 6):
        y = top + chart_height * (1 - tick / 5)
        amount = max_value * tick / 5
        parts.append(f'<line x1="{left}" y1="{y:.1f}" x2="{left + chart_width}" y2="{y:.1f}" stroke="#d7dee2"/>')
        parts.append(_svg_text(left - 12, y + 4, f"{amount:.0f}", 11, "end"))
    group_width = chart_width / max(1, len(methods))
    for method_index, method in enumerate(methods):
        x = left + method_index * group_width + group_width * 0.2
        bar_width = group_width * 0.58
        y_bottom = top + chart_height
        for category_index, category in enumerate(categories):
            count = counts.get(method, {}).get(category, 0)
            if not count:
                continue
            bar_height = chart_height * count / max_value
            y_bottom -= bar_height
            parts.append(f'<rect x="{x:.1f}" y="{y_bottom:.1f}" width="{bar_width:.1f}" height="{bar_height:.1f}" fill="{colors[category_index]}"/>')
        parts.append(_svg_text(x + bar_width / 2, top + chart_height + 24, method, 11))
    for category_index, category in enumerate(categories):
        x = left + (category_index % 3) * 240
        y = 455 + (category_index // 3) * 19
        parts.append(f'<rect x="{x}" y="{y - 11}" width="12" height="12" fill="{colors[category_index]}"/>')
        parts.append(_svg_text(x + 19, y, category, 10, "start"))
    if not any(counts.get(method) for method in methods):
        parts.append(_svg_text(width / 2, 245, "No candidate validation results available", 16))
    parts.append("</svg>")
    path.write_text("\n".join(parts), encoding="utf-8")


def _write_minimality_figure(path: Path, minimality_records: list[dict]) -> None:
    width, height = 900, 520
    parts = _svg_frame("Figure 3. Edit-script length distributions", width, height)
    metrics = ("repair_to_student", "repair_to_reference")
    colors = ("#087f8c", "#e07a2d")
    values = defaultdict(list)
    for record in minimality_records:
        method = record.get("method", "unknown")
        for metric in metrics:
            item = record.get(metric)
            if item and isinstance(item.get("distance"), (int, float)):
                values[(method, metric)].append(float(item["distance"]))
    methods = [method for method in ("llm_a", "llm_b") if any(values[(method, metric)] for metric in metrics)]
    chart_methods = methods or ["llm_a", "llm_b"]
    maximum = max((value for metric_values in values.values() for value in metric_values), default=1.0)
    maximum = max(1.0, maximum)
    left, top, chart_width, chart_height = 85, 65, 760, 350
    for tick in range(0, 6):
        y = top + chart_height * (1 - tick / 5)
        amount = maximum * tick / 5
        parts.append(f'<line x1="{left}" y1="{y:.1f}" x2="{left + chart_width}" y2="{y:.1f}" stroke="#d7dee2"/>')
        parts.append(_svg_text(left - 12, y + 4, f"{amount:.1f}", 11, "end"))
    group_width = chart_width / max(1, len(chart_methods))
    for method_index, method in enumerate(chart_methods):
        center = left + group_width * (method_index + 0.5)
        for metric_index, metric in enumerate(metrics):
            sample = sorted(values[(method, metric)])
            if not sample:
                continue
            quantile = lambda fraction: sample[min(len(sample) - 1, int(fraction * (len(sample) - 1)))]
            low, q1, median, q3, high = (quantile(value) for value in (0, 0.25, 0.5, 0.75, 1))
            x = center + (-25 if metric_index == 0 else 25)
            to_y = lambda value: top + chart_height * (1 - value / maximum)
            color = colors[metric_index]
            parts.append(f'<line x1="{x}" y1="{to_y(high):.1f}" x2="{x}" y2="{to_y(low):.1f}" stroke="{color}" stroke-width="2"/>')
            parts.append(f'<rect x="{x - 15}" y="{to_y(q3):.1f}" width="30" height="{max(1, to_y(q1) - to_y(q3)):.1f}" fill="{color}" fill-opacity="0.55" stroke="{color}"/>')
            parts.append(f'<line x1="{x - 15}" y1="{to_y(median):.1f}" x2="{x + 15}" y2="{to_y(median):.1f}" stroke="#263238" stroke-width="2"/>')
        parts.append(_svg_text(center, top + chart_height + 24, method, 12))
    for metric_index, metric in enumerate(metrics):
        x = left + metric_index * 210
        label = "to student" if metric == "repair_to_student" else "to reference"
        parts.append(f'<rect x="{x}" y="455" width="14" height="14" fill="{colors[metric_index]}"/>')
        parts.append(_svg_text(x + 22, 467, label, 12, "start"))
    if not values:
        parts.append(_svg_text(width / 2, 245, "Run RQ3 minimality before drawing this figure", 16))
    parts.append("</svg>")
    path.write_text("\n".join(parts), encoding="utf-8")


def _cost_rows(call_logs: dict[str, list[dict]], cost_config: dict | None) -> list[str]:
    rows = [
        "",
        "## Table 8. LLM Cost and Latency",
        "",
        "| Model | Calls | Groups | Median latency/group (ms) | P95 latency/group (ms) | Input tokens / 1,000 groups | Output tokens / 1,000 groups | Estimated actual cost (USD) |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for model in ("llm_a", "llm_b"):
        calls = call_logs.get(model, [])
        by_group = defaultdict(list)
        input_tokens = output_tokens = 0
        for call in calls:
            group_id = call.get("group_id")
            if group_id:
                by_group[group_id].append(call)
            input_tokens += int(call.get("input_tokens") or 0)
            output_tokens += int(call.get("output_tokens") or 0)
        group_latencies = [
            sum(float(call.get("latency_ms") or 0) for call in group_calls)
            for group_calls in by_group.values()
        ]
        median = _percentile(group_latencies, 0.5)
        p95 = _percentile(group_latencies, 0.95)
        groups = len(by_group)
        input_per_thousand = input_tokens * 1000 / groups if groups else None
        output_per_thousand = output_tokens * 1000 / groups if groups else None
        model_cost_config = (cost_config or {}).get(model, {})
        input_price = model_cost_config.get("input_cost_per_1m_tokens_usd")
        output_price = model_cost_config.get("output_cost_per_1m_tokens_usd")
        cost = None
        if input_price is not None and output_price is not None:
            cost = input_tokens * float(input_price) / 1_000_000 + output_tokens * float(output_price) / 1_000_000
        rows.append(
            f"| {METHOD_LABELS[model]} | {len(calls)} | {groups} | "
            f"{'n/a' if median is None else f'{median:.0f}'} | "
            f"{'n/a' if p95 is None else f'{p95:.0f}'} | "
            f"{'n/a' if input_per_thousand is None else f'{input_per_thousand:.0f}'} | "
            f"{'n/a' if output_per_thousand is None else f'{output_per_thousand:.0f}'} | "
            f"{'n/a' if cost is None else f'{cost:.4f}'} |"
        )
    return rows


def _main_metrics(records: list[dict], statuses: dict[int, dict]) -> dict:
    level1_repaired = sum(
        statuses.get(int(record["id"]), {}).get("outcome")
        in {"validated", "falsely_accepted", "level1_repaired"}
        for record in records
    )
    eligible = [record for record in records if int(record["problem"]) != 10]
    level2_repaired = sum(
        statuses.get(int(record["id"]), {}).get("outcome") == "validated"
        for record in eligible
    )
    repaired_p1_9 = [
        record
        for record in eligible
        if statuses.get(int(record["id"]), {}).get("outcome")
        in {"validated", "falsely_accepted"}
    ]
    false_acceptances = sum(
        statuses.get(int(record["id"]), {}).get("outcome") == "falsely_accepted"
        for record in repaired_p1_9
    )
    return {
        "level1": (level1_repaired, len(records)),
        "level2": (level2_repaired, len(eligible)),
        "false_submission": (false_acceptances, len(repaired_p1_9)),
    }


def build_results_report(
    submissions: list[dict],
    validation_by_method: dict[str, list[dict]],
    output_path: Path,
    problem_metadata: list[dict] | None = None,
    bootstrap_draws: int = 2000,
    call_logs: dict[str, list[dict]] | None = None,
    cost_config: dict | None = None,
    minimality_records: list[dict] | None = None,
) -> str:
    all_records = [record for record in submissions if record.get("in_e_all")]
    clean_records = [record for record in submissions if record.get("in_e_clean")]
    status_by_method = {}
    groups_by_method = {}
    testcase_counts = {
        int(item["problem"]): len(item["test_cases"])
        for item in (problem_metadata or [])
    }
    for method, records in validation_by_method.items():
        status_by_method[method], groups_by_method[method] = _status_maps(records)

    lines = [
        "# Beyond the Test Cases: Core Results",
        "",
        "Results are computed from the available validation files. Missing methods or study stages are labeled unavailable; no unrun repair or stress-test outcome is imputed as a success.",
        "",
        "## Table 1. Dataset",
        "",
        "| Problem | Concept | Test cases | E_all | E_clean | Syntax | Semantic | Label-only | Query groups |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for problem in range(1, 11):
        problem_rows = [record for record in all_records if int(record["problem"]) == problem]
        clean_count = sum(int(record["problem"]) == problem for record in clean_records)
        concept = PROBLEM_CONCEPTS[problem]
        groups = len({record.get("group_id") for record in problem_rows})
        lines.append(
            f"| {problem} | {concept} | {testcase_counts.get(problem, 'n/a')} | {len(problem_rows)} | {clean_count} | "
            f"{sum(record.get('error_kind') == 'syntax' for record in problem_rows)} | "
            f"{sum(record.get('error_kind') == 'semantic' for record in problem_rows)} | "
            f"{sum(record.get('label_only', False) for record in problem_rows)} | {groups} |"
        )

    lines.extend(
        [
            "",
            "## Table 2. Main Results",
            "",
            "| Method | Set | Level 1 repair | Level 1 Wilson 95% | Level 2 repair (Problems 1–9) | Level 2 Wilson 95% | False acceptance | Candidate false acceptance | First accepted wrong | Stress failure | Participant bootstrap 95% (L1 / L2) |",
            "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for method in ("sqlrepair", "rules", "llm_a", "llm_b"):
        method_status = status_by_method.get(method, {})
        for set_name, records in (("E_all", all_records), ("E_clean", clean_records)):
            metrics = _main_metrics(records, method_status)
            level1_successes, level1_total = metrics["level1"]
            level2_successes, level2_total = metrics["level2"]
            false_successes, false_total = metrics["false_submission"]
            boot = _participant_bootstrap(
                records, method_status, "level1", seed=42, draws=bootstrap_draws
            )
            boot_level2 = _participant_bootstrap(
                records, method_status, "level2", seed=42, draws=bootstrap_draws
            )
            boot_text = "n/a" if boot is None else f"{boot[0]:.1%}–{boot[1]:.1%}"
            boot_level2_text = "n/a" if boot_level2 is None else f"{boot_level2[0]:.1%}–{boot_level2[1]:.1%}"
            candidate_passes = candidate_failures = 0
            first_wrong = first_count = 0
            stress_failures = stress_tested = 0
            for group in groups_by_method.get(method, {}).values():
                if int(group["problem"]) == 10:
                    continue
                for candidate in group.get("candidate_results", []):
                    if candidate["level1"]["status"] == "pass":
                        candidate_passes += 1
                        candidate_failures += candidate.get("level2", {}).get("status") != "pass"
                    level2_result = candidate.get("level2")
                    if level2_result and level2_result.get("status") == "pass" and candidate.get("stress_fail") is not None:
                        stress_tested += 1
                        stress_failures += bool(candidate["stress_fail"])
                if group.get("level1_repair") is not None:
                    first_count += 1
                    first_wrong += bool(group.get("first_accepted_wrong"))
            candidate_false = _rate(candidate_failures, candidate_passes)
            first_false = _rate(first_wrong, first_count)
            stress_false = _rate(stress_failures, stress_tested)
            status_note = "unavailable" if method not in status_by_method else "n/a"
            false_rate = _rate(false_successes, false_total) if method in status_by_method else status_note
            lines.append(
                f"| {METHOD_LABELS[method]} | {set_name} | {_rate(level1_successes, level1_total) if method in status_by_method else status_note} | "
                f"{_wilson_text(level1_successes, level1_total) if method in status_by_method else status_note} | "
                f"{_rate(level2_successes, level2_total) if method in status_by_method else status_note} | "
                f"{_wilson_text(level2_successes, level2_total) if method in status_by_method else status_note} | "
                f"{false_rate} | {candidate_false if method in status_by_method else status_note} | "
                f"{first_false if method in status_by_method else status_note} | "
                f"{stress_false if method in status_by_method else status_note} | "
                f"{boot_text if method in status_by_method else status_note} / "
                f"{boot_level2_text if method in status_by_method else status_note} |"
            )
    hist_n, hist_d = HISTORICAL_SQLREPAIR_RATE
    lines.append(
        f"| SQLRepair (historical; original protocol) | Published | {_rate(hist_n, hist_d)} | not recomputed | not comparable | n/a | n/a | n/a | n/a | n/a |"
    )

    lines.extend(
        [
            "",
            "## Table 3. Repair Rate by Problem",
            "",
            "| Method | Problem | Level 1 repair | Level 2 repair |",
            "|---|---:|---:|---:|",
        ]
    )
    for method in ("sqlrepair", "rules", "llm_a", "llm_b"):
        method_status = status_by_method.get(method)
        for problem in range(1, 11):
            rows = [record for record in all_records if int(record["problem"]) == problem]
            successes = sum(
                method_status.get(int(record["id"]), {}).get("outcome")
                in {"validated", "falsely_accepted", "level1_repaired"}
                for record in rows
            ) if method_status is not None else 0
            validated = sum(
                method_status.get(int(record["id"]), {}).get("outcome") == "validated"
                for record in rows
            ) if method_status is not None else 0
            level2 = "Level 1 only" if problem == 10 else _rate(validated, len(rows)) if method_status is not None else "unavailable"
            lines.append(
                f"| {METHOD_LABELS[method]} | {problem} | "
                f"{_rate(successes, len(rows)) if method_status is not None else 'unavailable'} | {level2} |"
            )

    lines.extend(
        [
            "",
            "## Table 4. Repair Rate by Error Category",
            "",
            "| Method | Error category | E_all | Level 1 repair | Level 2 validated |",
            "|---|---|---:|---:|---:|",
        ]
    )
    categories = sorted({record.get("error_category") or "uncategorized" for record in all_records})
    for method in ("sqlrepair", "rules", "llm_a", "llm_b"):
        method_status = status_by_method.get(method)
        for category in categories:
            rows = [record for record in all_records if (record.get("error_category") or "uncategorized") == category]
            l1 = sum(
                method_status.get(int(record["id"]), {}).get("outcome")
                in {"validated", "falsely_accepted", "level1_repaired"}
                for record in rows
            ) if method_status is not None else 0
            l2 = sum(
                method_status.get(int(record["id"]), {}).get("outcome") == "validated"
                for record in rows
            ) if method_status is not None else 0
            lines.append(
                f"| {METHOD_LABELS[method]} | {category} | {len(rows)} | "
                f"{_rate(l1, len(rows)) if method_status is not None else 'unavailable'} | "
                f"{_rate(l2, len(rows)) if method_status is not None else 'unavailable'} |"
            )

    lines.extend(
        [
            "",
            "## Table 5. Paired Query-Group Tests",
            "",
            "| Level | Comparison | Discordant A/B | Raw p | Holm p |",
            "|---|---|---:|---:|---:|",
        ]
    )
    available = [method for method in ("rules", "sqlrepair", "llm_a", "llm_b") if method in groups_by_method]
    comparisons = []
    for first, second in (("llm_a", "rules"), ("llm_b", "rules"), ("llm_a", "sqlrepair"), ("llm_b", "sqlrepair"), ("llm_a", "llm_b")):
        if first in available and second in available:
            comparisons.append((first, second))
    all_groups = sorted({record.get("group_id") for record in all_records if record.get("group_id")})
    problem_by_group = {}
    for record in all_records:
        problem_by_group.setdefault(record.get("group_id"), int(record["problem"]))
    for level in ("level1", "level2"):
        test_rows = []
        for first, second in comparisons:
            group_ids = [
                group_id
                for group_id in all_groups
                if problem_by_group[group_id] != 10
            ] if level == "level2" else all_groups
            first_values = []
            second_values = []
            for group_id in group_ids:
                group_a = groups_by_method[first].get(group_id)
                group_b = groups_by_method[second].get(group_id)
                def outcome(group):
                    if not group:
                        return False
                    if level == "level1":
                        return group["outcome"] in {"validated", "falsely_accepted", "level1_repaired"}
                    return group["outcome"] == "validated"
                first_values.append(outcome(group_a))
                second_values.append(outcome(group_b))
            only_a, only_b, p_value = mcnemar_pvalue(first_values, second_values)
            test_rows.append((first, second, only_a, only_b, p_value))
        adjusted = holm_adjust([row[4] for row in test_rows])
        for row, corrected in zip(test_rows, adjusted, strict=True):
            lines.append(
                f"| {level} | {METHOD_LABELS[row[0]]} vs {METHOD_LABELS[row[1]]} | {row[2]}/{row[3]} | {row[4]:.4g} | {corrected:.4g} |"
            )

    lines.extend(_cost_rows(call_logs or {}, cost_config))
    figure_dir = output_path.parent / "figures"
    figure_dir.mkdir(parents=True, exist_ok=True)
    figure_rates = {}
    for method in ("rules", "sqlrepair", "llm_a", "llm_b"):
        metrics = _main_metrics(all_records, status_by_method.get(method, {}))
        l1_total, l1_denominator = metrics["level1"]
        l2_total, l2_denominator = metrics["level2"]
        figure_rates[METHOD_LABELS[method]] = (
            l1_total / l1_denominator if method in status_by_method and l1_denominator else None,
            l2_total / l2_denominator if method in status_by_method and l2_denominator else None,
        )
    _write_level_rate_figure(figure_dir / "figure1_level1_level2.svg", figure_rates)
    _write_false_acceptance_figure(
        figure_dir / "figure2_false_acceptance_families.svg", groups_by_method
    )
    _write_minimality_figure(
        figure_dir / "figure3_minimality_distributions.svg", minimality_records or []
    )
    lines.extend(
        [
            "",
            "## Figures",
            "",
            "- Figure 1: [`figures/figure1_level1_level2.svg`](figures/figure1_level1_level2.svg)",
            "- Figure 2: [`figures/figure2_false_acceptance_families.svg`](figures/figure2_false_acceptance_families.svg)",
            "- Figure 3: [`figures/figure3_minimality_distributions.svg`](figures/figure3_minimality_distributions.svg)",
        ]
    )

    lines.extend(
        [
            "",
            "## Limitations and Status",
            "",
            "- Problem 10 is included in Level 1 rates and excluded from Level 2 rates and false-acceptance analyses.",
            "- Participant-cluster bootstrap intervals use 2,000 resamples and seed 42 when the method outputs are available.",
            "- RQ3 minimality and RQ4 renaming scripts are implemented as separate stages; their results require a completed core run, and RQ3 expert labels require two annotators.",
            "- Cost is calculated only when per-token input and output prices are supplied; otherwise it is labeled n/a.",
            "- Same-validator Java/Z3 SQLRepair results and final release checks remain pending.",
            "- Level 2 is execution evidence on the fixed independent variants, not a proof of SQL equivalence.",
        ]
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return "\n".join(lines)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--pilot", action="store_true", help="Aggregate only pilot groups")
    parser.add_argument("--config", type=Path, default=Path(__file__).parents[1] / "config.yaml")
    args = parser.parse_args()
    research_root = Path(__file__).parents[1]
    processed = research_root / "data" / "processed"
    submissions = _read_jsonl(processed / "submissions.jsonl")
    problems = json.loads((processed / "problems.json").read_text(encoding="utf-8"))
    validations = {}
    validation_dir = research_root / "outputs" / "validation"
    if validation_dir.exists():
        pattern = "pilot_*.jsonl" if args.pilot else "*.jsonl"
        for path in validation_dir.glob(pattern):
            method = path.stem.removeprefix("pilot_") if args.pilot else path.stem
            validations[method] = _read_jsonl(path)
    if args.pilot:
        pilot_groups = {
            record.get("group_id")
            for records in validations.values()
            for record in records
            if record.get("record_type") == "group"
        }
        submissions = [
            record for record in submissions
            if record.get("group_id") in pilot_groups and record.get("in_e_all")
        ]
        for record in submissions:
            record["in_e_clean"] = True
        output_path = research_root / "outputs" / "pilot" / "results.md"
    else:
        output_path = research_root / "outputs" / "results.md"
    call_logs = {
        model: _read_jsonl(research_root / "logs" / "llm" / f"{model}_calls.jsonl")
        for model in ("llm_a", "llm_b")
    }
    minimality_records = _read_jsonl(research_root / "outputs" / "rq3_metrics.jsonl")
    cost_config = None
    if args.config.exists():
        import yaml

        settings = yaml.safe_load(args.config.read_text(encoding="utf-8")) or {}
        cost_config = settings.get("llm", {})
    build_results_report(
        submissions,
        validations,
        output_path,
        problem_metadata=problems,
        call_logs=call_logs,
        cost_config=cost_config,
        minimality_records=minimality_records,
    )
    print(f"Wrote {output_path}")


if __name__ == "__main__":
    main()
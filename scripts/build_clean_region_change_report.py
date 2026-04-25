#!/usr/bin/env python3
"""Build cleaned ASN region-change reports from existing curated outputs."""

from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable


ALLOCATED_STATUSES = {"allocated", "assigned"}
INVALID_COUNTRIES = {"", "ZZ", "AP", "EU", "gap"}
INVALID_REGIONS = {"", "unknown", "gap"}
INVALID_RIRS = {"", "gap"}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return [dict(row) for row in csv.DictReader(f)]


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fieldnames is None:
        fieldnames = list(rows[0].keys()) if rows else []
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def is_real_allocated_change(row: dict[str, str]) -> bool:
    if row["from_status"] not in ALLOCATED_STATUSES or row["to_status"] not in ALLOCATED_STATUSES:
        return False
    if row["from_country"] in INVALID_COUNTRIES or row["to_country"] in INVALID_COUNTRIES:
        return False
    if row["from_rir"] in INVALID_RIRS or row["to_rir"] in INVALID_RIRS:
        return False
    return (
        row["from_country"] != row["to_country"]
        or row["from_rir"] != row["to_rir"]
        or row["from_region"] != row["to_region"]
    )


def transition_matrix(events: Iterable[dict[str, str]], from_field: str, to_field: str) -> list[dict[str, Any]]:
    counts: Counter[tuple[str, str]] = Counter()
    for event in events:
        source = event[from_field]
        target = event[to_field]
        if source != target and source not in {"", "gap"} and target not in {"", "gap"}:
            counts[(source, target)] += 1
    return [
        {"from": source, "to": target, "event_count": count}
        for (source, target), count in counts.most_common()
    ]


def clean_candidate_rows(real_events: list[dict[str, str]], trajectories: dict[str, dict[str, str]]) -> list[dict[str, Any]]:
    by_asn: dict[str, list[dict[str, str]]] = defaultdict(list)
    for event in real_events:
        by_asn[event["asn"]].append(event)

    rows: list[dict[str, Any]] = []
    for asn, events in by_asn.items():
        trajectory = trajectories.get(asn, {})
        countries = _sequence([events[0]["from_country"], *[event["to_country"] for event in events]])
        rirs = _sequence([events[0]["from_rir"], *[event["to_rir"] for event in events]])
        regions = _sequence([events[0]["from_region"], *[event["to_region"] for event in events]])
        reasons: list[str] = []
        if len(rirs) > 1 and len(countries) > 1:
            reasons.append("cross_rir_and_country")
        if len(regions) > 1:
            reasons.append("cross_region")
        if len(events) > 1:
            reasons.append("multiple_real_changes")
        if countries and countries[0] == countries[-1] and len(set(countries)) > 1:
            reasons.append("real_temporary_revert")
        if trajectory.get("trajectory_type") in {"temporary_revert", "oscillation"} and len(events) > 1:
            reasons.append("trajectory_revert_or_oscillation")
        rows.append(
            {
                "asn": asn,
                "first_real_change_month": events[0]["to_month"],
                "last_real_change_month": events[-1]["to_month"],
                "real_change_event_count": len(events),
                "real_country_sequence": " -> ".join(countries),
                "real_rir_sequence": " -> ".join(rirs),
                "real_region_sequence": " -> ".join(regions),
                "trajectory_type": trajectory.get("trajectory_type", ""),
                "observed_months": trajectory.get("observed_months", ""),
                "missing_months": trajectory.get("missing_months", ""),
                "max_stable_months": trajectory.get("max_stable_months", ""),
                "review_reasons": ";".join(reasons),
                "first_raw_evidence_path": events[0]["from_raw_evidence_path"],
                "first_raw_evidence_sha256": events[0]["from_raw_evidence_sha256"],
                "last_raw_evidence_path": events[-1]["to_raw_evidence_path"],
                "last_raw_evidence_sha256": events[-1]["to_raw_evidence_sha256"],
            }
        )
    return sorted(
        rows,
        key=lambda row: (
            "cross_region" in row["review_reasons"],
            "cross_rir_and_country" in row["review_reasons"],
            int(row["real_change_event_count"]),
        ),
        reverse=True,
    )


def _sequence(values: list[str]) -> list[str]:
    out: list[str] = []
    for value in values:
        if value and (not out or out[-1] != value):
            out.append(value)
    return out


def write_summary(
    path: Path,
    real_events: list[dict[str, str]],
    all_events: list[dict[str, str]],
    trajectories: dict[str, dict[str, str]],
    candidates: list[dict[str, Any]],
) -> None:
    real_asns = {event["asn"] for event in real_events}
    real_country_asns = {event["asn"] for event in real_events if event["from_country"] != event["to_country"]}
    real_rir_asns = {event["asn"] for event in real_events if event["from_rir"] != event["to_rir"]}
    real_region_asns = {event["asn"] for event in real_events if event["from_region"] != event["to_region"]}
    zz_or_reserved_events = [
        event
        for event in all_events
        if event["from_status"] not in ALLOCATED_STATUSES
        or event["to_status"] not in ALLOCATED_STATUSES
        or event["from_country"] in INVALID_COUNTRIES
        or event["to_country"] in INVALID_COUNTRIES
    ]
    country_paths = Counter(
        f"{event['from_country']} -> {event['to_country']}"
        for event in real_events
        if event["from_country"] != event["to_country"]
    )
    rir_paths = Counter(
        f"{event['from_rir']} -> {event['to_rir']}"
        for event in real_events
        if event["from_rir"] != event["to_rir"]
    )
    lines = [
        "# ASN 近五年真实分配态变化清洗报告",
        "",
        "## 口径",
        "",
        "- 仅统计 `allocated/assigned -> allocated/assigned` 的 delegated 行政分配变化。",
        "- 排除 `country=ZZ/AP/EU`、`gap`、`available`、`reserved` 引起的状态变化。",
        "- 该结果仍只表示 registry delegated 行政分配变化，不代表运营地变化或最终异常裁定。",
        "",
        "## 核心统计",
        "",
        f"- 全量轨迹 ASN 数量：{len(trajectories)}",
        f"- 全量变化事件数量：{len(all_events)}",
        f"- 涉及 ZZ/reserved/available/gap 的状态变化事件数量：{len(zz_or_reserved_events)}",
        f"- 真实分配态变化事件数量：{len(real_events)}",
        f"- 真实分配态变化 ASN 数量：{len(real_asns)}",
        f"- 真实国家变化 ASN 数量：{len(real_country_asns)}",
        f"- 真实 RIR 变化 ASN 数量：{len(real_rir_asns)}",
        f"- 真实跨大区变化 ASN 数量：{len(real_region_asns)}",
        f"- 清洗后高优先级复核候选数量：{len(candidates)}",
        "",
        "## 最常见真实国家变化路径",
        "",
    ]
    for path_name, count in country_paths.most_common(20):
        lines.append(f"- `{path_name}`: {count}")
    lines.extend(["", "## 最常见真实 RIR 变化路径", ""])
    for path_name, count in rir_paths.most_common(20):
        lines.append(f"- `{path_name}`: {count}")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build cleaned ASN region-change report artifacts.")
    parser.add_argument("--events", type=Path, default=Path("data/curated/registry/asn_region_change_events.csv"))
    parser.add_argument("--trajectories", type=Path, default=Path("data/curated/registry/asn_region_trajectories.csv"))
    parser.add_argument("--report-dir", type=Path, default=Path("reports/asn_region_changes"))
    args = parser.parse_args()

    events = read_csv(args.events)
    trajectories = {row["asn"]: row for row in read_csv(args.trajectories)}
    real_events = [event for event in events if is_real_allocated_change(event)]
    candidates = clean_candidate_rows(real_events, trajectories)

    args.report_dir.mkdir(parents=True, exist_ok=True)
    write_csv(args.report_dir / "real_allocated_change_events.csv", real_events)
    write_csv(args.report_dir / "real_country_transition_matrix.csv", transition_matrix(real_events, "from_country", "to_country"))
    write_csv(args.report_dir / "real_rir_transition_matrix.csv", transition_matrix(real_events, "from_rir", "to_rir"))
    write_csv(args.report_dir / "real_region_transition_matrix.csv", transition_matrix(real_events, "from_region", "to_region"))
    write_csv(args.report_dir / "real_high_priority_review_candidates.csv", candidates)
    write_summary(args.report_dir / "summary_clean.md", real_events, events, trajectories, candidates)
    print(f"real_allocated_change_events={len(real_events)}")
    print(f"real_high_priority_review_candidates={len(candidates)}")
    print(f"summary={args.report_dir / 'summary_clean.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

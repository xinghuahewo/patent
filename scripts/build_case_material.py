#!/usr/bin/env python3
"""Build human-review case material from the current stage1 candidates."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from pipeline_utils import (
    add_common_args,
    as_bool,
    as_float,
    as_int,
    ensure_dirs,
    load_config,
    parser_version,
    read_table,
    relative_to_root,
    resolve_run_id,
    schema_version,
    sha256_file,
    utc_now,
    write_json,
    write_table,
)


PRIORITY_ORDER = {"high_review": 0, "medium_review": 1, "low_review": 2}
CASE_SCHEMA_NAME = "case_material_v1"


def key_for(row: dict[str, Any], month_field: str = "analysis_month") -> tuple[int, str]:
    return int(row["asn"]), str(row.get(month_field) or row.get("month"))


def clean_country(value: Any) -> str:
    return str(value or "").strip().upper()


def evidence_status(weakness_flags: list[str]) -> str:
    severe = {
        "missing_stage1_evidence",
        "missing_prefix_geo_evidence",
        "dominant_country_missing",
        "dominant_country_unmapped",
        "low_prefix_count",
        "high_unmapped_ratio",
    }
    if severe & set(weakness_flags):
        return "insufficient_evidence"
    if weakness_flags:
        return "partial_evidence"
    return "evidence_ready"


def weakness_flags_for(
    *,
    stage1: dict[str, Any],
    prefix_geo: dict[str, Any],
    registry: dict[str, Any],
    inventory: dict[str, Any],
    country: str,
) -> list[str]:
    flags: list[str] = []
    prefix_count = as_int(prefix_geo.get("prefix_count"), 0)
    mapped_count = as_int(prefix_geo.get("mapped_prefix_count"), 0)
    unmapped_count = as_int(prefix_geo.get("unmapped_prefix_count"), 0)
    dominant = clean_country(prefix_geo.get("dominant_prefix_country") or stage1.get("dominant_prefix_country"))

    if not stage1.get("raw_evidence_path") or not stage1.get("raw_evidence_sha256"):
        flags.append("missing_stage1_evidence")
    if not prefix_geo.get("raw_evidence_path") or not prefix_geo.get("raw_evidence_sha256"):
        flags.append("missing_prefix_geo_evidence")
    if not registry.get("registered_country"):
        flags.append("registered_country_missing")
    if clean_country(registry.get("allocated_country") or stage1.get("allocated_country")) not in {"", country}:
        flags.append("allocated_country_outside_scope")
    if not dominant:
        flags.append("dominant_country_missing")
    elif dominant == "ZZ":
        flags.append("dominant_country_unmapped")
    if prefix_count < 3:
        flags.append("low_prefix_count")
    elif prefix_count < 10:
        flags.append("small_prefix_count")
    if prefix_count and unmapped_count / prefix_count >= 0.5:
        flags.append("high_unmapped_ratio")
    if prefix_count and mapped_count / prefix_count < 0.5:
        flags.append("low_mapped_ratio")
    if not inventory:
        flags.append("missing_prefix_inventory_row")
    if as_bool(stage1.get("border_as_flag", False)):
        flags.append("border_as_explanatory_risk")
    for field in ("cloud_or_cdn_flag", "crossborder_group_flag", "hosting_or_lease_hint_flag"):
        if registry.get(field) not in (None, "") and as_bool(registry.get(field)):
            flags.append(field.replace("_flag", "_risk"))
    return flags


def choose_review_priority(
    *,
    prefix_geo: dict[str, Any],
    weakness_flags: list[str],
) -> str:
    prefix_count = as_int(prefix_geo.get("prefix_count"), 0)
    foreign_ratio = as_float(prefix_geo.get("foreign_prefix_coverage_ratio"), 0.0)
    dominant = clean_country(prefix_geo.get("dominant_prefix_country"))
    low_flags = {
        "dominant_country_missing",
        "dominant_country_unmapped",
        "low_prefix_count",
        "high_unmapped_ratio",
        "low_mapped_ratio",
        "border_as_explanatory_risk",
        "cloud_or_cdn_risk",
        "crossborder_group_risk",
        "hosting_or_lease_hint_risk",
    }
    medium_blockers = {"registered_country_missing", "allocated_country_outside_scope", "small_prefix_count"}

    if low_flags & set(weakness_flags):
        return "low_review"
    if dominant and dominant != "ZZ" and foreign_ratio >= 0.70 and prefix_count >= 10:
        if not (medium_blockers & set(weakness_flags)):
            return "high_review"
        return "medium_review"
    return "medium_review"


def trigger_reason_for(prefix_geo: dict[str, Any]) -> str:
    dominant = clean_country(prefix_geo.get("dominant_prefix_country")) or "missing"
    foreign_ratio = as_float(prefix_geo.get("foreign_prefix_coverage_ratio"), 0.0)
    prefix_count = as_int(prefix_geo.get("prefix_count"), 0)
    return (
        "prefix_geo_conflict"
        f": dominant_prefix_country={dominant}; "
        f"foreign_prefix_coverage_ratio={foreign_ratio:.3f}; "
        f"prefix_count={prefix_count}"
    )


def build_case_rows(
    *,
    stage1_rows: list[dict[str, Any]],
    prefix_geo_rows: list[dict[str, Any]],
    registry_rows: list[dict[str, Any]],
    prefix_inventory_rows: list[dict[str, Any]],
    country: str,
    month: str,
) -> list[dict[str, Any]]:
    country = country.upper()
    prefix_geo_by_key = {key_for(row): row for row in prefix_geo_rows}
    registry_by_key = {key_for(row): row for row in registry_rows}
    inventory_by_key = {key_for(row): row for row in prefix_inventory_rows}
    rows: list[dict[str, Any]] = []

    for stage1 in stage1_rows:
        asn = int(stage1["asn"])
        row_month = str(stage1.get("month") or stage1.get("analysis_month"))
        if row_month != month or not as_bool(stage1.get("geo_conflict_flag", False)):
            continue
        prefix_geo = prefix_geo_by_key.get((asn, month), {})
        if clean_country(prefix_geo.get("baseline_country")) != country:
            continue
        if not as_bool(prefix_geo.get("geo_conflict_flag", False)):
            continue

        registry = registry_by_key.get((asn, month), {})
        inventory = inventory_by_key.get((asn, month), {})
        flags = weakness_flags_for(
            stage1=stage1,
            prefix_geo=prefix_geo,
            registry=registry,
            inventory=inventory,
            country=country,
        )
        priority = choose_review_priority(prefix_geo=prefix_geo, weakness_flags=flags)
        evidence = evidence_status(flags)
        raw_path = str(stage1.get("raw_evidence_path") or prefix_geo.get("raw_evidence_path") or "")
        raw_sha = str(stage1.get("raw_evidence_sha256") or prefix_geo.get("raw_evidence_sha256") or "")

        rows.append(
            {
                "asn": asn,
                "month": month,
                "review_priority": priority,
                "evidence_status": evidence,
                "trigger_reason": trigger_reason_for(prefix_geo),
                "weakness_flags": ";".join(flags),
                "raw_evidence_path": raw_path,
                "raw_evidence_sha256": raw_sha,
                "allocated_country": registry.get("allocated_country") or stage1.get("allocated_country") or "",
                "registered_country": registry.get("registered_country") or stage1.get("registered_country") or "",
                "dominant_prefix_country": prefix_geo.get("dominant_prefix_country") or "",
                "prefix_count": as_int(prefix_geo.get("prefix_count"), 0),
                "mapped_prefix_count": as_int(prefix_geo.get("mapped_prefix_count"), 0),
                "unmapped_prefix_count": as_int(prefix_geo.get("unmapped_prefix_count"), 0),
                "foreign_prefix_coverage_ratio": f"{as_float(prefix_geo.get('foreign_prefix_coverage_ratio'), 0.0):.6f}",
                "as_name": inventory.get("as_name") or "",
                "stage1_raw_evidence_path": stage1.get("raw_evidence_path") or "",
                "stage1_raw_evidence_sha256": stage1.get("raw_evidence_sha256") or "",
                "prefix_geo_raw_evidence_path": prefix_geo.get("raw_evidence_path") or "",
                "prefix_geo_raw_evidence_sha256": prefix_geo.get("raw_evidence_sha256") or "",
                "geo_evidence_path": prefix_geo.get("geo_evidence_path") or "",
                "geo_evidence_sha256": prefix_geo.get("geo_evidence_sha256") or "",
                "registry_raw_evidence_path": registry.get("raw_evidence_path") or "",
                "registry_raw_evidence_sha256": registry.get("raw_evidence_sha256") or "",
                "prefix_inventory_raw_evidence_path": inventory.get("raw_evidence_path") or "",
                "prefix_inventory_raw_evidence_sha256": inventory.get("raw_evidence_sha256") or "",
            }
        )

    rows.sort(
        key=lambda row: (
            PRIORITY_ORDER[str(row["review_priority"])],
            -float(row["foreign_prefix_coverage_ratio"]),
            -int(row["prefix_count"]),
            int(row["asn"]),
        )
    )
    return rows


def render_case_card(row: dict[str, Any]) -> str:
    title = f"AS{row['asn']} - {row['month']} 人工复核材料"
    weakness = str(row.get("weakness_flags") or "无").replace(";", "、")
    return "\n".join(
        [
            f"# {title}",
            "",
            "## 复核队列信息",
            "",
            f"- `review_priority`: `{row['review_priority']}`",
            f"- `evidence_status`: `{row['evidence_status']}`",
            f"- `trigger_reason`: {row['trigger_reason']}",
            f"- `weakness_flags`: {weakness}",
            "",
            "## 当前可见线索",
            "",
            f"- ASN：`{row['asn']}`",
            f"- 月份：`{row['month']}`",
            f"- 名称：`{row.get('as_name') or 'missing'}`",
            f"- allocated country：`{row.get('allocated_country') or 'missing'}`",
            f"- registered country：`{row.get('registered_country') or 'missing'}`",
            f"- dominant prefix country：`{row.get('dominant_prefix_country') or 'missing'}`",
            f"- prefix count：`{row.get('prefix_count')}`",
            f"- mapped / unmapped：`{row.get('mapped_prefix_count')}` / `{row.get('unmapped_prefix_count')}`",
            f"- foreign prefix coverage ratio：`{row.get('foreign_prefix_coverage_ratio')}`",
            "",
            "## 不能说明什么",
            "",
            "- 不能说明最终运营国。",
            "- 不能作为异常裁定。",
            "- 不能替代人工复核；边界型 ASN、云厂商、CDN、骨干网、跨国集团仍需要解释性降权。",
            "",
            "## 原始证据引用",
            "",
            f"- stage1：`{row.get('stage1_raw_evidence_path') or row.get('raw_evidence_path')}`，sha256=`{row.get('stage1_raw_evidence_sha256') or row.get('raw_evidence_sha256')}`",
            f"- prefix_geo raw：`{row.get('prefix_geo_raw_evidence_path')}`，sha256=`{row.get('prefix_geo_raw_evidence_sha256')}`",
            f"- delegated prefix geo：`{row.get('geo_evidence_path')}`，sha256=`{row.get('geo_evidence_sha256')}`",
            f"- registry：`{row.get('registry_raw_evidence_path')}`，sha256=`{row.get('registry_raw_evidence_sha256')}`",
            f"- prefix inventory：`{row.get('prefix_inventory_raw_evidence_path')}`，sha256=`{row.get('prefix_inventory_raw_evidence_sha256')}`",
            "",
        ]
    )


def artifact_entry(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return {
        "path": relative_to_root(path),
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
    }


def write_summary(path: Path, rows: list[dict[str, Any]], country: str, month: str) -> None:
    counts = {priority: 0 for priority in PRIORITY_ORDER}
    status_counts: dict[str, int] = {}
    for row in rows:
        counts[str(row["review_priority"])] += 1
        status = str(row["evidence_status"])
        status_counts[status] = status_counts.get(status, 0) + 1
    lines = [
        f"# {country} {month} 人工复核材料摘要",
        "",
        "本目录只把 stage1 中 `geo_conflict_flag=true` 的候选整理成人工复核材料，不给出最终运营国或异常裁定。",
        "",
        "## 队列概览",
        "",
        f"- 候选总数：`{len(rows)}`",
        f"- high_review：`{counts['high_review']}`",
        f"- medium_review：`{counts['medium_review']}`",
        f"- low_review：`{counts['low_review']}`",
        "",
        "## 证据状态",
        "",
    ]
    for status, count in sorted(status_counts.items()):
        lines.append(f"- {status}：`{count}`")
    lines.extend(
        [
            "",
            "## 输出文件",
            "",
            "- `review_queue.csv`：人工复核队列。",
            "- `cases/AS{asn}.md`：逐 ASN case card。",
            "- `manifest.json`：输入、输出、hash 和语义边界。",
            "",
            "## 禁止解释",
            "",
            "- `dominant_prefix_country` 只表示静态 prefix delegated 画像。",
            "- 本报告不包含最终运营国字段。",
            "- 本报告不包含异常裁定字段。",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def write_case_material(
    *,
    rows: list[dict[str, Any]],
    output_dir: Path,
    country: str,
    month: str,
    run_id: str,
    config: dict[str, Any],
    inputs: dict[str, Path],
) -> None:
    cases_dir = output_dir / "cases"
    ensure_dirs([output_dir, cases_dir])
    review_queue = output_dir / "review_queue.csv"
    summary = output_dir / "summary.md"
    write_table(rows, review_queue)
    for row in rows:
        (cases_dir / f"AS{row['asn']}.md").write_text(render_case_card(row), encoding="utf-8")
    write_summary(summary, rows, country, month)

    priority_counts: dict[str, int] = {priority: 0 for priority in PRIORITY_ORDER}
    for row in rows:
        priority_counts[str(row["review_priority"])] += 1
    manifest = {
        "artifact": "case_material",
        "schema": CASE_SCHEMA_NAME,
        "layer": "reports",
        "analysis_unit": "(asn, month)",
        "producer": "scripts/build_case_material.py",
        "command": "python3 " + " ".join(sys.argv),
        "generated_at": utc_now(),
        "run_id": run_id,
        "schema_version": schema_version(config),
        "parser_version": parser_version(config),
        "scope": {"country": country, "month": month, "trigger_filter": "geo_conflict_flag=true"},
        "inputs": {name: artifact_entry(path) for name, path in inputs.items()},
        "outputs": {
            "summary": artifact_entry(summary),
            "review_queue": artifact_entry(review_queue),
            "cases_dir": relative_to_root(cases_dir),
        },
        "row_count": len(rows),
        "priority_counts": priority_counts,
        "required_fields": [
            "asn",
            "month",
            "review_priority",
            "evidence_status",
            "trigger_reason",
            "weakness_flags",
            "raw_evidence_path",
            "raw_evidence_sha256",
        ],
        "meaning": "把 stage1 中静态 prefix_geo 冲突线索整理成人工复核队列和 case card。",
        "caveats": [
            "case material 不是最终异常名单。",
            "不输出最终运营国。",
            "不输出异常裁定。",
            "缺失证据只进入 evidence_status 或 weakness_flags。",
        ],
    }
    write_json(output_dir / "manifest.json", manifest)


def resolve_dir(path: Path) -> Path:
    return path if path.is_absolute() else Path.cwd() / path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build human-review case material.")
    add_common_args(parser)
    parser.add_argument("--country", default="IR")
    parser.add_argument("--month", default="2026-03")
    parser.add_argument("--stage1-dir", type=Path, default=None)
    parser.add_argument("--prefix-dir", type=Path, default=None)
    parser.add_argument("--registry-dir", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args(argv)

    config = load_config(args.config)
    run_id = resolve_run_id(config, args.run_id)
    staging_root = Path(config["paths"]["staging_root"])
    curated_root = Path(config["paths"]["curated_root"])
    reports_root = Path(config["paths"]["reports_root"])
    stage1_dir = resolve_dir(args.stage1_dir or curated_root / "stage1")
    prefix_dir = resolve_dir(args.prefix_dir or staging_root / "prefixes")
    registry_dir = resolve_dir(args.registry_dir or staging_root / "registry")
    output_dir = resolve_dir(args.output_dir or reports_root / "case_material" / f"{args.country.upper()}_{args.month}")

    stage1_csv = stage1_dir / "asn_suspect_stage1.csv"
    prefix_geo_csv = prefix_dir / "asn_prefix_geo_monthly.csv"
    registry_csv = registry_dir / "asn_registry_baseline_monthly.csv"
    prefix_inventory_csv = prefix_dir / "asn_prefix_inventory_monthly.csv"
    rows = build_case_rows(
        stage1_rows=read_table(stage1_csv, stage1_dir / "asn_suspect_stage1.parquet"),
        prefix_geo_rows=read_table(prefix_geo_csv, prefix_dir / "asn_prefix_geo_monthly.parquet"),
        registry_rows=read_table(registry_csv, registry_dir / "asn_registry_baseline_monthly.parquet"),
        prefix_inventory_rows=read_table(prefix_inventory_csv, prefix_dir / "asn_prefix_inventory_monthly.parquet"),
        country=args.country,
        month=args.month,
    )
    write_case_material(
        rows=rows,
        output_dir=output_dir,
        country=args.country.upper(),
        month=args.month,
        run_id=run_id,
        config=config,
        inputs={
            "stage1": stage1_csv,
            "prefix_geo": prefix_geo_csv,
            "registry": registry_csv,
            "prefix_inventory": prefix_inventory_csv,
        },
    )
    print(f"saved {len(rows)} case material rows to {relative_to_root(output_dir)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

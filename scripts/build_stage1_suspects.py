#!/usr/bin/env python3
"""Build the first-stage ASN suspect candidate set."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from pipeline_utils import (
    add_common_args,
    as_bool,
    ensure_dirs,
    load_config,
    parser_version,
    read_table,
    relative_to_root,
    resolve_run_id,
    schema_version,
    sha256_file,
    write_json,
    write_table,
)


def key_for(row: dict[str, Any]) -> tuple[int, str]:
    return int(row["asn"]), str(row.get("analysis_month") or row.get("month"))


def choose_level(admin_conflict: bool, geo_conflict: bool, topology_anomaly: bool) -> str:
    true_count = sum([admin_conflict, geo_conflict, topology_anomaly])
    if admin_conflict and topology_anomaly:
        return "high"
    if true_count >= 2 or admin_conflict or topology_anomaly:
        return "medium"
    return "low"


def build_manifest(output_dir: Path, row: dict[str, Any], registry: dict[str, Any], links: dict[str, Any]) -> tuple[str, str]:
    manifest_dir = output_dir / "manifest"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    path = manifest_dir / f"{row['asn']}_{row['month']}_{row['run_id']}.json"
    write_json(
        path,
        {
            "record_id": f"stage1_evidence_{row['asn']}_{row['month']}",
            "run_id": row["run_id"],
            "schema_version": row["schema_version"],
            "parser_version": row["parser_version"],
            "asn": row["asn"],
            "month": row["month"],
            "source_records": {
                "registry": {
                    "record_id": registry.get("record_id"),
                    "raw_evidence_path": registry.get("raw_evidence_path"),
                    "raw_evidence_sha256": registry.get("raw_evidence_sha256"),
                },
                "links": {
                    "record_id": links.get("record_id"),
                    "raw_evidence_path": links.get("raw_evidence_path"),
                    "raw_evidence_sha256": links.get("raw_evidence_sha256"),
                },
            },
        },
    )
    return relative_to_root(path), sha256_file(path)


def build_rows(registry_rows: list[dict[str, Any]], links_rows: list[dict[str, Any]], run_id: str, config: dict[str, Any], output_dir: Path) -> list[dict[str, Any]]:
    registry_by_key = {key_for(row): row for row in registry_rows}
    links_by_key = {key_for(row): row for row in links_rows}
    rows: list[dict[str, Any]] = []

    for asn, month in sorted(set(registry_by_key) | set(links_by_key)):
        registry = registry_by_key.get((asn, month), {})
        links = links_by_key.get((asn, month), {})
        admin_conflict = as_bool(registry.get("admin_conflict_flag", False))
        topology_anomaly = as_bool(links.get("topology_anomaly_flag", False))
        border_as = as_bool(links.get("border_as_flag", False))
        geo_conflict = False
        level = choose_level(admin_conflict, geo_conflict, topology_anomaly)
        review_required = level in {"high", "medium"}

        row: dict[str, Any] = {
            "record_id": f"stage1_{asn}_{month}",
            "run_id": run_id,
            "schema_version": schema_version(config),
            "parser_version": parser_version(config),
            "asn": asn,
            "month": month,
            "allocated_country": registry.get("allocated_country") or None,
            "registered_country": registry.get("registered_country") or None,
            "dominant_prefix_country": None,
            "admin_conflict_flag": admin_conflict,
            "geo_conflict_flag": geo_conflict,
            "topology_anomaly_flag": topology_anomaly,
            "border_as_flag": border_as,
            "suspect_level": level,
            "review_required_flag": review_required,
            "evidence_summary": (
                f"allocated={registry.get('allocated_country') or 'missing'}; "
                f"registered={registry.get('registered_country') or 'missing'}; "
                f"admin_conflict={int(admin_conflict)}; "
                f"geo_conflict={int(geo_conflict)}; "
                f"topology_anomaly={int(topology_anomaly)}; "
                f"border_as={int(border_as)}; level={level}"
            ),
        }
        raw_path, raw_sha = build_manifest(output_dir, row, registry, links)
        row["raw_evidence_path"] = raw_path
        row["raw_evidence_sha256"] = raw_sha
        rows.append(row)
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build stage1 suspect candidates.")
    add_common_args(parser)
    parser.add_argument("--registry-dir", type=Path, default=None)
    parser.add_argument("--links-dir", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args(argv)

    config = load_config(args.config)
    run_id = resolve_run_id(config, args.run_id)
    staging_root = Path(config["paths"]["staging_root"])
    curated_root = Path(config["paths"]["curated_root"])
    registry_dir = args.registry_dir or staging_root / "registry"
    links_dir = args.links_dir or staging_root / "links"
    output_dir = args.output_dir or curated_root / "stage1"
    registry_dir = registry_dir if registry_dir.is_absolute() else Path.cwd() / registry_dir
    links_dir = links_dir if links_dir.is_absolute() else Path.cwd() / links_dir
    output_dir = output_dir if output_dir.is_absolute() else Path.cwd() / output_dir
    ensure_dirs([output_dir])

    registry_rows = read_table(
        registry_dir / "asn_registry_baseline_monthly.csv",
        registry_dir / "asn_registry_baseline_monthly.parquet",
    )
    links_rows = read_table(
        links_dir / "asn_link_summary_monthly.csv",
        links_dir / "asn_link_summary_monthly.parquet",
    )
    rows = build_rows(registry_rows, links_rows, run_id, config, output_dir)
    write_table(
        rows,
        output_dir / "asn_suspect_stage1.csv",
        output_dir / "asn_suspect_stage1.parquet",
    )
    print(f"saved {len(rows)} stage1 rows to {relative_to_root(output_dir)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

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
    utc_now,
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


def build_manifest(
    output_dir: Path,
    row: dict[str, Any],
    registry: dict[str, Any],
    links: dict[str, Any],
    prefix_geo: dict[str, Any],
) -> tuple[str, str]:
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
                "prefix_geo": {
                    "record_id": prefix_geo.get("record_id"),
                    "raw_evidence_path": prefix_geo.get("raw_evidence_path"),
                    "raw_evidence_sha256": prefix_geo.get("raw_evidence_sha256"),
                    "geo_evidence_path": prefix_geo.get("geo_evidence_path"),
                    "geo_evidence_sha256": prefix_geo.get("geo_evidence_sha256"),
                },
            },
        },
    )
    return relative_to_root(path), sha256_file(path)


def build_rows(
    registry_rows: list[dict[str, Any]],
    links_rows: list[dict[str, Any]],
    prefix_geo_rows: list[dict[str, Any]],
    run_id: str,
    config: dict[str, Any],
    output_dir: Path,
) -> list[dict[str, Any]]:
    registry_by_key = {key_for(row): row for row in registry_rows}
    links_by_key = {key_for(row): row for row in links_rows}
    prefix_geo_by_key = {key_for(row): row for row in prefix_geo_rows}
    rows: list[dict[str, Any]] = []

    for asn, month in sorted(set(registry_by_key) | set(links_by_key) | set(prefix_geo_by_key)):
        registry = registry_by_key.get((asn, month), {})
        links = links_by_key.get((asn, month), {})
        prefix_geo = prefix_geo_by_key.get((asn, month), {})
        admin_conflict = as_bool(registry.get("admin_conflict_flag", False))
        topology_anomaly = as_bool(links.get("topology_anomaly_flag", False))
        border_as = as_bool(links.get("border_as_flag", False))
        geo_conflict = as_bool(prefix_geo.get("geo_conflict_flag", False))
        level = choose_level(admin_conflict, geo_conflict, topology_anomaly)
        review_required = level in {"high", "medium"}
        dominant_prefix_country = prefix_geo.get("dominant_prefix_country") or None

        row: dict[str, Any] = {
            "record_id": f"stage1_{asn}_{month}",
            "run_id": run_id,
            "schema_version": schema_version(config),
            "parser_version": parser_version(config),
            "asn": asn,
            "month": month,
            "allocated_country": registry.get("allocated_country") or None,
            "registered_country": registry.get("registered_country") or None,
            "dominant_prefix_country": dominant_prefix_country,
            "admin_conflict_flag": admin_conflict,
            "geo_conflict_flag": geo_conflict,
            "topology_anomaly_flag": topology_anomaly,
            "border_as_flag": border_as,
            "suspect_level": level,
            "review_required_flag": review_required,
            "evidence_summary": (
                f"allocated={registry.get('allocated_country') or 'missing'}; "
                f"registered={registry.get('registered_country') or 'missing'}; "
                f"dominant_prefix={dominant_prefix_country or 'missing'}; "
                f"admin_conflict={int(admin_conflict)}; "
                f"geo_conflict={int(geo_conflict)}; "
                f"topology_anomaly={int(topology_anomaly)}; "
                f"border_as={int(border_as)}; level={level}"
            ),
        }
        raw_path, raw_sha = build_manifest(output_dir, row, registry, links, prefix_geo)
        row["raw_evidence_path"] = raw_path
        row["raw_evidence_sha256"] = raw_sha
        rows.append(row)
    return rows


def artifact_entry(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return {
        "path": relative_to_root(path),
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
    }


def write_artifact_manifest(
    *,
    manifest_path: Path,
    run_id: str,
    config: dict[str, Any],
    registry_dir: Path,
    links_dir: Path,
    prefix_geo_dir: Path,
    output_csv: Path,
    output_parquet: Path,
    row_count: int,
) -> None:
    manifest = {
        "artifact": "asn_suspect_stage1",
        "layer": "curated",
        "analysis_unit": "(asn, month)",
        "producer": "scripts/build_stage1_suspects.py",
        "command": "python3 " + " ".join(sys.argv),
        "generated_at": utc_now(),
        "run_id": run_id,
        "schema_version": schema_version(config),
        "parser_version": parser_version(config),
        "inputs": {
            "registry": artifact_entry(registry_dir / "asn_registry_baseline_monthly.csv"),
            "links": artifact_entry(links_dir / "asn_link_summary_monthly.csv"),
            "prefix_geo": artifact_entry(prefix_geo_dir / "asn_prefix_geo_monthly.csv"),
        },
        "outputs": {
            "csv": artifact_entry(output_csv),
            "parquet": artifact_entry(output_parquet),
            "row_manifest_dir": relative_to_root(output_csv.parent / "manifest"),
        },
        "row_count": row_count,
        "validation_command": "python3 scripts/validate_outputs.py --stage stage1",
        "meaning": "registry、links、prefix_geo 融合后的第一阶段候选集。",
        "caveats": [
            "stage1 是候选集，不是最终异常名单。",
            "suspect_level 只是复核优先级，不是最终风险等级。",
            "geo_conflict_flag 来自静态 prefix_geo 画像，不能替代运营地判断。",
        ],
    }
    write_json(manifest_path, manifest)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build stage1 suspect candidates.")
    add_common_args(parser)
    parser.add_argument("--registry-dir", type=Path, default=None)
    parser.add_argument("--links-dir", type=Path, default=None)
    parser.add_argument("--prefix-geo-dir", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args(argv)

    config = load_config(args.config)
    run_id = resolve_run_id(config, args.run_id)
    staging_root = Path(config["paths"]["staging_root"])
    curated_root = Path(config["paths"]["curated_root"])
    registry_dir = args.registry_dir or staging_root / "registry"
    links_dir = args.links_dir or staging_root / "links"
    prefix_geo_dir = args.prefix_geo_dir or staging_root / "prefixes"
    output_dir = args.output_dir or curated_root / "stage1"
    registry_dir = registry_dir if registry_dir.is_absolute() else Path.cwd() / registry_dir
    links_dir = links_dir if links_dir.is_absolute() else Path.cwd() / links_dir
    prefix_geo_dir = prefix_geo_dir if prefix_geo_dir.is_absolute() else Path.cwd() / prefix_geo_dir
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
    prefix_geo_rows = read_table(
        prefix_geo_dir / "asn_prefix_geo_monthly.csv",
        prefix_geo_dir / "asn_prefix_geo_monthly.parquet",
    )
    rows = build_rows(registry_rows, links_rows, prefix_geo_rows, run_id, config, output_dir)
    output_csv = output_dir / "asn_suspect_stage1.csv"
    output_parquet = output_dir / "asn_suspect_stage1.parquet"
    write_table(rows, output_csv, output_parquet)
    write_artifact_manifest(
        manifest_path=output_dir / "asn_suspect_stage1.manifest.json",
        run_id=run_id,
        config=config,
        registry_dir=registry_dir,
        links_dir=links_dir,
        prefix_geo_dir=prefix_geo_dir,
        output_csv=output_csv,
        output_parquet=output_parquet,
        row_count=len(rows),
    )
    print(f"saved {len(rows)} stage1 rows to {relative_to_root(output_dir)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Standardize raw local-bview prefix inventories into monthly staging rows."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from pipeline_utils import (
    add_common_args,
    as_int,
    ensure_dirs,
    load_config,
    read_json,
    relative_to_root,
    resolve_run_id,
    sha256_file,
    write_table,
)


def normalize_record(path: Path, run_id: str, config: dict[str, Any]) -> dict[str, Any]:
    payload = read_json(path)
    normalized = payload.get("normalized") or {}
    prefixes_v4 = sorted(str(item) for item in normalized.get("prefixes_v4") or [])
    prefixes_v6 = sorted(str(item) for item in normalized.get("prefixes_v6") or [])
    prefix_count_v4 = as_int(normalized.get("prefix_count_v4"), len(prefixes_v4))
    prefix_count_v6 = as_int(normalized.get("prefix_count_v6"), len(prefixes_v6))
    total_prefix_count = as_int(normalized.get("total_prefix_count"), prefix_count_v4 + prefix_count_v6)

    return {
        "record_id": f"prefix_inventory_{payload['asn']}_{payload['analysis_month']}",
        "run_id": run_id,
        "schema_version": str(config["project"]["schema_version"]),
        "parser_version": str(config["project"]["parser_version"]),
        "asn": int(payload["asn"]),
        "analysis_month": str(payload["analysis_month"]),
        "filter_country": payload.get("filter_country"),
        "as_name": payload.get("as_name"),
        "as_country": payload.get("as_country"),
        "global_rank": payload.get("global_rank"),
        "source_collector": payload.get("source_collector"),
        "source_snapshot_time": payload.get("source_snapshot_time"),
        "prefix_count_v4": prefix_count_v4,
        "prefix_count_v6": prefix_count_v6,
        "total_prefix_count": total_prefix_count,
        "prefixes_v4_json": json.dumps(prefixes_v4, ensure_ascii=False, sort_keys=True),
        "prefixes_v6_json": json.dumps(prefixes_v6, ensure_ascii=False, sort_keys=True),
        "fetch_time": payload.get("fetch_time"),
        "raw_evidence_path": relative_to_root(path),
        "raw_evidence_sha256": sha256_file(path),
    }


def iter_raw_files(raw_dir: Path, run_id: str | None, month: str | None, country: str | None) -> list[Path]:
    latest_by_key: dict[tuple[str, str, str], Path] = {}
    for path in sorted(raw_dir.glob("*.json")):
        payload = read_json(path)
        if run_id and str(payload.get("run_id")) != run_id:
            continue
        if month and str(payload.get("analysis_month")) != month:
            continue
        if country and str(payload.get("filter_country") or "").upper() != country.upper():
            continue
        key = (
            str(payload.get("asn")),
            str(payload.get("analysis_month")),
            str(payload.get("run_id")),
        )
        latest_by_key[key] = path
    return [latest_by_key[key] for key in sorted(latest_by_key)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Stage monthly ASN prefix inventories.")
    add_common_args(parser)
    parser.add_argument("--raw-dir", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--month", default=None)
    parser.add_argument("--country", default=None)
    args = parser.parse_args(argv)

    config = load_config(args.config)
    run_id = resolve_run_id(config, args.run_id)
    raw_dir = args.raw_dir or (Path(config["paths"]["raw_root"]) / "prefixes" / "extracted")
    output_dir = args.output_dir or (Path(config["paths"]["staging_root"]) / "prefixes")
    raw_dir = raw_dir if raw_dir.is_absolute() else Path.cwd() / raw_dir
    output_dir = output_dir if output_dir.is_absolute() else Path.cwd() / output_dir
    ensure_dirs([output_dir])

    raw_paths = iter_raw_files(raw_dir, run_id=run_id, month=args.month, country=args.country)
    rows = [normalize_record(path, run_id, config) for path in raw_paths]
    write_table(
        rows,
        output_dir / "asn_prefix_inventory_monthly.csv",
        output_dir / "asn_prefix_inventory_monthly.parquet",
    )
    print(f"saved {len(rows)} prefix staging rows to {relative_to_root(output_dir)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

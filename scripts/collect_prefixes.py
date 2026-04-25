#!/usr/bin/env python3
"""Collect monthly ASN prefix inventories from a local month-end bview."""

from __future__ import annotations

import argparse
import csv
import ipaddress
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pipeline_utils import (
    add_common_args,
    append_only_path,
    ensure_dirs,
    load_config,
    parser_version,
    read_asn_months,
    relative_to_root,
    resolve_input,
    resolve_run_id,
    schema_version,
    sha256_file,
    utc_now,
    write_json,
)


SNAPSHOT_RE = re.compile(r"^bview\.(\d{4})(\d{2})(\d{2})\.(\d{2})(\d{2})\.gz$")


@dataclass
class EntityRecord:
    asn: int
    as_name: str | None
    as_country: str | None
    global_rank: int | None


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect monthly ASN prefix inventories from local bview snapshots.")
    add_common_args(parser)
    parser.add_argument("--country", default=None, help="Country code filter from as_entity.csv. Default comes from config.")
    parser.add_argument("--month", action="append", default=None, help="Analysis month YYYY-MM. Can be passed multiple times.")
    parser.add_argument("--pilot-limit", type=int, default=None, help="Optional top-N ASN subset by global_rank for smoke tests.")
    parser.add_argument("--max-lines", type=int, default=None, help="Optional line cap for smoke tests; omit in full runs.")
    parser.add_argument("--entity-csv", type=Path, default=None, help="Override as_entity.csv source path.")
    parser.add_argument("--bview-root", type=Path, default=None, help="Override local bview root.")
    parser.add_argument("--raw-dir", type=Path, default=None, help="Override raw output root.")
    return parser.parse_args(argv)


def month_dir_name(month: str) -> str:
    year, month_num = month.split("-")
    return f"{year}.{month_num}"


def discover_bview(month: str, bview_root: Path) -> Path:
    month_dir = bview_root / month_dir_name(month)
    candidates = sorted(month_dir.glob("bview.*.gz"))
    if not candidates:
        raise FileNotFoundError(f"no bview snapshot found under {month_dir}")
    return candidates[-1]


def snapshot_time_from_name(path: Path) -> str:
    match = SNAPSHOT_RE.match(path.name)
    if not match:
        return utc_now()
    year, month, day, hour, minute = match.groups()
    return f"{year}-{month}-{day}T{hour}:{minute}:00Z"


def parse_prefix(prefix: str) -> str | None:
    try:
        return str(ipaddress.ip_network(prefix.strip(), strict=False))
    except ValueError:
        return None


def parse_origin_asn(as_path: str) -> int | None:
    tokens = [token for token in as_path.strip().split() if token]
    if not tokens:
        return None
    origin = tokens[-1]
    if any(marker in origin for marker in ("{", "}", ",")):
        return None
    try:
        return int(origin)
    except ValueError:
        return None


def parse_mrt_line(line: str) -> tuple[int, str] | None:
    parts = line.rstrip("\n").split("|")
    if len(parts) < 7:
        return None
    prefix = parse_prefix(parts[5])
    if prefix is None:
        return None
    origin_asn = parse_origin_asn(parts[6])
    if origin_asn is None:
        return None
    return origin_asn, prefix


def load_entity_index(path: Path, country: str, pilot_limit: int | None = None) -> dict[int, EntityRecord]:
    records: list[EntityRecord] = []
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            row_country = str(row.get("as_country") or "").strip().upper()
            if row_country != country:
                continue
            try:
                asn = int(str(row.get("asn") or "").strip())
            except ValueError:
                continue
            raw_rank = str(row.get("global_rank") or "").strip()
            try:
                global_rank = int(float(raw_rank)) if raw_rank else None
            except ValueError:
                global_rank = None
            records.append(
                EntityRecord(
                    asn=asn,
                    as_name=str(row.get("as_name") or "").strip() or None,
                    as_country=row_country or None,
                    global_rank=global_rank,
                )
            )
    records.sort(key=lambda item: (item.global_rank is None, item.global_rank or 10**12, item.asn))
    if pilot_limit is not None:
        records = records[: max(pilot_limit, 0)]
    return {record.asn: record for record in records}


def scan_bview_file(
    bgpdump_bin: str, bview_path: Path, entity_index: dict[int, EntityRecord], max_lines: int | None = None
) -> tuple[dict[int, dict[str, set[str]]], dict[str, int], str]:
    results = {asn: {"v4": set(), "v6": set()} for asn in entity_index}
    stats = {"total_lines": 0, "parsed_lines": 0, "matched_prefix_lines": 0, "invalid_lines": 0}
    process = subprocess.Popen(
        [bgpdump_bin, "-m", str(bview_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert process.stdout is not None
    capped = False
    for line in process.stdout:
        stats["total_lines"] += 1
        if stats["total_lines"] % 1_000_000 == 0:
            print(f"[progress] scanned_lines={stats['total_lines']} matched_prefix_lines={stats['matched_prefix_lines']}", flush=True)
        parsed = parse_mrt_line(line)
        if parsed is None:
            stats["invalid_lines"] += 1
            continue
        origin_asn, prefix = parsed
        stats["parsed_lines"] += 1
        bucket = results.get(origin_asn)
        if bucket is None:
            continue
        family = "v6" if ":" in prefix else "v4"
        bucket[family].add(prefix)
        stats["matched_prefix_lines"] += 1
        if max_lines is not None and stats["total_lines"] >= max_lines:
            capped = True
            break
    stderr_text = ""
    if capped and process.poll() is None:
        process.terminate()
    return_code = process.wait()
    if return_code != 0 and not capped:
        raise RuntimeError(f"bgpdump failed for {bview_path} with exit code {return_code}: {stderr_text.strip()}")
    return results, stats, stderr_text.strip()


def resolve_months(args: argparse.Namespace, input_path: Path | None) -> list[str]:
    if args.month:
        return sorted(set(str(month) for month in args.month))
    if input_path is None:
        raise ValueError("either --month or --input must be provided")
    return sorted({row["month"] for row in read_asn_months(input_path)})


def write_raw_records(
    month: str,
    run_id: str,
    country: str,
    entity_index: dict[int, EntityRecord],
    entity_path: Path,
    entity_sha256: str,
    bview_path: Path,
    bview_sha256: str,
    scan_results: dict[int, dict[str, set[str]]],
    config: dict[str, Any],
    raw_root: Path,
) -> list[str]:
    extracted_dir = raw_root / "prefixes" / "extracted"
    ensure_dirs([extracted_dir])
    fetch_time = utc_now()
    source_snapshot_time = snapshot_time_from_name(bview_path)
    written_paths: list[str] = []

    for asn, record in entity_index.items():
        buckets = scan_results[asn]
        payload = {
            "record_id": f"raw_prefixes_{asn}_{month}",
            "run_id": run_id,
            "schema_version": schema_version(config),
            "parser_version": parser_version(config),
            "asn": asn,
            "analysis_month": month,
            "filter_country": country,
            "fetch_time": fetch_time,
            "source_snapshot_time": source_snapshot_time,
            "source_collector": "rrc25",
            "as_name": record.as_name,
            "as_country": record.as_country,
            "global_rank": record.global_rank,
            "sources": {
                "bview": {
                    "status": "ok",
                    "raw_response_path": relative_to_root(bview_path),
                    "raw_response_sha256": bview_sha256,
                    "snapshot_time": source_snapshot_time,
                    "collector": "rrc25",
                },
                "as_entity": {
                    "status": "ok",
                    "raw_response_path": str(entity_path),
                    "raw_response_sha256": entity_sha256,
                    "country_filter": country,
                },
            },
            "normalized": {
                "prefixes_v4": sorted(buckets["v4"]),
                "prefixes_v6": sorted(buckets["v6"]),
                "prefix_count_v4": len(buckets["v4"]),
                "prefix_count_v6": len(buckets["v6"]),
                "total_prefix_count": len(buckets["v4"]) + len(buckets["v6"]),
            },
        }
        path = append_only_path(extracted_dir / f"{asn}_{month}_{run_id}.json")
        write_json(path, payload)
        written_paths.append(relative_to_root(path))
    return written_paths


def write_month_manifest(
    month: str,
    run_id: str,
    country: str,
    entity_count: int,
    entity_path: Path,
    entity_sha256: str,
    bview_path: Path,
    bview_sha256: str,
    stats: dict[str, int],
    stderr_text: str,
    written_paths: list[str],
    input_path: Path | None,
    config: dict[str, Any],
    raw_root: Path,
) -> Path:
    manifest_dir = raw_root / "prefixes" / "manifest"
    ensure_dirs([manifest_dir])
    payload = {
        "record_id": f"raw_prefixes_batch_{country}_{month}",
        "run_id": run_id,
        "schema_version": schema_version(config),
        "parser_version": parser_version(config),
        "analysis_month": month,
        "filter_country": country,
        "fetch_time": utc_now(),
        "source_snapshot_time": snapshot_time_from_name(bview_path),
        "source_collector": "rrc25",
        "input_path": relative_to_root(input_path) if input_path else None,
        "target_asn_count": entity_count,
        "raw_files_written": len(written_paths),
        "sources": {
            "bview": {
                "status": "ok",
                "raw_response_path": relative_to_root(bview_path),
                "raw_response_sha256": bview_sha256,
            },
            "as_entity": {
                "status": "ok",
                "raw_response_path": str(entity_path),
                "raw_response_sha256": entity_sha256,
                "country_filter": country,
            },
        },
        "scan_stats": stats,
        "bgpdump_stderr": stderr_text or None,
        "written_raw_files": written_paths,
    }
    path = append_only_path(manifest_dir / f"{country.lower()}_{month}_{run_id}.json")
    write_json(path, payload)
    return path


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    config = load_config(args.config)
    run_id = resolve_run_id(config, args.run_id)
    prefix_config = config.get("sources", {}).get("prefixes", {})
    as_entity_config = prefix_config.get("as_entity", {})
    bview_config = prefix_config.get("local_bview", {})

    country = str(args.country or as_entity_config.get("default_country") or "IR").upper()
    entity_path = args.entity_csv or Path(as_entity_config.get("source_path", "/home/experiment/info/as_entity.csv"))
    bview_root = args.bview_root or Path(bview_config.get("root", "/home/bgpdata/data/ripe/rrc25"))
    bgpdump_bin = str(bview_config.get("bgpdump_bin", "/usr/bin/bgpdump"))
    raw_root = args.raw_dir or Path(config["paths"]["raw_root"])
    input_path = resolve_input(config, args.input) if (args.input or args.month is None) else None

    entity_path = entity_path if entity_path.is_absolute() else Path.cwd() / entity_path
    bview_root = bview_root if bview_root.is_absolute() else Path.cwd() / bview_root
    raw_root = raw_root if raw_root.is_absolute() else Path.cwd() / raw_root
    if input_path is not None and not input_path.is_absolute():
        input_path = Path.cwd() / input_path

    months = resolve_months(args, input_path)
    print(f"[info] target_months={','.join(months)} country={country}", flush=True)
    entity_index = load_entity_index(entity_path, country, pilot_limit=args.pilot_limit)
    if not entity_index:
        raise ValueError(f"no ASN rows matched country={country} in {entity_path}")
    print(f"[info] matched_asns={len(entity_index)} entity_csv={entity_path}", flush=True)
    print(f"[info] hashing_entity_csv={entity_path}", flush=True)
    entity_sha256 = sha256_file(entity_path)

    for month in months:
        bview_path = discover_bview(month, bview_root)
        print(f"[info] selected_bview month={month} path={bview_path}", flush=True)
        print(f"[info] hashing_bview={bview_path}", flush=True)
        bview_sha256 = sha256_file(bview_path)
        print(f"[info] scanning_bview month={month}", flush=True)
        scan_results, stats, stderr_text = scan_bview_file(bgpdump_bin, bview_path, entity_index, max_lines=args.max_lines)
        written_paths = write_raw_records(
            month=month,
            run_id=run_id,
            country=country,
            entity_index=entity_index,
            entity_path=entity_path,
            entity_sha256=entity_sha256,
            bview_path=bview_path,
            bview_sha256=bview_sha256,
            scan_results=scan_results,
            config=config,
            raw_root=raw_root,
        )
        manifest_path = write_month_manifest(
            month=month,
            run_id=run_id,
            country=country,
            entity_count=len(entity_index),
            entity_path=entity_path,
            entity_sha256=entity_sha256,
            bview_path=bview_path,
            bview_sha256=bview_sha256,
            stats=stats,
            stderr_text=stderr_text,
            written_paths=written_paths,
            input_path=input_path,
            config=config,
            raw_root=raw_root,
        )
        print(
            f"saved {len(written_paths)} raw prefix records for country={country} month={month} "
            f"using {relative_to_root(bview_path)}; manifest={relative_to_root(manifest_path)}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())

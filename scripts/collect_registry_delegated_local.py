#!/usr/bin/env python3
"""Collect registry delegated evidence from a local NRO monthly snapshot."""

from __future__ import annotations

import argparse
import bisect
import calendar
import csv
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pipeline_utils import (
    COUNTRY_RE,
    add_common_args,
    append_only_path,
    ensure_dirs,
    load_config,
    parse_asn,
    parse_month,
    read_asn_months,
    relative_to_root,
    repo_root,
    resolve_input,
    resolve_run_id,
    schema_version,
    parser_version,
    sha256_file,
    sha256_text,
    utc_now,
    write_json,
)


DEFAULT_COUNTRY = "IR"
DEFAULT_MONTH = "2026-03"


@dataclass(frozen=True)
class AsnDelegatedRecord:
    rir: str
    country: str | None
    start_asn: int
    end_asn: int
    allocation_date: str | None
    allocation_status: str | None
    raw_line: str

    @property
    def span(self) -> int:
        return self.end_asn - self.start_asn + 1


class AsnDelegatedIndex:
    def __init__(self, records: list[AsnDelegatedRecord]) -> None:
        self.records = sorted(records, key=lambda record: (record.start_asn, record.end_asn))
        self.starts = [record.start_asn for record in self.records]

    def lookup(self, asn: int) -> AsnDelegatedRecord | None:
        idx = bisect.bisect_right(self.starts, asn) - 1
        best: AsnDelegatedRecord | None = None
        while idx >= 0 and self.records[idx].start_asn <= asn:
            record = self.records[idx]
            if record.end_asn >= asn and (best is None or record.span < best.span):
                best = record
            idx -= 1
        return best


def default_delegated_file(month: str) -> Path:
    parsed_month = parse_month(month)
    year, month_num = [int(part) for part in parsed_month.split("-")]
    last_day = calendar.monthrange(year, month_num)[1]
    snapshot = f"{year:04d}{month_num:02d}{last_day:02d}"
    return repo_root() / "data" / "raw" / "registry" / "delegated_monthly_go" / f"nro_delegated_stats_{parsed_month}_{snapshot}.txt"


def parse_delegated_asn_line(line: str) -> AsnDelegatedRecord | None:
    parts = line.strip().split("|")
    if len(parts) < 7 or parts[2].lower() != "asn":
        return None
    if parts[1] == "*" or parts[3] == "*" or parts[4] == "*":
        return None
    try:
        start_asn = int(parts[3])
        count = int(parts[4])
    except ValueError:
        return None
    if count <= 0:
        return None
    country = parts[1].strip().upper()
    return AsnDelegatedRecord(
        rir=parts[0].strip().lower(),
        country=country if COUNTRY_RE.match(country) else None,
        start_asn=start_asn,
        end_asn=start_asn + count - 1,
        allocation_date=parts[5] or None,
        allocation_status=parts[6] or None,
        raw_line=line.rstrip("\n"),
    )


def load_delegated_asn_index(path: Path) -> tuple[AsnDelegatedIndex, str | None]:
    records: list[AsnDelegatedRecord] = []
    snapshot_time: str | None = None
    with path.open(encoding="utf-8") as f:
        for line in f:
            parts = line.strip().split("|")
            if len(parts) >= 6 and parts[0] == "2":
                snapshot_time = _date_to_snapshot_time(parts[5])
                continue
            record = parse_delegated_asn_line(line)
            if record is not None:
                records.append(record)
    return AsnDelegatedIndex(records), snapshot_time


def read_prefix_geo_targets(path: Path, *, country: str, month: str) -> list[tuple[int, str]]:
    targets: list[tuple[int, str]] = []
    target_country = country.upper()
    target_month = parse_month(month)
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for line_no, row in enumerate(reader, start=2):
            if str(row.get("analysis_month")) != target_month:
                continue
            baseline_country = str(row.get("baseline_country") or "").upper()
            if baseline_country != target_country:
                continue
            targets.append((parse_asn(row.get("asn"), f"{path}:{line_no}"), target_month))
    return sorted(set(targets))


def read_existing_input(path: Path) -> list[tuple[int, str]]:
    if not path.exists():
        return []
    return [(item["asn"], item["month"]) for item in read_asn_months(path)]


def write_asn_months(path: Path, rows: list[tuple[int, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["asn", "month"])
        writer.writeheader()
        for asn, month in sorted(rows):
            writer.writerow({"asn": asn, "month": month})


def build_payload(
    *,
    asn: int,
    month: str,
    run_id: str,
    config: dict[str, Any],
    record: AsnDelegatedRecord | None,
    delegated_file: Path,
    delegated_sha256: str,
    source_snapshot_time: str | None,
) -> dict[str, Any]:
    fetch_time = utc_now()
    delegated: dict[str, Any] = {
        "status": "not_found",
        "fetched_at": fetch_time,
        "raw_response_path": relative_to_root(delegated_file),
        "raw_response_sha256": delegated_sha256,
        "source_snapshot_time": source_snapshot_time,
    }
    normalized: dict[str, Any] = {}
    if record is not None:
        delegated.update(
            {
                "status": "ok",
                "rir": record.rir,
                "registered_rir": record.rir,
                "country": record.country,
                "allocated_country": record.country,
                "start_asn": record.start_asn,
                "end_asn": record.end_asn,
                "allocation_date": record.allocation_date,
                "allocation_status": record.allocation_status,
                "raw_line": record.raw_line,
            }
        )
        normalized.update(
            {
                "allocated_country": record.country,
                "registered_rir": record.rir,
                "allocation_date": record.allocation_date,
                "allocation_status": record.allocation_status,
            }
        )
    return {
        "record_id": f"raw_registry_delegated_local_{asn}_{month}",
        "run_id": run_id,
        "schema_version": schema_version(config),
        "parser_version": parser_version(config),
        "asn": asn,
        "analysis_month": month,
        "fetch_time": fetch_time,
        "source_snapshot_time": source_snapshot_time,
        "sources": {
            "delegated": delegated,
            "rdap": {
                "status": "not_fetched",
                "reason": "local_delegated_only",
                "fetched_at": fetch_time,
            },
            "whois": {
                "status": "not_fetched",
                "reason": "local_delegated_only",
                "fetched_at": fetch_time,
            },
        },
        "normalized": {key: value for key, value in normalized.items() if value is not None},
    }


def _date_to_snapshot_time(value: str | None) -> str | None:
    if not value or len(value) != 8 or not value.isdigit():
        return None
    return f"{value[:4]}-{value[4:6]}-{value[6:8]}T00:00:00Z"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect local delegated registry manifests for prefix_geo targets.")
    add_common_args(parser)
    parser.add_argument("--country", default=DEFAULT_COUNTRY)
    parser.add_argument("--month", default=DEFAULT_MONTH)
    parser.add_argument("--delegated-file", type=Path, default=None)
    parser.add_argument("--prefix-geo-file", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--input-output", type=Path, default=None)
    parser.add_argument("--include-existing-input", action="store_true", default=True)
    args = parser.parse_args(argv)

    config = load_config(args.config)
    run_id = resolve_run_id(config, args.run_id)
    month = parse_month(args.month)
    staging_root = Path(config["paths"]["staging_root"])
    raw_root = Path(config["paths"]["raw_root"])
    delegated_file = args.delegated_file or default_delegated_file(month)
    prefix_geo_file = args.prefix_geo_file or staging_root / "prefixes" / "asn_prefix_geo_monthly.csv"
    output_dir = args.output_dir or raw_root / "registry" / "manifest"
    input_output = args.input_output or repo_root() / "data" / "input" / f"asn_months_registry_{args.country.upper()}_{month}.csv"

    delegated_file = delegated_file if delegated_file.is_absolute() else Path.cwd() / delegated_file
    prefix_geo_file = prefix_geo_file if prefix_geo_file.is_absolute() else Path.cwd() / prefix_geo_file
    output_dir = output_dir if output_dir.is_absolute() else Path.cwd() / output_dir
    input_output = input_output if input_output.is_absolute() else Path.cwd() / input_output
    ensure_dirs([output_dir, input_output.parent])

    delegated_index, source_snapshot_time = load_delegated_asn_index(delegated_file)
    delegated_sha256 = sha256_file(delegated_file)
    prefix_targets = read_prefix_geo_targets(prefix_geo_file, country=args.country, month=month)
    existing_rows = read_existing_input(resolve_input(config, args.input)) if args.include_existing_input else []
    input_rows = sorted(set(existing_rows) | set(prefix_targets))
    write_asn_months(input_output, input_rows)

    log_rows: list[dict[str, Any]] = []
    for asn, target_month in prefix_targets:
        record = delegated_index.lookup(asn)
        payload = build_payload(
            asn=asn,
            month=target_month,
            run_id=run_id,
            config=config,
            record=record,
            delegated_file=delegated_file,
            delegated_sha256=delegated_sha256,
            source_snapshot_time=source_snapshot_time,
        )
        output_path = append_only_path(output_dir / f"{asn}_{target_month}_{run_id}.json")
        write_json(output_path, payload)
        log_rows.append(
            {
                "asn": asn,
                "analysis_month": target_month,
                "raw_evidence_path": relative_to_root(output_path),
                "raw_evidence_sha256": sha256_file(output_path),
                "delegated_status": payload["sources"]["delegated"]["status"],
                "allocated_country": payload["normalized"].get("allocated_country"),
                "manifest_sha256": sha256_text(json.dumps(payload, ensure_ascii=False, sort_keys=True)),
            }
        )

    log_dir = Path(config["paths"]["logs_root"])
    log_dir = log_dir if log_dir.is_absolute() else Path.cwd() / log_dir
    log_path = append_only_path(log_dir / f"collect_registry_delegated_local_{run_id}.json")
    write_json(
        log_path,
        {
            "run_id": run_id,
            "country": args.country.upper(),
            "month": month,
            "fetch_time": utc_now(),
            "delegated_file": relative_to_root(delegated_file),
            "delegated_sha256": delegated_sha256,
            "prefix_geo_file": relative_to_root(prefix_geo_file),
            "input_output": relative_to_root(input_output),
            "records": log_rows,
        },
    )
    print(
        f"saved {len(log_rows)} local delegated registry manifests; "
        f"input={relative_to_root(input_output)} log={relative_to_root(log_path)}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Map staged ASN prefixes to delegated countries for a monthly geo profile."""

from __future__ import annotations

import argparse
import bisect
import calendar
import ipaddress
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pipeline_utils import (
    COUNTRY_RE,
    add_common_args,
    as_int,
    ensure_dirs,
    load_config,
    parse_month,
    parser_version,
    read_table,
    relative_to_root,
    repo_root,
    resolve_run_id,
    schema_version,
    sha256_file,
    utc_now,
    write_json,
    write_table,
)


UNKNOWN_COUNTRY = "ZZ"
DEFAULT_COUNTRY = "IR"
DEFAULT_MONTH = "2026-03"
DEFAULT_FOREIGN_RATIO_THRESHOLD = 0.5


@dataclass(frozen=True)
class DelegatedBlock:
    family: int
    start: int
    end: int
    country: str
    rir: str
    status: str
    raw_line: str

    @property
    def span(self) -> int:
        return self.end - self.start + 1


class DelegatedIndex:
    def __init__(self, blocks: list[DelegatedBlock]) -> None:
        self.blocks = sorted(blocks, key=lambda block: (block.family, block.start, block.end))
        self.by_family: dict[int, list[DelegatedBlock]] = {
            4: [block for block in self.blocks if block.family == 4],
            6: [block for block in self.blocks if block.family == 6],
        }
        self.starts: dict[int, list[int]] = {}
        self.max_ends: dict[int, list[int]] = {}
        for family, family_blocks in self.by_family.items():
            self.starts[family] = [block.start for block in family_blocks]
            max_ends: list[int] = []
            current_max = -1
            for block in family_blocks:
                current_max = max(current_max, block.end)
                max_ends.append(current_max)
            self.max_ends[family] = max_ends

    def lookup(self, prefix: str) -> DelegatedBlock | None:
        network = ipaddress.ip_network(prefix, strict=False)
        family = network.version
        blocks = self.by_family[family]
        if not blocks:
            return None

        start = int(network.network_address)
        end = int(network.broadcast_address)
        idx = bisect.bisect_right(self.starts[family], start) - 1
        if idx < 0 or self.max_ends[family][idx] < end:
            return None

        best: DelegatedBlock | None = None
        best_span: int | None = None
        while idx >= 0:
            if self.max_ends[family][idx] < end:
                break
            block = blocks[idx]
            if block.end >= end:
                if best_span is None or block.span < best_span:
                    best = block
                    best_span = block.span
            if best_span is not None and best_span <= end - block.start + 1:
                break
            idx -= 1
        return best


def default_delegated_file(month: str) -> Path:
    parsed_month = parse_month(month)
    year, month_num = [int(part) for part in parsed_month.split("-")]
    last_day = calendar.monthrange(year, month_num)[1]
    snapshot = f"{year:04d}{month_num:02d}{last_day:02d}"
    return repo_root() / "data" / "raw" / "registry" / "delegated_monthly_go" / f"nro_delegated_stats_{parsed_month}_{snapshot}.txt"


def parse_delegated_line(line: str) -> DelegatedBlock | None:
    parts = line.strip().split("|")
    if len(parts) < 7:
        return None
    rir, country, record_type, start_text, value_text, _date, status = parts[:7]
    record_type = record_type.lower()
    if record_type not in {"ipv4", "ipv6"}:
        return None
    if start_text == "*" or value_text == "*":
        return None

    country = country.strip().upper()
    if not COUNTRY_RE.match(country):
        country = UNKNOWN_COUNTRY
    try:
        if record_type == "ipv4":
            start_addr = ipaddress.IPv4Address(start_text)
            count = int(value_text)
            if count <= 0:
                return None
            start = int(start_addr)
            end = start + count - 1
            if end > int(ipaddress.IPv4Address("255.255.255.255")):
                return None
            family = 4
        else:
            prefix_len = int(value_text)
            network = ipaddress.IPv6Network(f"{start_text}/{prefix_len}", strict=False)
            start = int(network.network_address)
            end = int(network.broadcast_address)
            family = 6
    except ValueError:
        return None

    return DelegatedBlock(
        family=family,
        start=start,
        end=end,
        country=country,
        rir=rir.strip().lower(),
        status=status.strip().lower(),
        raw_line=line.rstrip("\n"),
    )


def load_delegated_index(path: Path) -> DelegatedIndex:
    blocks: list[DelegatedBlock] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            block = parse_delegated_line(line)
            if block is not None:
                blocks.append(block)
    return DelegatedIndex(blocks)


def parse_prefix_list(value: Any) -> list[str]:
    if not value:
        return []
    parsed = json.loads(str(value))
    if not isinstance(parsed, list):
        raise ValueError("prefix JSON field must be a list")
    prefixes: list[str] = []
    for item in parsed:
        network = ipaddress.ip_network(str(item), strict=False)
        prefixes.append(str(network))
    return sorted(prefixes)


def is_real_country(country: str | None) -> bool:
    if not country:
        return False
    country = country.upper()
    return country != UNKNOWN_COUNTRY and bool(COUNTRY_RE.match(country))


def choose_dominant_country(country_counts: dict[str, int]) -> tuple[str | None, int]:
    if not country_counts:
        return UNKNOWN_COUNTRY, 0
    country, count = sorted(country_counts.items(), key=lambda item: (-item[1], item[0]))[0]
    return country, count


def classify_prefixes(prefixes: list[str], delegated_index: DelegatedIndex) -> tuple[dict[str, int], int, int]:
    country_counts: dict[str, int] = {}
    mapped_count = 0
    for prefix in prefixes:
        block = delegated_index.lookup(prefix)
        country = block.country if block is not None else UNKNOWN_COUNTRY
        if block is not None:
            mapped_count += 1
        country_counts[country] = country_counts.get(country, 0) + 1
    return country_counts, mapped_count, len(prefixes) - mapped_count


def build_geo_row(
    inventory_row: dict[str, Any],
    delegated_index: DelegatedIndex,
    *,
    run_id: str,
    config: dict[str, Any],
    delegated_file: Path,
    delegated_sha256: str,
    foreign_ratio_threshold: float,
) -> dict[str, Any]:
    prefixes = parse_prefix_list(inventory_row.get("prefixes_v4_json")) + parse_prefix_list(inventory_row.get("prefixes_v6_json"))
    prefix_count = len(prefixes)
    country_counts, mapped_count, unmapped_count = classify_prefixes(prefixes, delegated_index)
    dominant_country, dominant_count = choose_dominant_country(country_counts)
    baseline_country = str(inventory_row.get("as_country") or inventory_row.get("filter_country") or "").strip().upper()
    if not COUNTRY_RE.match(baseline_country):
        baseline_country = UNKNOWN_COUNTRY

    foreign_prefix_count = sum(
        count
        for country, count in country_counts.items()
        if is_real_country(country) and country != baseline_country
    )
    dominant_ratio = dominant_count / prefix_count if prefix_count else 0.0
    foreign_ratio = foreign_prefix_count / prefix_count if prefix_count else 0.0
    geo_conflict = (
        is_real_country(dominant_country)
        and dominant_country != baseline_country
        and foreign_ratio >= foreign_ratio_threshold
    )
    asn = as_int(inventory_row["asn"])
    month = parse_month(inventory_row["analysis_month"])

    return {
        "record_id": f"prefix_geo_{asn}_{month}",
        "run_id": run_id,
        "schema_version": schema_version(config),
        "parser_version": parser_version(config),
        "asn": asn,
        "analysis_month": month,
        "baseline_country": baseline_country,
        "prefix_count": prefix_count,
        "mapped_prefix_count": mapped_count,
        "unmapped_prefix_count": unmapped_count,
        "dominant_prefix_country": dominant_country,
        "dominant_prefix_country_ratio": round(dominant_ratio, 6),
        "foreign_prefix_count": foreign_prefix_count,
        "foreign_prefix_coverage_ratio": round(foreign_ratio, 6),
        "geo_conflict_flag": geo_conflict,
        "raw_evidence_path": inventory_row.get("raw_evidence_path"),
        "raw_evidence_sha256": inventory_row.get("raw_evidence_sha256"),
        "geo_evidence_path": relative_to_root(delegated_file),
        "geo_evidence_sha256": delegated_sha256,
        "evidence_summary": (
            f"baseline={baseline_country}; dominant={dominant_country or 'missing'}; "
            f"prefix_count={prefix_count}; mapped={mapped_count}; foreign_ratio={foreign_ratio:.6f}; "
            f"geo_conflict={int(geo_conflict)}"
        ),
    }


def build_rows(
    inventory_rows: list[dict[str, Any]],
    delegated_index: DelegatedIndex,
    *,
    country: str,
    month: str,
    run_id: str,
    config: dict[str, Any],
    delegated_file: Path,
    foreign_ratio_threshold: float,
) -> list[dict[str, Any]]:
    delegated_sha256 = sha256_file(delegated_file)
    rows: list[dict[str, Any]] = []
    target_country = country.upper()
    target_month = parse_month(month)
    for row in inventory_rows:
        if str(row.get("analysis_month")) != target_month:
            continue
        row_country = str(row.get("filter_country") or row.get("as_country") or "").upper()
        if row_country != target_country:
            continue
        rows.append(
            build_geo_row(
                row,
                delegated_index,
                run_id=run_id,
                config=config,
                delegated_file=delegated_file,
                delegated_sha256=delegated_sha256,
                foreign_ratio_threshold=foreign_ratio_threshold,
            )
        )
    return rows


def artifact_entry(path: Path) -> dict[str, Any]:
    return {
        "path": relative_to_root(path),
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
    }


def maybe_artifact_entry(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return artifact_entry(path)


def write_artifact_manifest(
    *,
    manifest_path: Path,
    run_id: str,
    config: dict[str, Any],
    country: str,
    month: str,
    input_file: Path,
    delegated_file: Path,
    output_csv: Path,
    output_parquet: Path,
    row_count: int,
    foreign_ratio_threshold: float,
) -> None:
    manifest = {
        "artifact": "asn_prefix_geo_monthly",
        "layer": "staging",
        "analysis_unit": "(asn, analysis_month)",
        "producer": "scripts/stage_prefix_geo.py",
        "command": "python3 " + " ".join(sys.argv),
        "generated_at": utc_now(),
        "run_id": run_id,
        "schema_version": schema_version(config),
        "parser_version": parser_version(config),
        "parameters": {
            "country": country.upper(),
            "month": month,
            "foreign_ratio_threshold": foreign_ratio_threshold,
        },
        "inputs": {
            "prefix_inventory": artifact_entry(input_file),
            "delegated_snapshot": artifact_entry(delegated_file),
        },
        "outputs": {
            "csv": artifact_entry(output_csv),
            "parquet": maybe_artifact_entry(output_parquet),
        },
        "row_count": row_count,
        "validation_command": "python3 scripts/validate_outputs.py --stage prefix_geo",
        "meaning": "ASN 起源 prefix 的静态 delegated 国家画像。",
        "caveats": [
            "dominant_prefix_country 不是运营国家判断。",
            "geo_conflict_flag 只是人工复核线索，不是最终异常裁定。",
            "未匹配 prefix 记为 ZZ，且不触发 geo_conflict_flag。",
        ],
    }
    write_json(manifest_path, manifest)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Stage monthly ASN prefix geo profiles.")
    add_common_args(parser)
    parser.add_argument("--country", default=DEFAULT_COUNTRY)
    parser.add_argument("--month", default=DEFAULT_MONTH)
    parser.add_argument("--delegated-file", type=Path, default=None)
    parser.add_argument("--foreign-ratio-threshold", type=float, default=DEFAULT_FOREIGN_RATIO_THRESHOLD)
    parser.add_argument("--input-file", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args(argv)

    config = load_config(args.config)
    run_id = resolve_run_id(config, args.run_id)
    month = parse_month(args.month)
    staging_root = Path(config["paths"]["staging_root"])
    input_file = args.input_file or staging_root / "prefixes" / "asn_prefix_inventory_monthly.csv"
    output_dir = args.output_dir or staging_root / "prefixes"
    delegated_file = args.delegated_file or default_delegated_file(month)

    input_file = input_file if input_file.is_absolute() else Path.cwd() / input_file
    output_dir = output_dir if output_dir.is_absolute() else Path.cwd() / output_dir
    delegated_file = delegated_file if delegated_file.is_absolute() else Path.cwd() / delegated_file
    ensure_dirs([output_dir])

    if not delegated_file.exists():
        raise FileNotFoundError(f"delegated file not found: {delegated_file}")
    inventory_rows = read_table(input_file, None)
    delegated_index = load_delegated_index(delegated_file)
    rows = build_rows(
        inventory_rows,
        delegated_index,
        country=args.country,
        month=month,
        run_id=run_id,
        config=config,
        delegated_file=delegated_file,
        foreign_ratio_threshold=args.foreign_ratio_threshold,
    )
    output_csv = output_dir / "asn_prefix_geo_monthly.csv"
    output_parquet = output_dir / "asn_prefix_geo_monthly.parquet"
    write_table(rows, output_csv, output_parquet)
    write_artifact_manifest(
        manifest_path=output_dir / "asn_prefix_geo_monthly.manifest.json",
        run_id=run_id,
        config=config,
        country=args.country,
        month=month,
        input_file=input_file,
        delegated_file=delegated_file,
        output_csv=output_csv,
        output_parquet=output_parquet,
        row_count=len(rows),
        foreign_ratio_threshold=args.foreign_ratio_threshold,
    )
    print(f"saved {len(rows)} prefix_geo staging rows to {relative_to_root(output_dir)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Standardize registry raw evidence into the monthly registry baseline."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from pipeline_utils import (
    COUNTRY_RE,
    add_common_args,
    clean_text,
    ensure_dirs,
    load_config,
    normalize_country,
    parser_version,
    read_asn_months,
    read_json,
    relative_to_root,
    resolve_input,
    resolve_run_id,
    schema_version,
    sha256_file,
    utc_now,
    write_table,
)


KEYWORDS = {
    "cloud_or_cdn": ("cloud", "cdn", "hosting", "compute", "edge", "akamai", "amazon", "google", "microsoft"),
    "crossborder": ("global", "international", "worldwide", "group", "telecom", "communications"),
    "hosting_or_lease": ("hosting", "lease", "leased", "colo", "colocation", "managed", "proxy"),
}


def find_manifest(raw_dir: Path, asn: int, month: str, run_id: str) -> Path:
    matches = sorted(raw_dir.glob(f"{asn}_{month}_{run_id}*.json"))
    if matches:
        return matches[-1]
    raise FileNotFoundError(f"missing registry raw manifest for AS{asn} {month} in {raw_dir}")


def normalize_record(path: Path, run_id: str, config: dict[str, Any]) -> dict[str, Any]:
    payload = read_json(path)
    asn = int(payload["asn"])
    month = str(payload["analysis_month"])
    normalized = payload.get("normalized") or {}
    sources = payload.get("sources") or {}

    delegated = sources.get("delegated") or {}
    rdap = sources.get("rdap") or {}
    whois = sources.get("whois") or {}

    allocated_country = _country_or_none(
        normalized.get("allocated_country") or delegated.get("allocated_country") or delegated.get("country")
    )
    registered_country = _country_or_none(
        normalized.get("registered_country")
        or rdap.get("registered_country")
        or rdap.get("country")
        or whois.get("registered_country")
        or whois.get("country")
    )
    registered_rir = clean_text(
        normalized.get("registered_rir") or delegated.get("registered_rir") or delegated.get("rir") or rdap.get("rir")
    )
    org_name = clean_text(normalized.get("org_name") or rdap.get("org_name") or rdap.get("name") or whois.get("org_name"))
    parent_org = clean_text(normalized.get("parent_org") or rdap.get("parent_org") or whois.get("parent_org"))
    allocation_date = clean_text(normalized.get("allocation_date") or delegated.get("allocation_date"))
    allocation_status = clean_text(normalized.get("allocation_status") or delegated.get("allocation_status"))

    countries = {country for country in [allocated_country, registered_country] if country}
    source_countries = [
        _country_or_none(delegated.get("country")),
        _country_or_none(delegated.get("allocated_country")),
        _country_or_none(rdap.get("country")),
        _country_or_none(rdap.get("registered_country")),
        _country_or_none(whois.get("country")),
        _country_or_none(whois.get("registered_country")),
    ]
    countries.update(country for country in source_countries if country)
    multi_country_registry_flag = len(countries) > 1
    admin_conflict_flag = bool(
        (allocated_country and registered_country and allocated_country != registered_country)
        or multi_country_registry_flag
    )

    org_blob = " ".join(filter(None, [org_name, parent_org])).lower()
    cloud_or_cdn_flag = _contains_any(org_blob, KEYWORDS["cloud_or_cdn"])
    crossborder_group_flag = _contains_any(org_blob, KEYWORDS["crossborder"])
    hosting_or_lease_hint_flag = _contains_any(org_blob, KEYWORDS["hosting_or_lease"])

    evidence_summary = (
        f"allocated_country={allocated_country or 'missing'}; "
        f"registered_country={registered_country or 'missing'}; "
        f"admin_conflict={int(admin_conflict_flag)}; "
        f"multi_country_registry={int(multi_country_registry_flag)}"
    )

    return {
        "record_id": f"reg_{asn}_{month}",
        "run_id": run_id,
        "schema_version": schema_version(config),
        "parser_version": parser_version(config),
        "asn": asn,
        "analysis_month": month,
        "allocated_country": allocated_country,
        "registered_country": registered_country,
        "registered_rir": registered_rir,
        "org_name": org_name,
        "parent_org": parent_org,
        "allocation_date": allocation_date,
        "allocation_status": allocation_status,
        "admin_conflict_flag": admin_conflict_flag,
        "multi_country_registry_flag": multi_country_registry_flag,
        "cloud_or_cdn_flag": cloud_or_cdn_flag,
        "crossborder_group_flag": crossborder_group_flag,
        "hosting_or_lease_hint_flag": hosting_or_lease_hint_flag,
        "evidence_summary": evidence_summary,
        "raw_evidence_path": relative_to_root(path),
        "raw_evidence_sha256": sha256_file(path),
        "source_snapshot_time": _source_snapshot_time(payload, delegated, rdap, whois),
        "fetch_time": clean_text(payload.get("fetch_time")) or utc_now(),
    }


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)


def _country_or_none(value: Any) -> str | None:
    country = normalize_country(value)
    if not country:
        return None
    return country if COUNTRY_RE.match(country) else None


def _source_snapshot_time(payload: dict[str, Any], *sources: dict[str, Any]) -> str | None:
    candidates = [clean_text(payload.get("source_snapshot_time"))]
    candidates.extend(clean_text(source.get("source_snapshot_time")) for source in sources)
    values = [value for value in candidates if value]
    return max(values) if values else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build registry staging output.")
    add_common_args(parser)
    parser.add_argument("--raw-dir", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args(argv)

    config = load_config(args.config)
    run_id = resolve_run_id(config, args.run_id)
    input_path = resolve_input(config, args.input)
    raw_dir = args.raw_dir or Path(config["paths"]["raw_root"]) / "registry" / "manifest"
    output_dir = args.output_dir or Path(config["paths"]["staging_root"]) / "registry"
    raw_dir = raw_dir if raw_dir.is_absolute() else Path.cwd() / raw_dir
    output_dir = output_dir if output_dir.is_absolute() else Path.cwd() / output_dir
    ensure_dirs([output_dir])

    rows = [
        normalize_record(find_manifest(raw_dir, item["asn"], item["month"], run_id), run_id, config)
        for item in read_asn_months(input_path)
    ]
    write_table(
        rows,
        output_dir / "asn_registry_baseline_monthly.csv",
        output_dir / "asn_registry_baseline_monthly.parquet",
    )
    print(f"saved {len(rows)} registry staging rows to {relative_to_root(output_dir)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

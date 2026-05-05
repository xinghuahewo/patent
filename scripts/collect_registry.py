#!/usr/bin/env python3
"""Collect registry raw evidence for the ASN/month input set.

The default mode is intentionally offline-safe: it records a raw evidence
manifest with source status instead of fabricating registry facts. With
``--online`` the collector fetches RIR delegated snapshots and RDAP responses,
saves those raw responses, and indexes the extracted ASN evidence in the per
``(asn, month)`` manifest.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from pipeline_utils import (
    add_common_args,
    append_only_path,
    ensure_dirs,
    load_config,
    read_asn_months,
    relative_to_root,
    resolve_input,
    resolve_run_id,
    schema_version,
    parser_version,
    sha256_file,
    sha256_text,
    utc_now,
    write_json,
)

RIR_DELEGATED_URLS = {
    "afrinic": "https://ftp.afrinic.net/pub/stats/afrinic/delegated-afrinic-latest",
    "apnic": "https://ftp.apnic.net/stats/apnic/delegated-apnic-latest",
    "arin": "https://ftp.arin.net/pub/stats/arin/delegated-arin-extended-latest",
    "lacnic": "https://ftp.lacnic.net/pub/stats/lacnic/delegated-lacnic-latest",
    "ripencc": "https://ftp.ripe.net/pub/stats/ripencc/delegated-ripencc-latest",
}

RDAP_BOOTSTRAP_URL = "https://data.iana.org/rdap/asn.json"
USER_AGENT = "asn-mismatch-pipeline/0.1 (+registry evidence collection)"
COUNTRY_NAME_ALIASES = {
    "AUSTRALIA": "AU",
    "AZERBAIJAN": "AZ",
    "BULGARIA": "BG",
    "CANADA": "CA",
    "FRANCE": "FR",
    "GERMANY": "DE",
    "GREECE": "GR",
    "IRAN": "IR",
    "IRAN, ISLAMIC REPUBLIC OF": "IR",
    "ISLAMIC REPUBLIC OF IRAN": "IR",
    "MOLDOVA": "MD",
    "ROMANIA": "RO",
    "SWITZERLAND": "CH",
    "TURKEY": "TR",
    "UNITED ARAB EMIRATES": "AE",
    "UAE": "AE",
    "UNITED KINGDOM": "GB",
    "GREAT BRITAIN": "GB",
    "ENGLAND": "GB",
    "UNITED STATES": "US",
    "UNITED STATES OF AMERICA": "US",
    "USA": "US",
}


@dataclass(frozen=True)
class DelegatedRecord:
    rir: str
    country: str | None
    start_asn: int
    end_asn: int
    allocation_date: str | None
    allocation_status: str | None
    raw_line: str


@dataclass(frozen=True)
class FetchResult:
    status: str
    fetched_at: str
    http_status: int | None = None
    text: str | None = None
    error: str | None = None


def build_payload(asn: int, month: str, run_id: str, config: dict[str, Any]) -> dict[str, Any]:
    fetch_time = utc_now()
    return {
        "record_id": f"raw_registry_{asn}_{month}",
        "run_id": run_id,
        "schema_version": schema_version(config),
        "parser_version": parser_version(config),
        "asn": asn,
        "analysis_month": month,
        "fetch_time": fetch_time,
        "sources": {
            "delegated": {
                "status": "not_fetched",
                "reason": "offline_default_raw_manifest",
                "fetched_at": fetch_time,
            },
            "rdap": {
                "status": "not_fetched",
                "reason": "offline_default_raw_manifest",
                "fetched_at": fetch_time,
            },
            "whois": {
                "status": "not_fetched",
                "reason": "offline_default_raw_manifest",
                "fetched_at": fetch_time,
            },
        },
        "normalized": {},
    }


def fetch_text(url: str, timeout: int, max_retries: int) -> FetchResult:
    last_error: str | None = None
    for attempt in range(max_retries + 1):
        fetched_at = utc_now()
        try:
            request = Request(url, headers={"User-Agent": USER_AGENT})
            with urlopen(request, timeout=timeout) as response:
                charset = response.headers.get_content_charset() or "utf-8"
                body = response.read().decode(charset, errors="replace")
                return FetchResult(
                    status="ok",
                    fetched_at=fetched_at,
                    http_status=getattr(response, "status", None),
                    text=body,
                )
        except HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")[:2000]
            last_error = f"HTTP {exc.code}: {error_body}"
            if 400 <= exc.code < 500:
                return FetchResult("error", fetched_at, exc.code, error=last_error)
        except (URLError, TimeoutError, OSError) as exc:
            last_error = str(exc)
        if attempt < max_retries:
            time.sleep(min(2**attempt, 5))
    return FetchResult("error", utc_now(), error=last_error or "unknown fetch error")


def save_text(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def parse_delegated_records(text: str, rir: str) -> tuple[list[DelegatedRecord], str | None]:
    records: list[DelegatedRecord] = []
    snapshot_time: str | None = None
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        parts = line.split("|")
        if len(parts) < 7:
            continue
        if parts[0] == "2":
            snapshot_time = _date_to_snapshot_time(parts[5] if len(parts) > 5 else None)
            continue
        if parts[2].lower() != "asn":
            continue
        try:
            start_asn = int(parts[3])
            count = int(parts[4])
        except ValueError:
            continue
        country = parts[1].upper() if len(parts[1]) == 2 and parts[1] != "*" else None
        records.append(
            DelegatedRecord(
                rir=rir,
                country=country,
                start_asn=start_asn,
                end_asn=start_asn + max(count, 1) - 1,
                allocation_date=parts[5] or None,
                allocation_status=parts[6] or None,
                raw_line=line,
            )
        )
    return records, snapshot_time


def find_delegated_record(asn: int, records_by_rir: dict[str, list[DelegatedRecord]]) -> DelegatedRecord | None:
    for records in records_by_rir.values():
        for record in records:
            if record.start_asn <= asn <= record.end_asn:
                return record
    return None


def build_delegated_snapshots(
    config: dict[str, Any],
    run_id: str,
    registry_root: Path,
) -> tuple[dict[str, dict[str, Any]], dict[str, list[DelegatedRecord]]]:
    delegated_config = config.get("sources", {}).get("registry", {}).get("delegated", {})
    include_rirs = [str(rir).lower() for rir in delegated_config.get("include_rirs", RIR_DELEGATED_URLS)]
    timeout = int(delegated_config.get("timeout_sec", 30))
    max_retries = int(delegated_config.get("max_retries", 3))
    if not delegated_config.get("enabled", True):
        return {
            rir: {"status": "not_fetched", "reason": "delegated_disabled", "fetched_at": utc_now()}
            for rir in include_rirs
        }, {}

    source_status: dict[str, dict[str, Any]] = {}
    records_by_rir: dict[str, list[DelegatedRecord]] = {}
    delegated_dir = registry_root / "delegated"
    ensure_dirs([delegated_dir])

    for rir in include_rirs:
        url = RIR_DELEGATED_URLS.get(rir)
        fetched_at = utc_now()
        if not url:
            source_status[rir] = {
                "status": "error",
                "fetched_at": fetched_at,
                "error": f"unknown RIR {rir}",
            }
            continue
        result = fetch_text(url, timeout, max_retries)
        status: dict[str, Any] = {
            "status": result.status,
            "url": url,
            "fetched_at": result.fetched_at,
            "http_status": result.http_status,
        }
        if result.status == "ok" and result.text is not None:
            snapshot_path = append_only_path(delegated_dir / f"{rir}_{run_id}.txt")
            save_text(snapshot_path, result.text)
            records, snapshot_time = parse_delegated_records(result.text, rir)
            records_by_rir[rir] = records
            status.update(
                {
                    "raw_response_path": relative_to_root(snapshot_path),
                    "raw_response_sha256": sha256_file(snapshot_path),
                    "source_snapshot_time": snapshot_time,
                    "record_count": len(records),
                }
            )
        else:
            status["error"] = result.error
        source_status[rir] = status
    return source_status, records_by_rir


def load_rdap_bootstrap(config: dict[str, Any], run_id: str, registry_root: Path) -> tuple[dict[str, Any], dict[str, Any] | None]:
    rdap_config = config.get("sources", {}).get("registry", {}).get("rdap", {})
    if not rdap_config.get("enabled", True):
        return {"status": "not_fetched", "reason": "rdap_disabled", "fetched_at": utc_now()}, None
    timeout = int(rdap_config.get("timeout_sec", 30))
    max_retries = int(rdap_config.get("max_retries", 3))
    result = fetch_text(RDAP_BOOTSTRAP_URL, timeout, max_retries)
    status: dict[str, Any] = {
        "status": result.status,
        "url": RDAP_BOOTSTRAP_URL,
        "fetched_at": result.fetched_at,
        "http_status": result.http_status,
    }
    if result.status != "ok" or result.text is None:
        status["error"] = result.error
        return status, None
    bootstrap_dir = registry_root / "rdap"
    ensure_dirs([bootstrap_dir])
    bootstrap_path = append_only_path(bootstrap_dir / f"asn_bootstrap_{run_id}.json")
    save_text(bootstrap_path, result.text)
    status.update(
        {
            "raw_response_path": relative_to_root(bootstrap_path),
            "raw_response_sha256": sha256_file(bootstrap_path),
        }
    )
    try:
        return status, json.loads(result.text)
    except json.JSONDecodeError as exc:
        status.update({"status": "error", "error": f"invalid RDAP bootstrap JSON: {exc}"})
        return status, None


def rdap_base_url(asn: int, bootstrap: dict[str, Any]) -> str | None:
    for ranges, urls in bootstrap.get("services", []):
        for raw_range in ranges:
            start, end = _parse_asn_range(str(raw_range))
            if start <= asn <= end:
                return str(urls[0]) if urls else None
    return None


def fetch_rdap_record(
    asn: int,
    run_id: str,
    config: dict[str, Any],
    registry_root: Path,
    bootstrap: dict[str, Any] | None,
    bootstrap_status: dict[str, Any],
) -> dict[str, Any]:
    rdap_config = config.get("sources", {}).get("registry", {}).get("rdap", {})
    fetched_at = utc_now()
    if not rdap_config.get("enabled", True):
        return {"status": "not_fetched", "reason": "rdap_disabled", "fetched_at": fetched_at}
    if bootstrap is None:
        return {
            "status": "error",
            "reason": "rdap_bootstrap_unavailable",
            "fetched_at": fetched_at,
            "bootstrap": bootstrap_status,
        }
    base_url = rdap_base_url(asn, bootstrap)
    if not base_url:
        return {"status": "error", "fetched_at": fetched_at, "error": f"no RDAP bootstrap endpoint for AS{asn}"}

    url = urljoin(base_url.rstrip("/") + "/", f"autnum/{asn}")
    result = fetch_text(url, int(rdap_config.get("timeout_sec", 30)), int(rdap_config.get("max_retries", 3)))
    status: dict[str, Any] = {
        "status": result.status,
        "url": url,
        "base_url": base_url,
        "fetched_at": result.fetched_at,
        "http_status": result.http_status,
        "bootstrap": bootstrap_status,
    }
    if result.status == "ok" and result.text is not None:
        rdap_dir = registry_root / "rdap"
        ensure_dirs([rdap_dir])
        rdap_path = append_only_path(rdap_dir / f"{asn}_{run_id}.json")
        save_text(rdap_path, result.text)
        status.update(
            {
                "raw_response_path": relative_to_root(rdap_path),
                "raw_response_sha256": sha256_file(rdap_path),
            }
        )
        try:
            response = json.loads(result.text)
            status.update(extract_rdap_fields(response))
        except json.JSONDecodeError as exc:
            status.update({"status": "error", "error": f"invalid RDAP JSON: {exc}"})
    else:
        status["error"] = result.error
    return status


def extract_rdap_fields(response: dict[str, Any]) -> dict[str, Any]:
    entity_names: list[str] = []
    entity_countries: list[str] = []
    parent_org: str | None = None

    for entity in response.get("entities") or []:
        name = _name_from_entity(entity)
        country = _country_from_entity(entity)
        roles = {str(role).lower() for role in entity.get("roles") or []}
        if name:
            entity_names.append(name)
            if parent_org is None and roles.intersection({"registrant", "administrative", "sponsor"}):
                parent_org = name
        if country:
            entity_countries.append(country)

    rdap_country = _country_code(response.get("country"))
    registered_country = rdap_country or (entity_countries[0] if entity_countries else None)
    org_name = response.get("name") or (entity_names[0] if entity_names else None)
    result = {
        "handle": response.get("handle"),
        "name": response.get("name"),
        "country": registered_country,
        "registered_country": registered_country,
        "org_name": org_name,
        "parent_org": parent_org,
    }
    return {key: value for key, value in result.items() if value}


def build_online_payload(
    asn: int,
    month: str,
    run_id: str,
    config: dict[str, Any],
    delegated_sources: dict[str, dict[str, Any]],
    delegated_records: dict[str, list[DelegatedRecord]],
    rdap_status: dict[str, Any],
) -> dict[str, Any]:
    payload = build_payload(asn, month, run_id, config)
    fetch_time = utc_now()
    delegated_match = find_delegated_record(asn, delegated_records)
    delegated: dict[str, Any] = {
        "status": "not_found",
        "fetched_at": fetch_time,
        "source_status": delegated_sources,
    }
    normalized: dict[str, Any] = {}
    source_snapshot_times = [
        str(source.get("source_snapshot_time"))
        for source in delegated_sources.values()
        if source.get("source_snapshot_time")
    ]
    source_snapshot_time = max(source_snapshot_times) if source_snapshot_times else None
    if delegated_match is not None:
        source = delegated_sources.get(delegated_match.rir, {})
        source_snapshot_time = source.get("source_snapshot_time") or source_snapshot_time
        delegated.update(
            {
                "status": "ok",
                "rir": delegated_match.rir,
                "registered_rir": delegated_match.rir,
                "country": delegated_match.country,
                "allocated_country": delegated_match.country,
                "start_asn": delegated_match.start_asn,
                "end_asn": delegated_match.end_asn,
                "allocation_date": delegated_match.allocation_date,
                "allocation_status": delegated_match.allocation_status,
                "raw_line": delegated_match.raw_line,
                "raw_response_path": source.get("raw_response_path"),
                "raw_response_sha256": source.get("raw_response_sha256"),
                "source_snapshot_time": source.get("source_snapshot_time"),
            }
        )
        normalized.update(
            {
                "allocated_country": delegated_match.country,
                "registered_rir": delegated_match.rir,
                "allocation_date": delegated_match.allocation_date,
                "allocation_status": delegated_match.allocation_status,
            }
        )
    elif any(source.get("status") == "error" for source in delegated_sources.values()):
        delegated["status"] = "partial_error"

    rdap = {key: value for key, value in rdap_status.items() if key != "bootstrap"}
    if rdap.get("registered_country"):
        normalized["registered_country"] = rdap.get("registered_country")
    if rdap.get("org_name"):
        normalized["org_name"] = rdap.get("org_name")
    if rdap.get("parent_org"):
        normalized["parent_org"] = rdap.get("parent_org")

    payload["fetch_time"] = fetch_time
    payload["source_snapshot_time"] = source_snapshot_time
    payload["sources"] = {
        "delegated": delegated,
        "rdap": rdap,
        "whois": {
            "status": "not_fetched",
            "reason": "whois_not_required_for_registry_v1_online",
            "fetched_at": fetch_time,
        },
    }
    payload["normalized"] = {key: value for key, value in normalized.items() if value is not None}
    return payload


def _parse_asn_range(raw_range: str) -> tuple[int, int]:
    if "-" in raw_range:
        start, end = raw_range.split("-", 1)
        return int(start), int(end)
    value = int(raw_range)
    return value, value


def _date_to_snapshot_time(value: str | None) -> str | None:
    if not value or len(value) != 8 or not value.isdigit():
        return None
    return f"{value[:4]}-{value[4:6]}-{value[6:8]}T00:00:00Z"


def _country_code(value: Any) -> str | None:
    text = str(value or "").strip().upper()
    return text if len(text) == 2 and text.isalpha() else None


def _name_from_entity(entity: dict[str, Any]) -> str | None:
    for item in _vcard_items(entity):
        if len(item) >= 4 and item[0] in {"fn", "org"} and item[3]:
            if isinstance(item[3], list):
                return " ".join(str(part) for part in item[3] if part).strip() or None
            return str(item[3]).strip() or None
    return entity.get("handle")


def _country_from_entity(entity: dict[str, Any]) -> str | None:
    country = _country_code(entity.get("country"))
    if country:
        return country
    for item in _vcard_items(entity):
        if len(item) >= 4 and item[0] == "adr":
            if isinstance(item[3], list) and item[3]:
                country = _country_code(item[3][-1]) or _country_from_label(" ".join(str(part) for part in item[3] if part))
                if country:
                    return country
            params = item[1] if isinstance(item[1], dict) else {}
            country = _country_from_label(params.get("label"))
            if country:
                return country
    return None


def _country_from_label(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    direct = _country_code(text)
    if direct:
        return direct
    normalized = " ".join(text.upper().replace("/", " ").replace("\n", " ").split())
    for name, code in sorted(COUNTRY_NAME_ALIASES.items(), key=lambda item: len(item[0]), reverse=True):
        pattern = r"(?<![A-Z])" + re.escape(name) + r"(?![A-Z])"
        if re.search(pattern, normalized):
            return code
    return None


def _vcard_items(entity: dict[str, Any]) -> list[list[Any]]:
    vcard = entity.get("vcardArray")
    if not isinstance(vcard, list) or len(vcard) < 2 or not isinstance(vcard[1], list):
        return []
    return [item for item in vcard[1] if isinstance(item, list)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect registry raw evidence manifests.")
    add_common_args(parser)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--online", action="store_true", help="Fetch delegated snapshots and RDAP responses.")
    args = parser.parse_args(argv)

    config = load_config(args.config)
    run_id = resolve_run_id(config, args.run_id)
    input_path = resolve_input(config, args.input)
    output_dir = args.output_dir or Path(config["paths"]["raw_root"]) / "registry" / "manifest"
    output_dir = output_dir if output_dir.is_absolute() else Path.cwd() / output_dir
    log_dir = Path(config["paths"]["logs_root"])
    log_dir = log_dir if log_dir.is_absolute() else Path.cwd() / log_dir
    ensure_dirs([output_dir, log_dir])
    registry_root = output_dir.parent

    delegated_sources: dict[str, dict[str, Any]] = {}
    delegated_records: dict[str, list[DelegatedRecord]] = {}
    rdap_bootstrap_status: dict[str, Any] = {}
    rdap_bootstrap: dict[str, Any] | None = None
    if args.online:
        delegated_sources, delegated_records = build_delegated_snapshots(config, run_id, registry_root)
        rdap_bootstrap_status, rdap_bootstrap = load_rdap_bootstrap(config, run_id, registry_root)

    log_rows: list[dict[str, Any]] = []
    for item in read_asn_months(input_path):
        asn = item["asn"]
        month = item["month"]
        output_path = append_only_path(output_dir / f"{asn}_{month}_{run_id}.json")
        if args.online:
            rdap_status = fetch_rdap_record(asn, run_id, config, registry_root, rdap_bootstrap, rdap_bootstrap_status)
            payload = build_online_payload(
                asn,
                month,
                run_id,
                config,
                delegated_sources,
                delegated_records,
                rdap_status,
            )
        else:
            payload = build_payload(asn, month, run_id, config)
        write_json(output_path, payload)
        log_rows.append(
            {
                "asn": asn,
                "analysis_month": month,
                "raw_evidence_path": relative_to_root(output_path),
                "raw_evidence_sha256": sha256_file(output_path),
                "status": "saved",
                "mode": "online" if args.online else "offline",
                "manifest_sha256": sha256_text(json.dumps(payload, ensure_ascii=False, sort_keys=True)),
            }
        )

    log_path = append_only_path(log_dir / f"collect_registry_{run_id}.json")
    write_json(
        log_path,
        {
            "run_id": run_id,
            "fetch_time": utc_now(),
            "input_path": relative_to_root(input_path),
            "records": log_rows,
        },
    )
    print(f"saved {len(log_rows)} registry raw manifests; log={relative_to_root(log_path)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

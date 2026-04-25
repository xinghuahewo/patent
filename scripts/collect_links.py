#!/usr/bin/env python3
"""Collect links raw evidence manifests for the ASN/month input set.

The default mode remains offline-safe. With ``--online`` the collector fetches
RIPEstat neighbour snapshots and CAIDA AS Rank relationship data, saves the raw
responses, and indexes those source files in the per ``(asn, month)`` manifest.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from pipeline_utils import (
    add_common_args,
    append_only_path,
    ensure_dirs,
    load_config,
    month_window,
    parser_version,
    read_asn_months,
    relative_to_root,
    resolve_input,
    resolve_run_id,
    schema_version,
    sha256_file,
    sha256_text,
    utc_now,
    write_json,
)

RIPESTAT_NEIGHBOURS_URL = "https://stat.ripe.net/data/asn-neighbours/data.json"
ASRANK_GRAPHQL_URL = "https://api.asrank.caida.org/v2/graphql"
USER_AGENT = "asn-mismatch-pipeline/0.1 (+links evidence collection)"
ASRANK_PAGE_SIZE = 1000


def build_payload(asn: int, month: str, run_id: str, config: dict[str, Any]) -> dict[str, Any]:
    fetch_time = utc_now()
    window_start, window_end = month_window(month)
    return {
        "record_id": f"raw_links_{asn}_{month}",
        "run_id": run_id,
        "schema_version": schema_version(config),
        "parser_version": parser_version(config),
        "asn": asn,
        "analysis_month": month,
        "window_start": window_start,
        "window_end": window_end,
        "fetch_time": fetch_time,
        "sources": {
            "ripestat": {
                "status": "not_fetched",
                "reason": "offline_default_raw_manifest",
                "fetched_at": fetch_time,
            },
            "asrank": {
                "status": "not_fetched",
                "reason": "offline_default_raw_manifest",
                "fetched_at": fetch_time,
            },
        },
        "normalized": {},
    }


def fetch_text(url: str, timeout: int, max_retries: int, body: bytes | None = None) -> dict[str, Any]:
    last_error: str | None = None
    method = "POST" if body is not None else "GET"
    headers = {"User-Agent": USER_AGENT}
    if body is not None:
        headers["Content-Type"] = "application/json"
    for attempt in range(max_retries + 1):
        fetched_at = utc_now()
        try:
            request = Request(url, data=body, headers=headers, method=method)
            with urlopen(request, timeout=timeout) as response:
                charset = response.headers.get_content_charset() or "utf-8"
                return {
                    "status": "ok",
                    "fetched_at": fetched_at,
                    "http_status": getattr(response, "status", None),
                    "text": response.read().decode(charset, errors="replace"),
                }
        except HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")[:2000]
            last_error = f"HTTP {exc.code}: {error_body}"
            if 400 <= exc.code < 500:
                return {"status": "error", "fetched_at": fetched_at, "http_status": exc.code, "error": last_error}
        except (URLError, TimeoutError, OSError) as exc:
            last_error = str(exc)
        if attempt < max_retries:
            time.sleep(min(2**attempt, 5))
    return {"status": "error", "fetched_at": utc_now(), "http_status": None, "error": last_error or "unknown fetch error"}


def save_text(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def previous_month_end(month: str) -> str:
    year, month_num = [int(part) for part in month.split("-")]
    if month_num == 1:
        year -= 1
        month_num = 12
    else:
        month_num -= 1
    import calendar

    day = calendar.monthrange(year, month_num)[1]
    return f"{year:04d}-{month_num:02d}-{day:02d}T23:59:59Z"


def collect_ripestat_snapshot(
    asn: int,
    month: str,
    run_id: str,
    label: str,
    snapshot_time: str,
    config: dict[str, Any],
    links_root: Path,
) -> dict[str, Any]:
    source_config = config.get("sources", {}).get("links", {}).get("ripestat", {})
    if not source_config.get("enabled", True):
        return {"status": "not_fetched", "reason": "ripestat_disabled", "fetched_at": utc_now()}
    query = urlencode({"resource": f"AS{asn}", "starttime": snapshot_time.rstrip("Z")})
    url = f"{RIPESTAT_NEIGHBOURS_URL}?{query}"
    result = fetch_text(url, int(source_config.get("timeout_sec", 30)), int(source_config.get("max_retries", 3)))
    status = {
        "status": result["status"],
        "url": url,
        "snapshot_label": label,
        "snapshot_time": snapshot_time,
        "fetched_at": result["fetched_at"],
        "http_status": result.get("http_status"),
    }
    if result["status"] == "ok":
        path = append_only_path(links_root / "ripestat" / f"{asn}_{month}_{label}_{run_id}.json")
        save_text(path, str(result["text"]))
        status.update(
            {
                "raw_response_path": relative_to_root(path),
                "raw_response_sha256": sha256_file(path),
            }
        )
    else:
        status["error"] = result.get("error")
    return status


def collect_asrank_links(asn: int, month: str, run_id: str, config: dict[str, Any], links_root: Path) -> dict[str, Any]:
    source_config = config.get("sources", {}).get("links", {}).get("asrank", {})
    if not source_config.get("enabled", True):
        return {"status": "not_fetched", "reason": "asrank_disabled", "fetched_at": utc_now()}

    timeout = int(source_config.get("timeout_sec", 30))
    max_retries = int(source_config.get("max_retries", 3))
    offset = 0
    pages: list[dict[str, Any]] = []
    total_count: int | None = None
    fetched_at = utc_now()
    while True:
        query = _asrank_query(asn, ASRANK_PAGE_SIZE, offset)
        body = json.dumps({"query": query}).encode("utf-8")
        result = fetch_text(ASRANK_GRAPHQL_URL, timeout, max_retries, body=body)
        fetched_at = result["fetched_at"]
        if result["status"] != "ok":
            return {
                "status": "error",
                "url": ASRANK_GRAPHQL_URL,
                "fetched_at": fetched_at,
                "http_status": result.get("http_status"),
                "error": result.get("error"),
                "pages_fetched": len(pages),
            }
        try:
            payload = json.loads(str(result["text"]))
        except json.JSONDecodeError as exc:
            return {"status": "error", "url": ASRANK_GRAPHQL_URL, "fetched_at": fetched_at, "error": f"invalid JSON: {exc}"}
        if payload.get("errors"):
            return {"status": "error", "url": ASRANK_GRAPHQL_URL, "fetched_at": fetched_at, "error": payload["errors"]}
        links = (((payload.get("data") or {}).get("asn") or {}).get("asnLinks") or {})
        pages.append(payload)
        total_count = links.get("totalCount", total_count)
        page_info = links.get("pageInfo") or {}
        if not page_info.get("hasNextPage"):
            break
        offset += ASRANK_PAGE_SIZE

    output_payload = {
        "query_asn": asn,
        "page_size": ASRANK_PAGE_SIZE,
        "page_count": len(pages),
        "total_count": total_count,
        "pages": pages,
    }
    path = append_only_path(links_root / "asrank" / f"{asn}_{month}_{run_id}.json")
    save_text(path, json.dumps(output_payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    return {
        "status": "ok",
        "url": ASRANK_GRAPHQL_URL,
        "fetched_at": fetched_at,
        "raw_response_path": relative_to_root(path),
        "raw_response_sha256": sha256_file(path),
        "page_count": len(pages),
        "total_count": total_count,
    }


def build_online_payload(asn: int, month: str, run_id: str, config: dict[str, Any], links_root: Path) -> dict[str, Any]:
    payload = build_payload(asn, month, run_id, config)
    window_start, window_end = month_window(month)
    current = collect_ripestat_snapshot(asn, month, run_id, "current", window_end, config, links_root)
    previous = collect_ripestat_snapshot(asn, month, run_id, "previous", previous_month_end(month), config, links_root)
    asrank = collect_asrank_links(asn, month, run_id, config, links_root)
    fetch_time = utc_now()
    payload["fetch_time"] = fetch_time
    payload["sources"] = {
        "ripestat": {
            "status": _aggregate_status([current, previous]),
            "fetched_at": fetch_time,
            "snapshots": {
                "current": current,
                "previous": previous,
            },
        },
        "asrank": asrank,
    }
    return payload


def _aggregate_status(sources: list[dict[str, Any]]) -> str:
    statuses = {source.get("status") for source in sources}
    if statuses == {"ok"}:
        return "ok"
    if "ok" in statuses:
        return "partial_error"
    if "not_fetched" in statuses and len(statuses) == 1:
        return "not_fetched"
    return "error"


def _asrank_query(asn: int, first: int, offset: int) -> str:
    return (
        "{ asn(asn: \""
        + str(asn)
        + "\") { asn asnLinks(first: "
        + str(first)
        + ", offset: "
        + str(offset)
        + ") { totalCount pageInfo { first offset hasNextPage } edges { node { relationship asn0 { asn } asn1 { asn } } } } } }"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect links raw evidence manifests.")
    add_common_args(parser)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--online", action="store_true", help="Fetch RIPEstat neighbours and AS Rank relationships.")
    args = parser.parse_args(argv)

    config = load_config(args.config)
    run_id = resolve_run_id(config, args.run_id)
    input_path = resolve_input(config, args.input)
    output_dir = args.output_dir or Path(config["paths"]["raw_root"]) / "links" / "manifest"
    output_dir = output_dir if output_dir.is_absolute() else Path.cwd() / output_dir
    log_dir = Path(config["paths"]["logs_root"])
    log_dir = log_dir if log_dir.is_absolute() else Path.cwd() / log_dir
    ensure_dirs([output_dir, log_dir])
    links_root = output_dir.parent

    log_rows: list[dict[str, Any]] = []
    for item in read_asn_months(input_path):
        asn = item["asn"]
        month = item["month"]
        output_path = append_only_path(output_dir / f"{asn}_{month}_{run_id}.json")
        payload = build_online_payload(asn, month, run_id, config, links_root) if args.online else build_payload(asn, month, run_id, config)
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

    log_path = append_only_path(log_dir / f"collect_links_{run_id}.json")
    write_json(
        log_path,
        {
            "run_id": run_id,
            "fetch_time": utc_now(),
            "input_path": relative_to_root(input_path),
            "records": log_rows,
        },
    )
    print(f"saved {len(log_rows)} links raw manifests; log={relative_to_root(log_path)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

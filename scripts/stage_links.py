#!/usr/bin/env python3
"""Standardize links raw evidence into monthly structural summaries."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from pipeline_utils import (
    add_common_args,
    as_float,
    as_int,
    ensure_dirs,
    load_config,
    month_window,
    parser_version,
    read_asn_months,
    read_json,
    repo_root,
    relative_to_root,
    resolve_input,
    resolve_run_id,
    schema_version,
    sha256_file,
    write_table,
)


def find_manifest(raw_dir: Path, asn: int, month: str, run_id: str) -> Path:
    matches = sorted(raw_dir.glob(f"{asn}_{month}_{run_id}*.json"))
    if matches:
        return matches[-1]
    raise FileNotFoundError(f"missing links raw manifest for AS{asn} {month} in {raw_dir}")


def normalize_record(path: Path, run_id: str, config: dict[str, Any]) -> dict[str, Any]:
    payload = read_json(path)
    asn = int(payload["asn"])
    month = str(payload["analysis_month"])
    derived = derive_link_summary(payload)
    normalized = {**derived, **(payload.get("normalized") or {})}
    window_start = payload.get("window_start")
    window_end = payload.get("window_end")
    if not window_start or not window_end:
        window_start, window_end = month_window(month)

    observed_neighbor_count = as_int(normalized.get("observed_neighbor_count"), 0)
    provider_count = as_int(normalized.get("provider_count"), 0)
    customer_count = as_int(normalized.get("customer_count"), 0)
    peer_count = as_int(normalized.get("peer_count"), 0)
    unknown_count = as_int(normalized.get("unknown_count"), 0)
    new_neighbor_count = as_int(normalized.get("new_neighbor_count"), 0)
    lost_neighbor_count = as_int(normalized.get("lost_neighbor_count"), 0)
    neighbor_churn_rate = as_float(normalized.get("neighbor_churn_rate"), 0.0)
    provider_switch_count = as_int(normalized.get("provider_switch_count"), 0)

    thresholds = config["thresholds"]["topology"]
    link_instability_flag = bool(
        neighbor_churn_rate >= float(thresholds["high_neighbor_churn_rate"])
        or provider_switch_count >= int(thresholds["high_provider_switch_count"])
    )
    border_as_flag = bool(
        observed_neighbor_count > 0
        and provider_count <= int(thresholds["low_neighbor_count_threshold"])
        and peer_count >= provider_count
    )
    topology_anomaly_flag = bool(
        link_instability_flag
        or (
            observed_neighbor_count > 0
            and provider_count == 0
            and customer_count == 0
            and peer_count == 0
            and unknown_count > 0
        )
    )

    evidence_summary = (
        f"neighbors={observed_neighbor_count}; providers={provider_count}; "
        f"peers={peer_count}; churn={neighbor_churn_rate:.2f}; "
        f"provider_switch={provider_switch_count}; border_as={int(border_as_flag)}; "
        f"topology_anomaly={int(topology_anomaly_flag)}"
    )

    return {
        "record_id": f"link_{asn}_{month}",
        "run_id": run_id,
        "schema_version": schema_version(config),
        "parser_version": parser_version(config),
        "asn": asn,
        "analysis_month": month,
        "window_start": window_start,
        "window_end": window_end,
        "observed_neighbor_count": observed_neighbor_count,
        "provider_count": provider_count,
        "customer_count": customer_count,
        "peer_count": peer_count,
        "unknown_count": unknown_count,
        "new_neighbor_count": new_neighbor_count,
        "lost_neighbor_count": lost_neighbor_count,
        "neighbor_churn_rate": neighbor_churn_rate,
        "provider_switch_count": provider_switch_count,
        "link_instability_flag": link_instability_flag,
        "border_as_flag": border_as_flag,
        "topology_anomaly_flag": topology_anomaly_flag,
        "evidence_summary": evidence_summary,
        "raw_evidence_path": relative_to_root(path),
        "raw_evidence_sha256": sha256_file(path),
    }


def derive_link_summary(payload: dict[str, Any]) -> dict[str, Any]:
    asn = int(payload["asn"])
    sources = payload.get("sources") or {}
    ripestat = sources.get("ripestat") or {}
    snapshots = ripestat.get("snapshots") or {}
    current_payload = _read_source_json(snapshots.get("current") or ripestat)
    previous_payload = _read_source_json(snapshots.get("previous") or {})
    asrank_payload = _read_source_json(sources.get("asrank") or {})

    current_neighbors = parse_ripestat_neighbor_set(current_payload) if current_payload else set()
    previous_neighbors = parse_ripestat_neighbor_set(previous_payload) if previous_payload else set()
    relationships = parse_asrank_relationships(asrank_payload, asn) if asrank_payload else _empty_relationships()

    provider_neighbors = relationships["provider"]
    customer_neighbors = relationships["customer"]
    peer_neighbors = relationships["peer"]
    known_relationship_neighbors = provider_neighbors | customer_neighbors | peer_neighbors
    unknown_neighbors = relationships["unknown"] | (current_neighbors - known_relationship_neighbors)
    observed_neighbors = current_neighbors | known_relationship_neighbors | unknown_neighbors

    if current_payload and previous_payload:
        new_neighbors = current_neighbors - previous_neighbors
        lost_neighbors = previous_neighbors - current_neighbors
        denominator = len(current_neighbors | previous_neighbors)
        churn = (len(new_neighbors) + len(lost_neighbors)) / denominator if denominator else 0.0
    else:
        new_neighbors = set()
        lost_neighbors = set()
        churn = 0.0

    return {
        "observed_neighbor_count": len(observed_neighbors),
        "provider_count": len(provider_neighbors),
        "customer_count": len(customer_neighbors),
        "peer_count": len(peer_neighbors),
        "unknown_count": len(unknown_neighbors),
        "new_neighbor_count": len(new_neighbors),
        "lost_neighbor_count": len(lost_neighbors),
        "neighbor_churn_rate": round(churn, 6),
        "provider_switch_count": 0,
    }


def parse_ripestat_neighbor_set(payload: dict[str, Any]) -> set[int]:
    data = payload.get("data") or {}
    neighbors: set[int] = set()
    for item in data.get("neighbours") or []:
        try:
            neighbors.add(int(item["asn"]))
        except (KeyError, TypeError, ValueError):
            continue
    return neighbors


def parse_asrank_relationships(payload: dict[str, Any], target_asn: int) -> dict[str, set[int]]:
    relationships = _empty_relationships()
    for edge in _iter_asrank_edges(payload):
        node = edge.get("node") or {}
        relation = str(node.get("relationship") or "").lower()
        asn0 = _node_asn(node.get("asn0"))
        asn1 = _node_asn(node.get("asn1"))
        other = asn1 if asn0 == target_asn else asn0 if asn1 == target_asn else None
        if other is None:
            continue
        if relation == "peer":
            relationships["peer"].add(other)
        elif relation == "provider":
            if asn0 == target_asn:
                relationships["provider"].add(other)
            else:
                relationships["customer"].add(other)
        elif relation == "customer":
            if asn0 == target_asn:
                relationships["customer"].add(other)
            else:
                relationships["provider"].add(other)
        else:
            relationships["unknown"].add(other)
    return relationships


def _iter_asrank_edges(payload: dict[str, Any]) -> list[dict[str, Any]]:
    pages = payload.get("pages")
    if isinstance(pages, list):
        edges: list[dict[str, Any]] = []
        for page in pages:
            edges.extend(_iter_asrank_edges(page))
        return edges
    links = (((payload.get("data") or {}).get("asn") or {}).get("asnLinks") or {})
    return [edge for edge in links.get("edges") or [] if isinstance(edge, dict)]


def _node_asn(node: Any) -> int | None:
    if not isinstance(node, dict):
        return None
    try:
        return int(node.get("asn"))
    except (TypeError, ValueError):
        return None


def _empty_relationships() -> dict[str, set[int]]:
    return {"provider": set(), "customer": set(), "peer": set(), "unknown": set()}


def _read_source_json(source: dict[str, Any]) -> dict[str, Any] | None:
    raw_path = source.get("raw_response_path")
    if not raw_path:
        return None
    path = Path(str(raw_path))
    if not path.is_absolute():
        path = repo_root() / path
    if not path.exists():
        return None
    return read_json(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build links staging output.")
    add_common_args(parser)
    parser.add_argument("--raw-dir", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args(argv)

    config = load_config(args.config)
    run_id = resolve_run_id(config, args.run_id)
    input_path = resolve_input(config, args.input)
    raw_dir = args.raw_dir or Path(config["paths"]["raw_root"]) / "links" / "manifest"
    output_dir = args.output_dir or Path(config["paths"]["staging_root"]) / "links"
    raw_dir = raw_dir if raw_dir.is_absolute() else Path.cwd() / raw_dir
    output_dir = output_dir if output_dir.is_absolute() else Path.cwd() / output_dir
    ensure_dirs([output_dir])

    rows = [
        normalize_record(find_manifest(raw_dir, item["asn"], item["month"], run_id), run_id, config)
        for item in read_asn_months(input_path)
    ]
    write_table(
        rows,
        output_dir / "asn_link_summary_monthly.csv",
        output_dir / "asn_link_summary_monthly.parquet",
    )
    print(f"saved {len(rows)} links staging rows to {relative_to_root(output_dir)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

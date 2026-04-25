import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from collect_prefixes import parse_mrt_line
from pipeline_utils import DEFAULT_CONFIG, write_json
from collect_registry import extract_rdap_fields, parse_delegated_records
from stage_prefixes import normalize_record as normalize_prefixes
from stage_links import (
    normalize_record as normalize_links,
    parse_asrank_relationships,
    parse_ripestat_neighbor_set,
)
from stage_registry import normalize_record as normalize_registry


def test_delegated_parser_matches_asn_range() -> None:
    text = "\n".join(
        [
            "2|ripencc|20260423|0|0|20260423|0",
            "ripencc|DE|asn|3320|4|19930901|allocated",
        ]
    )

    records, snapshot_time = parse_delegated_records(text, "ripencc")

    assert snapshot_time == "2026-04-23T00:00:00Z"
    assert records[0].start_asn == 3320
    assert records[0].end_asn == 3323
    assert records[0].country == "DE"


def test_rdap_response_parser_extracts_registry_fields() -> None:
    fields = extract_rdap_fields(
        {
            "handle": "AS64500",
            "name": "Example Transit",
            "country": "US",
            "entities": [
                {
                    "roles": ["registrant"],
                    "vcardArray": [
                        "vcard",
                        [
                            ["version", {}, "text", "4.0"],
                            ["fn", {}, "text", "Example Global Group"],
                            ["adr", {}, "text", ["", "", "", "", "", "", "US"]],
                        ],
                    ],
                }
            ],
        }
    )

    assert fields["registered_country"] == "US"
    assert fields["org_name"] == "Example Transit"
    assert fields["parent_org"] == "Example Global Group"


def test_registry_normalization_flags_admin_conflict(tmp_path: Path) -> None:
    raw_path = tmp_path / "registry.json"
    write_json(
        raw_path,
        {
            "asn": 64500,
            "analysis_month": "2026-03",
            "fetch_time": "2026-04-23T00:00:00Z",
            "normalized": {
                "allocated_country": "US",
                "registered_country": "DE",
                "org_name": "Example Global Hosting",
            },
        },
    )

    row = normalize_registry(raw_path, "test_run", DEFAULT_CONFIG)

    assert row["allocated_country"] == "US"
    assert row["registered_country"] == "DE"
    assert row["admin_conflict_flag"] is True
    assert row["multi_country_registry_flag"] is True
    assert row["hosting_or_lease_hint_flag"] is True
    assert row["raw_evidence_sha256"]


def test_registry_normalization_flags_source_country_conflict(tmp_path: Path) -> None:
    raw_path = tmp_path / "registry.json"
    write_json(
        raw_path,
        {
            "asn": 64500,
            "analysis_month": "2026-03",
            "fetch_time": "2026-04-23T00:00:00Z",
            "sources": {
                "delegated": {"status": "ok", "country": "US", "allocation_status": "allocated"},
                "rdap": {"status": "ok", "country": "DE", "org_name": "Example Telecom"},
            },
        },
    )

    row = normalize_registry(raw_path, "test_run", DEFAULT_CONFIG)

    assert row["allocated_country"] == "US"
    assert row["registered_country"] == "DE"
    assert row["admin_conflict_flag"] is True
    assert row["multi_country_registry_flag"] is True


def test_registry_normalization_handles_failed_sources(tmp_path: Path) -> None:
    raw_path = tmp_path / "registry.json"
    write_json(
        raw_path,
        {
            "asn": 64500,
            "analysis_month": "2026-03",
            "fetch_time": "2026-04-23T00:00:00Z",
            "sources": {
                "delegated": {"status": "error", "error": "timeout"},
                "rdap": {"status": "error", "error": "http 500"},
            },
        },
    )

    row = normalize_registry(raw_path, "test_run", DEFAULT_CONFIG)

    assert row["allocated_country"] is None
    assert row["registered_country"] is None
    assert row["admin_conflict_flag"] is False
    assert row["multi_country_registry_flag"] is False


def test_ripestat_neighbor_parser_deduplicates_neighbors() -> None:
    neighbors = parse_ripestat_neighbor_set(
        {
            "data": {
                "neighbours": [
                    {"asn": 64501, "type": "left"},
                    {"asn": "64501", "type": "right"},
                    {"asn": 64502, "type": "uncertain"},
                ]
            }
        }
    )

    assert neighbors == {64501, 64502}


def test_asrank_relationship_parser_counts_from_target_perspective() -> None:
    relationships = parse_asrank_relationships(
        {
            "pages": [
                {
                    "data": {
                        "asn": {
                            "asnLinks": {
                                "edges": [
                                    {
                                        "node": {
                                            "relationship": "provider",
                                            "asn0": {"asn": "64500"},
                                            "asn1": {"asn": "64501"},
                                        }
                                    },
                                    {
                                        "node": {
                                            "relationship": "customer",
                                            "asn0": {"asn": "64500"},
                                            "asn1": {"asn": "64502"},
                                        }
                                    },
                                    {
                                        "node": {
                                            "relationship": "peer",
                                            "asn0": {"asn": "64500"},
                                            "asn1": {"asn": "64503"},
                                        }
                                    },
                                ]
                            }
                        }
                    }
                }
            ]
        },
        64500,
    )

    assert relationships["provider"] == {64501}
    assert relationships["customer"] == {64502}
    assert relationships["peer"] == {64503}


def test_links_normalization_from_online_raw_sources(tmp_path: Path) -> None:
    current_path = tmp_path / "ripestat_current.json"
    previous_path = tmp_path / "ripestat_previous.json"
    asrank_path = tmp_path / "asrank.json"
    raw_path = tmp_path / "links.json"
    write_json(
        current_path,
        {"data": {"neighbours": [{"asn": 64501}, {"asn": 64502}, {"asn": 64503}, {"asn": 64504}]}},
    )
    write_json(previous_path, {"data": {"neighbours": [{"asn": 64501}, {"asn": 64505}]}})
    write_json(
        asrank_path,
        {
            "pages": [
                {
                    "data": {
                        "asn": {
                            "asnLinks": {
                                "edges": [
                                    {"node": {"relationship": "provider", "asn0": {"asn": "64500"}, "asn1": {"asn": "64501"}}},
                                    {"node": {"relationship": "customer", "asn0": {"asn": "64500"}, "asn1": {"asn": "64502"}}},
                                    {"node": {"relationship": "peer", "asn0": {"asn": "64500"}, "asn1": {"asn": "64503"}}},
                                ]
                            }
                        }
                    }
                }
            ]
        },
    )
    write_json(
        raw_path,
        {
            "asn": 64500,
            "analysis_month": "2026-03",
            "window_start": "2026-03-01T00:00:00Z",
            "window_end": "2026-03-31T23:59:59Z",
            "sources": {
                "ripestat": {
                    "status": "ok",
                    "snapshots": {
                        "current": {"status": "ok", "raw_response_path": str(current_path)},
                        "previous": {"status": "ok", "raw_response_path": str(previous_path)},
                    },
                },
                "asrank": {"status": "ok", "raw_response_path": str(asrank_path)},
            },
        },
    )

    row = normalize_links(raw_path, "test_run", DEFAULT_CONFIG)

    assert row["observed_neighbor_count"] == 4
    assert row["provider_count"] == 1
    assert row["customer_count"] == 1
    assert row["peer_count"] == 1
    assert row["unknown_count"] == 1
    assert row["new_neighbor_count"] == 3
    assert row["lost_neighbor_count"] == 1
    assert row["neighbor_churn_rate"] == 0.8


def test_links_normalization_handles_failed_sources(tmp_path: Path) -> None:
    raw_path = tmp_path / "links.json"
    write_json(
        raw_path,
        {
            "asn": 64500,
            "analysis_month": "2026-03",
            "sources": {
                "ripestat": {"status": "error", "error": "timeout"},
                "asrank": {"status": "error", "error": "http 500"},
            },
        },
    )

    row = normalize_links(raw_path, "test_run", DEFAULT_CONFIG)

    assert row["observed_neighbor_count"] == 0
    assert row["provider_count"] == 0
    assert row["customer_count"] == 0
    assert row["peer_count"] == 0
    assert row["topology_anomaly_flag"] is False


def test_links_normalization_flags_topology_anomaly(tmp_path: Path) -> None:
    raw_path = tmp_path / "links.json"
    raw_path.write_text(
        json.dumps(
            {
                "asn": 64500,
                "analysis_month": "2026-03",
                "window_start": "2026-03-01T00:00:00Z",
                "window_end": "2026-03-31T23:59:59Z",
                "normalized": {
                    "observed_neighbor_count": 8,
                    "provider_count": 1,
                    "customer_count": 0,
                    "peer_count": 4,
                    "unknown_count": 3,
                    "neighbor_churn_rate": 0.75,
                    "provider_switch_count": 2,
                },
            }
        ),
        encoding="utf-8",
    )

    row = normalize_links(raw_path, "test_run", DEFAULT_CONFIG)

    assert row["link_instability_flag"] is True
    assert row["topology_anomaly_flag"] is True
    assert row["border_as_flag"] is True
    assert row["neighbor_churn_rate"] == 0.75


def test_parse_mrt_line_extracts_origin_prefix() -> None:
    parsed = parse_mrt_line(
        "TABLE_DUMP2|1774972800|B|192.0.2.1|64512|203.0.113.0/24|64500 64496|IGP|192.0.2.1|0|0||NAG||"
    )

    assert parsed == (64496, "203.0.113.0/24")


def test_parse_mrt_line_rejects_as_set_origin() -> None:
    parsed = parse_mrt_line(
        "TABLE_DUMP2|1774972800|B|192.0.2.1|64512|2001:db8::/32|64500 {64496,64497}|IGP|192.0.2.1|0|0||NAG||"
    )

    assert parsed is None


def test_prefix_normalization_counts_prefixes(tmp_path: Path) -> None:
    raw_path = tmp_path / "prefixes.json"
    write_json(
        raw_path,
        {
            "asn": 49666,
            "analysis_month": "2026-03",
            "filter_country": "IR",
            "as_name": "TIC-GW-AS",
            "as_country": "IR",
            "global_rank": 132,
            "source_collector": "rrc25",
            "source_snapshot_time": "2026-03-31T16:00:00Z",
            "fetch_time": "2026-04-23T00:00:00Z",
            "normalized": {
                "prefixes_v4": ["5.112.0.0/13", "37.32.0.0/12"],
                "prefixes_v6": ["2001:db8::/32"],
                "prefix_count_v4": 2,
                "prefix_count_v6": 1,
                "total_prefix_count": 3,
            },
        },
    )

    row = normalize_prefixes(raw_path, "test_run", DEFAULT_CONFIG)

    assert row["prefix_count_v4"] == 2
    assert row["prefix_count_v6"] == 1
    assert row["total_prefix_count"] == 3
    assert '"5.112.0.0/13"' in row["prefixes_v4_json"]
    assert row["raw_evidence_sha256"]

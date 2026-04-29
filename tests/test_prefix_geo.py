import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from pipeline_utils import DEFAULT_CONFIG, write_json
from stage_prefix_geo import (
    DelegatedIndex,
    build_geo_row,
    choose_dominant_country,
    classify_prefixes,
    parse_delegated_line,
)


def test_delegated_parser_handles_ipv4_and_ipv6() -> None:
    ipv4 = parse_delegated_line("ripencc|IR|ipv4|5.112.0.0|1048576|20120601|allocated")
    ipv6 = parse_delegated_line("ripencc|IR|ipv6|2001:db8::|32|20120601|allocated")

    assert ipv4 is not None
    assert ipv4.family == 4
    assert ipv4.country == "IR"
    assert ipv4.start < ipv4.end
    assert ipv6 is not None
    assert ipv6.family == 6
    assert ipv6.country == "IR"


def test_longest_covering_delegated_block_wins() -> None:
    broad = parse_delegated_line("ripencc|IR|ipv4|203.0.112.0|4096|20120601|allocated")
    specific = parse_delegated_line("arin|US|ipv4|203.0.113.0|256|20120601|allocated")
    assert broad is not None
    assert specific is not None

    index = DelegatedIndex([broad, specific])

    assert index.lookup("203.0.113.0/24").country == "US"
    assert index.lookup("203.0.112.0/24").country == "IR"


def test_prefix_geo_stats_and_unmapped_country() -> None:
    block_ir = parse_delegated_line("ripencc|IR|ipv4|5.112.0.0|1048576|20120601|allocated")
    block_us = parse_delegated_line("arin|US|ipv4|203.0.113.0|256|20120601|allocated")
    assert block_ir is not None
    assert block_us is not None

    counts, mapped_count, unmapped_count = classify_prefixes(
        ["5.112.0.0/13", "203.0.113.0/24", "198.51.100.0/24"],
        DelegatedIndex([block_ir, block_us]),
    )

    assert counts == {"IR": 1, "US": 1, "ZZ": 1}
    assert mapped_count == 2
    assert unmapped_count == 1


def test_geo_conflict_threshold_and_dominant_country(tmp_path: Path) -> None:
    delegated_file = tmp_path / "delegated.txt"
    delegated_file.write_text(
        "\n".join(
            [
                "ripencc|IR|ipv4|5.112.0.0|1048576|20120601|allocated",
                "arin|US|ipv4|203.0.113.0|512|20120601|allocated",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    raw_path = tmp_path / "prefix_raw.json"
    write_json(raw_path, {"ok": True})
    row = {
        "asn": 64500,
        "analysis_month": "2026-03",
        "filter_country": "IR",
        "as_country": "IR",
        "prefixes_v4_json": json.dumps(["203.0.113.0/24", "203.0.114.0/24", "5.112.0.0/13"]),
        "prefixes_v6_json": "[]",
        "raw_evidence_path": str(raw_path),
        "raw_evidence_sha256": "test-sha",
    }
    blocks = [
        block
        for block in (
            parse_delegated_line("ripencc|IR|ipv4|5.112.0.0|1048576|20120601|allocated"),
            parse_delegated_line("arin|US|ipv4|203.0.113.0|512|20120601|allocated"),
        )
        if block is not None
    ]

    output = build_geo_row(
        row,
        DelegatedIndex(blocks),
        run_id="test_run",
        config=DEFAULT_CONFIG,
        delegated_file=delegated_file,
        delegated_sha256="geo-sha",
        foreign_ratio_threshold=0.5,
    )

    assert output["dominant_prefix_country"] == "US"
    assert output["dominant_prefix_country_ratio"] == 0.666667
    assert output["foreign_prefix_count"] == 2
    assert output["foreign_prefix_coverage_ratio"] == 0.666667
    assert output["geo_conflict_flag"] is True


def test_unmapped_prefixes_do_not_trigger_geo_conflict(tmp_path: Path) -> None:
    delegated_file = tmp_path / "delegated.txt"
    delegated_file.write_text("ripencc|IR|ipv4|5.112.0.0|1048576|20120601|allocated\n", encoding="utf-8")
    row = {
        "asn": 64500,
        "analysis_month": "2026-03",
        "filter_country": "IR",
        "as_country": "IR",
        "prefixes_v4_json": json.dumps(["198.51.100.0/24", "203.0.113.0/24"]),
        "prefixes_v6_json": "[]",
        "raw_evidence_path": "raw.json",
        "raw_evidence_sha256": "test-sha",
    }
    block = parse_delegated_line("ripencc|IR|ipv4|5.112.0.0|1048576|20120601|allocated")
    assert block is not None

    output = build_geo_row(
        row,
        DelegatedIndex([block]),
        run_id="test_run",
        config=DEFAULT_CONFIG,
        delegated_file=delegated_file,
        delegated_sha256="geo-sha",
        foreign_ratio_threshold=0.5,
    )

    assert output["dominant_prefix_country"] == "ZZ"
    assert output["foreign_prefix_coverage_ratio"] == 0.0
    assert output["geo_conflict_flag"] is False


def test_empty_prefix_profile_uses_unknown_country() -> None:
    assert choose_dominant_country({}) == ("ZZ", 0)

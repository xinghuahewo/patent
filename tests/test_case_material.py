from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from build_case_material import build_case_rows, render_case_card


def _stage1(asn: int, geo_conflict: bool = True, registered_country: str = "") -> dict[str, object]:
    return {
        "asn": asn,
        "month": "2026-03",
        "allocated_country": "IR",
        "registered_country": registered_country,
        "dominant_prefix_country": "DE",
        "geo_conflict_flag": "true" if geo_conflict else "false",
        "border_as_flag": "false",
        "raw_evidence_path": f"data/curated/stage1/manifest/{asn}.json",
        "raw_evidence_sha256": f"stage1-sha-{asn}",
    }


def _prefix_geo(
    asn: int,
    *,
    prefix_count: int = 20,
    mapped: int = 20,
    unmapped: int = 0,
    foreign_ratio: float = 0.8,
    dominant: str = "DE",
) -> dict[str, object]:
    return {
        "asn": asn,
        "analysis_month": "2026-03",
        "baseline_country": "IR",
        "prefix_count": prefix_count,
        "mapped_prefix_count": mapped,
        "unmapped_prefix_count": unmapped,
        "dominant_prefix_country": dominant,
        "dominant_prefix_country_ratio": 0.8,
        "foreign_prefix_count": int(prefix_count * foreign_ratio),
        "foreign_prefix_coverage_ratio": foreign_ratio,
        "geo_conflict_flag": "true",
        "raw_evidence_path": f"data/raw/prefixes/{asn}.json",
        "raw_evidence_sha256": f"prefix-sha-{asn}",
        "geo_evidence_path": "data/raw/registry/delegated_monthly_go/nro.txt",
        "geo_evidence_sha256": "geo-sha",
    }


def _registry(asn: int, registered_country: str = "") -> dict[str, object]:
    return {
        "asn": asn,
        "analysis_month": "2026-03",
        "allocated_country": "IR",
        "registered_country": registered_country,
        "cloud_or_cdn_flag": "false",
        "crossborder_group_flag": "false",
        "hosting_or_lease_hint_flag": "false",
        "raw_evidence_path": f"data/raw/registry/{asn}.json",
        "raw_evidence_sha256": f"registry-sha-{asn}",
    }


def _inventory(asn: int, prefix_count: int = 20) -> dict[str, object]:
    return {
        "asn": asn,
        "analysis_month": "2026-03",
        "as_name": f"AS{asn}",
        "total_prefix_count": prefix_count,
        "raw_evidence_path": f"data/raw/prefixes/inventory-{asn}.json",
        "raw_evidence_sha256": f"inventory-sha-{asn}",
    }


def test_case_material_filters_only_geo_conflict_candidates() -> None:
    rows = build_case_rows(
        stage1_rows=[_stage1(64500, True), _stage1(64501, False)],
        prefix_geo_rows=[_prefix_geo(64500), _prefix_geo(64501)],
        registry_rows=[_registry(64500), _registry(64501)],
        prefix_inventory_rows=[_inventory(64500), _inventory(64501)],
        country="IR",
        month="2026-03",
    )

    assert [row["asn"] for row in rows] == [64500]
    assert rows[0]["trigger_reason"].startswith("prefix_geo_conflict")


def test_missing_registered_country_does_not_create_final_verdict() -> None:
    rows = build_case_rows(
        stage1_rows=[_stage1(64500, True, registered_country="")],
        prefix_geo_rows=[_prefix_geo(64500)],
        registry_rows=[_registry(64500, registered_country="")],
        prefix_inventory_rows=[_inventory(64500)],
        country="IR",
        month="2026-03",
    )

    row = rows[0]
    assert row["registered_country"] == ""
    assert "registered_country_missing" in row["weakness_flags"]
    assert "final_operating_country" not in row
    assert "anomaly_verdict" not in row


def test_zz_or_high_unmapped_ratio_lowers_review_priority() -> None:
    rows = build_case_rows(
        stage1_rows=[_stage1(64500, True)],
        prefix_geo_rows=[
            _prefix_geo(
                64500,
                prefix_count=12,
                mapped=3,
                unmapped=9,
                foreign_ratio=0.75,
                dominant="ZZ",
            )
        ],
        registry_rows=[_registry(64500)],
        prefix_inventory_rows=[_inventory(64500, 12)],
        country="IR",
        month="2026-03",
    )

    assert rows[0]["review_priority"] == "low_review"
    assert "dominant_country_unmapped" in rows[0]["weakness_flags"]
    assert "high_unmapped_ratio" in rows[0]["weakness_flags"]


def test_case_card_contains_limits_and_raw_evidence_references() -> None:
    row = build_case_rows(
        stage1_rows=[_stage1(64500, True)],
        prefix_geo_rows=[_prefix_geo(64500)],
        registry_rows=[_registry(64500)],
        prefix_inventory_rows=[_inventory(64500)],
        country="IR",
        month="2026-03",
    )[0]

    card = render_case_card(row)

    assert "## 不能说明什么" in card
    assert "## 原始证据引用" in card
    assert "data/curated/stage1/manifest/64500.json" in card
    assert "data/raw/prefixes/64500.json" in card

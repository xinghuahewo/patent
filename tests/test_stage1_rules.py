from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from build_stage1_suspects import build_rows, choose_level
from pipeline_utils import DEFAULT_CONFIG


def test_stage1_level_rules() -> None:
    assert choose_level(admin_conflict=True, geo_conflict=False, topology_anomaly=True) == "high"
    assert choose_level(admin_conflict=True, geo_conflict=False, topology_anomaly=False) == "medium"
    assert choose_level(admin_conflict=False, geo_conflict=False, topology_anomaly=True) == "medium"
    assert choose_level(admin_conflict=False, geo_conflict=False, topology_anomaly=False) == "low"


def test_geo_conflict_can_participate_without_being_required() -> None:
    assert choose_level(admin_conflict=False, geo_conflict=True, topology_anomaly=True) == "medium"
    assert choose_level(admin_conflict=False, geo_conflict=True, topology_anomaly=False) == "low"


def test_stage1_consumes_prefix_geo_signal(tmp_path: Path) -> None:
    rows = build_rows(
        registry_rows=[],
        links_rows=[],
        prefix_geo_rows=[
            {
                "record_id": "prefix_geo_64500_2026-03",
                "asn": 64500,
                "analysis_month": "2026-03",
                "dominant_prefix_country": "US",
                "geo_conflict_flag": "true",
                "raw_evidence_path": "data/raw/prefixes/example.json",
                "raw_evidence_sha256": "prefix-sha",
                "geo_evidence_path": "data/raw/registry/delegated.txt",
                "geo_evidence_sha256": "geo-sha",
            }
        ],
        run_id="test_run",
        config=DEFAULT_CONFIG,
        output_dir=tmp_path,
    )

    assert len(rows) == 1
    assert rows[0]["asn"] == 64500
    assert rows[0]["dominant_prefix_country"] == "US"
    assert rows[0]["geo_conflict_flag"] is True
    assert "prefix_geo" in Path(rows[0]["raw_evidence_path"]).read_text(encoding="utf-8")

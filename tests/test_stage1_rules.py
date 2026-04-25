from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from build_stage1_suspects import choose_level


def test_stage1_level_rules() -> None:
    assert choose_level(admin_conflict=True, geo_conflict=False, topology_anomaly=True) == "high"
    assert choose_level(admin_conflict=True, geo_conflict=False, topology_anomaly=False) == "medium"
    assert choose_level(admin_conflict=False, geo_conflict=False, topology_anomaly=True) == "medium"
    assert choose_level(admin_conflict=False, geo_conflict=False, topology_anomaly=False) == "low"


def test_geo_conflict_can_participate_without_being_required() -> None:
    assert choose_level(admin_conflict=False, geo_conflict=True, topology_anomaly=True) == "medium"
    assert choose_level(admin_conflict=False, geo_conflict=True, topology_anomaly=False) == "low"

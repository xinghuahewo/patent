from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from analyze_asn_region_changes import (  # noqa: E402
    AsnState,
    append_state_to_segments,
    classify_trajectory,
    country_region,
    event_rows,
    month_range,
    parse_delegated_asn_states,
    states_to_segments,
)
from pipeline_utils import DEFAULT_CONFIG  # noqa: E402


def _state(asn: int, month: str, rir: str, country: str, status: str = "allocated") -> AsnState:
    return AsnState(
        asn=asn,
        month=month,
        rir=rir,
        country=country,
        region=country_region(country),
        status=status,
        allocation_date="20200101",
        raw_evidence_path=f"raw/{month}.txt",
        raw_evidence_sha256=f"sha-{month}",
        raw_line=f"{rir}|{country}|asn|{asn}|1|20200101|{status}",
    )


def test_month_range_is_contiguous() -> None:
    assert month_range("2021-11", "2022-02") == ["2021-11", "2021-12", "2022-01", "2022-02"]


def test_delegated_parser_expands_asn_range_and_skips_iana(tmp_path: Path) -> None:
    raw_path = tmp_path / "nro_delegated_stats_2026-03_20260331.txt"
    raw_path.write_text(
        "\n".join(
            [
                "2|nro|20260331|0|0|20260331|+0000",
                "iana|ZZ|asn|404381|4199595619|20061129|available|iana|iana",
                "ripencc|NL|asn|64500|3|20200101|allocated",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    rows = list(parse_delegated_asn_states(raw_path, "2026-03", "abc123"))

    assert [row.asn for row in rows] == [64500, 64501, 64502]
    assert all(row.rir == "ripencc" for row in rows)
    assert rows[0].region == "europe"


def test_stable_asn_classifies_stable() -> None:
    months = month_range("2026-01", "2026-03")
    month_index = {month: idx for idx, month in enumerate(months)}
    segments = states_to_segments(
        64500,
        [_state(64500, "2026-01", "arin", "US"), _state(64500, "2026-02", "arin", "US"), _state(64500, "2026-03", "arin", "US")],
        month_index,
    )

    assert len(segments) == 1
    assert classify_trajectory(segments, months) == "stable"


def test_country_move_and_rir_move_are_classified() -> None:
    months = month_range("2026-01", "2026-03")
    month_index = {month: idx for idx, month in enumerate(months)}
    country_segments = states_to_segments(
        64500,
        [_state(64500, "2026-01", "arin", "US"), _state(64500, "2026-02", "arin", "CA"), _state(64500, "2026-03", "arin", "CA")],
        month_index,
    )
    rir_segments = states_to_segments(
        64501,
        [_state(64501, "2026-01", "arin", "US"), _state(64501, "2026-02", "ripencc", "NL")],
        month_index,
    )

    assert classify_trajectory(country_segments, months) == "single_country_move"
    assert classify_trajectory(rir_segments, months) == "cross_rir_move"


def test_temporary_revert_and_gap_are_classified() -> None:
    months = month_range("2026-01", "2026-04")
    month_index = {month: idx for idx, month in enumerate(months)}
    revert_segments = states_to_segments(
        64500,
        [
            _state(64500, "2026-01", "arin", "US"),
            _state(64500, "2026-02", "ripencc", "NL"),
            _state(64500, "2026-03", "arin", "US"),
            _state(64500, "2026-04", "arin", "US"),
        ],
        month_index,
    )
    gap_segments = states_to_segments(
        64501,
        [_state(64501, "2026-01", "arin", "US"), _state(64501, "2026-03", "arin", "US")],
        month_index,
    )

    assert classify_trajectory(revert_segments, months) == "temporary_revert"
    assert classify_trajectory(gap_segments, months) == "data_gap"
    assert any(segment.status == "gap" for segment in gap_segments)


def test_streaming_segment_builder_matches_batch_builder() -> None:
    months = month_range("2026-01", "2026-03")
    states = [_state(64500, "2026-01", "arin", "US"), _state(64500, "2026-03", "ripencc", "NL")]
    month_index = {month: idx for idx, month in enumerate(months)}
    batch_segments = states_to_segments(64500, states, month_index)
    streamed: dict[int, list] = {}
    for state in states:
        append_state_to_segments(streamed, state, month_index[state.month])

    assert [(seg.rir, seg.country, seg.status) for seg in streamed[64500]] == [
        (seg.rir, seg.country, seg.status) for seg in batch_segments
    ]


def test_event_rows_include_change_type_and_gap_boundaries() -> None:
    months = month_range("2026-01", "2026-03")
    month_index = {month: idx for idx, month in enumerate(months)}
    segments = states_to_segments(
        64500,
        [_state(64500, "2026-01", "arin", "US"), _state(64500, "2026-03", "ripencc", "NL")],
        month_index,
    )

    rows = event_rows(64500, segments, months, "test_run", DEFAULT_CONFIG)

    assert [row["change_type"] for row in rows] == ["gap_start", "gap_end"]

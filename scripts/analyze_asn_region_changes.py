#!/usr/bin/env python3
"""Analyze five-year ASN registry region changes from local NRO delegated files."""

from __future__ import annotations

import argparse
import calendar
import csv
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator

from pipeline_utils import (
    ensure_dirs,
    load_config,
    parser_version,
    relative_to_root,
    schema_version,
    sha256_file,
    utc_now,
)


EXPECTED_RIRS = {"afrinic", "apnic", "arin", "lacnic", "ripencc"}
RAW_PATTERN = "nro_delegated_stats_*.txt"
DEFAULT_START_MONTH = "2021-04"
DEFAULT_END_MONTH = "2026-03"

MONTHLY_COLUMNS = [
    "record_id",
    "run_id",
    "schema_version",
    "parser_version",
    "asn",
    "analysis_month",
    "rir",
    "country",
    "region",
    "status",
    "allocation_date",
    "raw_evidence_path",
    "raw_evidence_sha256",
    "raw_line",
]

SEGMENT_COLUMNS = [
    "record_id",
    "run_id",
    "schema_version",
    "parser_version",
    "asn",
    "segment_index",
    "start_month",
    "end_month",
    "duration_months",
    "rir",
    "country",
    "region",
    "status",
    "start_raw_evidence_path",
    "start_raw_evidence_sha256",
    "end_raw_evidence_path",
    "end_raw_evidence_sha256",
]

TRAJECTORY_COLUMNS = [
    "record_id",
    "run_id",
    "schema_version",
    "parser_version",
    "asn",
    "first_seen_month",
    "last_seen_month",
    "observed_months",
    "missing_months",
    "segment_count",
    "rir_sequence",
    "country_sequence",
    "region_sequence",
    "status_sequence",
    "changed_rir_count",
    "changed_country_count",
    "changed_region_count",
    "max_stable_months",
    "trajectory_type",
    "first_raw_evidence_path",
    "first_raw_evidence_sha256",
    "last_raw_evidence_path",
    "last_raw_evidence_sha256",
]

EVENT_COLUMNS = [
    "record_id",
    "run_id",
    "schema_version",
    "parser_version",
    "asn",
    "from_month",
    "to_month",
    "from_rir",
    "to_rir",
    "from_country",
    "to_country",
    "from_region",
    "to_region",
    "from_status",
    "to_status",
    "change_type",
    "from_duration_months",
    "to_duration_months",
    "from_raw_evidence_path",
    "from_raw_evidence_sha256",
    "to_raw_evidence_path",
    "to_raw_evidence_sha256",
]

TRAJECTORY_TYPES = {
    "stable",
    "single_country_move",
    "multi_country_move",
    "cross_region_move",
    "cross_rir_move",
    "oscillation",
    "temporary_revert",
    "appeared_late",
    "disappeared_early",
    "data_gap",
}

COUNTRY_REGION: dict[str, str] = {}
for _country in """
DZ AO BJ BW BF BI CV CM CF TD KM CG CD CI DJ EG GQ ER SZ ET GA GM GH GN GW KE LS LR LY MG MW ML MR MU MA MZ
NA NE NG RW ST SN SC SL SO ZA SS SD TZ TG TN UG ZM ZW
""".split():
    COUNTRY_REGION[_country] = "africa"
for _country in """
AI AG AR AW BS BB BZ BM BO BR VG CA KY CL CO CR CU CW DM DO EC SV FK GF GL GD GP GT GY HT HN JM MQ MX MS
NI PA PY PE PR BL KN LC MF PM VC SX SR TT TC US UY VE VI
""".split():
    COUNTRY_REGION[_country] = "americas"
for _country in """
AL AD AM AT AZ BY BE BA BG HR CY CZ DK EE FO FI FR GE DE GI GR GG HU IS IE IM IT JE KZ XK LV LI LT LU MT
MD MC ME NL MK NO PL PT RO RU SM RS SK SI ES SE CH TR UA GB VA EU
""".split():
    COUNTRY_REGION[_country] = "europe"
for _country in """
AF BH BD BT BN KH CN HK IN ID IR IQ IL JP JO KP KR KW KG LA LB MO MY MV MN MM NP OM PK PS PH QA SA SG LK
SY TW TJ TH TL TM AE UZ VN YE
""".split():
    COUNTRY_REGION[_country] = "asia"
for _country in """
AS AU CK FJ PF GU KI MH FM NR NC NZ NU NF MP PW PG PN WS SB TK TO TV VU WF
""".split():
    COUNTRY_REGION[_country] = "oceania"


@dataclass(frozen=True)
class AsnState:
    asn: int
    month: str
    rir: str
    country: str
    region: str
    status: str
    allocation_date: str
    raw_evidence_path: str
    raw_evidence_sha256: str
    raw_line: str

    @property
    def key(self) -> tuple[str, str, str, str]:
        return (self.rir, self.country, self.region, self.status)


@dataclass
class Segment:
    asn: int
    start_idx: int
    end_idx: int
    rir: str
    country: str
    region: str
    status: str
    start_raw_evidence_path: str
    start_raw_evidence_sha256: str
    end_raw_evidence_path: str
    end_raw_evidence_sha256: str

    @property
    def is_gap(self) -> bool:
        return self.status == "gap"

    @property
    def key(self) -> tuple[str, str, str, str]:
        return (self.rir, self.country, self.region, self.status)


class TableSink:
    """Write a CSV table and an optional chunked Parquet table."""

    def __init__(self, csv_path: Path, parquet_path: Path, columns: list[str], chunk_size: int = 100_000) -> None:
        self.csv_path = csv_path
        self.parquet_path = parquet_path
        self.columns = columns
        self.chunk_size = chunk_size
        self._csv_file: Any = None
        self._csv_writer: csv.DictWriter[str] | None = None
        self._buffer: list[dict[str, Any]] = []
        self._parquet_writer: Any = None
        self._pa: Any = None

    def __enter__(self) -> "TableSink":
        self.csv_path.parent.mkdir(parents=True, exist_ok=True)
        self._csv_file = self.csv_path.open("w", newline="", encoding="utf-8")
        self._csv_writer = csv.DictWriter(self._csv_file, fieldnames=self.columns)
        self._csv_writer.writeheader()
        try:
            import pyarrow as pa  # type: ignore
            import pyarrow.parquet as pq  # type: ignore

            self._pa = pa
            self._pq = pq
            self.parquet_path.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            self._pa = None
        return self

    def write(self, row: dict[str, Any]) -> None:
        if self._csv_writer is None:
            raise RuntimeError("TableSink is not open")
        clean = {column: _csv_value(row.get(column, "")) for column in self.columns}
        self._csv_writer.writerow(clean)
        if self._pa is not None:
            self._buffer.append(clean)
            if len(self._buffer) >= self.chunk_size:
                self.flush_parquet()

    def write_many(self, rows: Iterable[dict[str, Any]]) -> None:
        for row in rows:
            self.write(row)

    def flush_parquet(self) -> None:
        if self._pa is None or not self._buffer:
            return
        table = self._pa.Table.from_pylist(self._buffer)
        if self._parquet_writer is None:
            self._parquet_writer = self._pq.ParquetWriter(self.parquet_path, table.schema)
        self._parquet_writer.write_table(table)
        self._buffer.clear()

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if exc_type is None:
            self.flush_parquet()
        if self._parquet_writer is not None:
            self._parquet_writer.close()
        if self._csv_file is not None:
            self._csv_file.close()


def _csv_value(value: Any) -> Any:
    if value is None:
        return ""
    return value


def month_range(start_month: str, end_month: str) -> list[str]:
    start_year, start_num = [int(part) for part in start_month.split("-")]
    end_year, end_num = [int(part) for part in end_month.split("-")]
    current_year, current_num = start_year, start_num
    months: list[str] = []
    while (current_year, current_num) <= (end_year, end_num):
        months.append(f"{current_year:04d}-{current_num:02d}")
        current_num += 1
        if current_num == 13:
            current_year += 1
            current_num = 1
    return months


def month_end_yyyymmdd(month: str) -> str:
    year, month_num = [int(part) for part in month.split("-")]
    return f"{year:04d}{month_num:02d}{calendar.monthrange(year, month_num)[1]:02d}"


def month_from_filename(path: Path) -> str | None:
    parts = path.stem.split("_")
    if len(parts) < 4:
        return None
    candidate = parts[3]
    if len(candidate) == 7 and candidate[4] == "-":
        return candidate
    return None


def country_region(country: str) -> str:
    return COUNTRY_REGION.get(country.upper(), "unknown")


def parse_index(index_path: Path) -> dict[str, dict[str, str]]:
    with index_path.open(newline="", encoding="utf-8") as f:
        return {row["month"]: row for row in csv.DictReader(f)}


def inventory_raw_files(raw_dir: Path, months: list[str], report_path: Path) -> list[dict[str, Any]]:
    expected = set(months)
    files_by_month = {month_from_filename(path): path for path in sorted(raw_dir.glob(RAW_PATTERN))}
    index_rows = parse_index(raw_dir / "index.csv") if (raw_dir / "index.csv").exists() else {}
    rows: list[dict[str, Any]] = []
    for month in months:
        path = files_by_month.get(month)
        expected_date = month_end_yyyymmdd(month)
        exists = path is not None and path.exists()
        actual_sha = sha256_file(path) if path else ""
        index_row = index_rows.get(month, {})
        index_sha = index_row.get("raw_evidence_sha256", "")
        rirs = scan_rir_coverage(path) if path else set()
        rows.append(
            {
                "month": month,
                "expected_snapshot_date": expected_date,
                "raw_evidence_path": relative_to_root(path) if path else "",
                "exists": exists,
                "index_present": bool(index_row),
                "sha256_matches_index": bool(actual_sha and actual_sha == index_sha),
                "actual_sha256": actual_sha,
                "index_sha256": index_sha,
                "rir_coverage": ";".join(sorted(rirs)),
                "has_all_five_rirs": EXPECTED_RIRS.issubset(rirs),
                "unexpected_extra_month_file_count": 0,
            }
        )
    extra_months = {month for month in files_by_month if month and month not in expected}
    if extra_months:
        rows[0]["unexpected_extra_month_file_count"] = len(extra_months)
    write_csv_rows(report_path, rows)
    return rows


def scan_rir_coverage(path: Path) -> set[str]:
    rirs: set[str] = set()
    with path.open(encoding="utf-8", errors="replace") as f:
        for line in f:
            parts = line.rstrip("\n").split("|")
            if len(parts) >= 7 and parts[2] == "asn" and parts[0] in EXPECTED_RIRS:
                rirs.add(parts[0])
                if rirs == EXPECTED_RIRS:
                    break
    return rirs


def parse_delegated_asn_states(path: Path, month: str, file_sha: str) -> Iterator[AsnState]:
    raw_path = relative_to_root(path)
    with path.open(encoding="utf-8", errors="replace") as f:
        for raw in f:
            line = raw.rstrip("\n")
            parts = line.split("|")
            if len(parts) < 7 or parts[2] != "asn":
                continue
            rir = parts[0].strip().lower()
            if rir == "iana":
                # IANA rows include enormous available/reserved ranges. They are
                # not RIR allocations and must not be expanded into analysis rows.
                continue
            if rir not in EXPECTED_RIRS:
                continue
            try:
                start_asn = int(parts[3])
                count = int(parts[4])
            except ValueError:
                continue
            if start_asn <= 0 or count <= 0:
                continue
            country = parts[1].strip().upper() or "ZZ"
            region = country_region(country)
            allocation_date = parts[5].strip()
            status = parts[6].strip().lower()
            for asn in range(start_asn, start_asn + count):
                yield AsnState(
                    asn=asn,
                    month=month,
                    rir=rir,
                    country=country,
                    region=region,
                    status=status,
                    allocation_date=allocation_date,
                    raw_evidence_path=raw_path,
                    raw_evidence_sha256=file_sha,
                    raw_line=line,
                )


def state_to_monthly_row(state: AsnState, run_id: str, config: dict[str, Any]) -> dict[str, Any]:
    return {
        "record_id": f"delegated_{state.asn}_{state.month}",
        "run_id": run_id,
        "schema_version": schema_version(config),
        "parser_version": parser_version(config),
        "asn": state.asn,
        "analysis_month": state.month,
        "rir": state.rir,
        "country": state.country,
        "region": state.region,
        "status": state.status,
        "allocation_date": state.allocation_date,
        "raw_evidence_path": state.raw_evidence_path,
        "raw_evidence_sha256": state.raw_evidence_sha256,
        "raw_line": state.raw_line,
    }


def build_segments_from_states(month_states: list[AsnState], months: list[str]) -> dict[int, list[Segment]]:
    month_index = {month: idx for idx, month in enumerate(months)}
    by_asn: dict[int, list[AsnState]] = defaultdict(list)
    for state in month_states:
        by_asn[state.asn].append(state)
    return {asn: states_to_segments(asn, sorted(states, key=lambda item: month_index[item.month]), month_index) for asn, states in by_asn.items()}


def states_to_segments(asn: int, states: list[AsnState], month_index: dict[str, int]) -> list[Segment]:
    if not states:
        return []
    segments: list[Segment] = []
    current = _segment_from_state(states[0], month_index[states[0].month])
    last_idx = current.end_idx
    for state in states[1:]:
        idx = month_index[state.month]
        if idx > last_idx + 1:
            segments.append(current)
            segments.append(
                Segment(
                    asn=asn,
                    start_idx=last_idx + 1,
                    end_idx=idx - 1,
                    rir="gap",
                    country="gap",
                    region="gap",
                    status="gap",
                    start_raw_evidence_path="",
                    start_raw_evidence_sha256="",
                    end_raw_evidence_path="",
                    end_raw_evidence_sha256="",
                )
            )
            current = _segment_from_state(state, idx)
        elif state.key == current.key:
            current.end_idx = idx
            current.end_raw_evidence_path = state.raw_evidence_path
            current.end_raw_evidence_sha256 = state.raw_evidence_sha256
        else:
            segments.append(current)
            current = _segment_from_state(state, idx)
        last_idx = idx
    segments.append(current)
    return segments


def append_state_to_segments(segments_by_asn: dict[int, list[Segment]], state: AsnState, month_idx: int) -> None:
    segments = segments_by_asn.setdefault(state.asn, [])
    if not segments:
        segments.append(_segment_from_state(state, month_idx))
        return
    current = segments[-1]
    if month_idx > current.end_idx + 1:
        segments.append(
            Segment(
                asn=state.asn,
                start_idx=current.end_idx + 1,
                end_idx=month_idx - 1,
                rir="gap",
                country="gap",
                region="gap",
                status="gap",
                start_raw_evidence_path="",
                start_raw_evidence_sha256="",
                end_raw_evidence_path="",
                end_raw_evidence_sha256="",
            )
        )
        segments.append(_segment_from_state(state, month_idx))
    elif state.key == current.key:
        current.end_idx = month_idx
        current.end_raw_evidence_path = state.raw_evidence_path
        current.end_raw_evidence_sha256 = state.raw_evidence_sha256
    else:
        segments.append(_segment_from_state(state, month_idx))


def _segment_from_state(state: AsnState, idx: int) -> Segment:
    return Segment(
        asn=state.asn,
        start_idx=idx,
        end_idx=idx,
        rir=state.rir,
        country=state.country,
        region=state.region,
        status=state.status,
        start_raw_evidence_path=state.raw_evidence_path,
        start_raw_evidence_sha256=state.raw_evidence_sha256,
        end_raw_evidence_path=state.raw_evidence_path,
        end_raw_evidence_sha256=state.raw_evidence_sha256,
    )


def segment_row(segment: Segment, index: int, months: list[str], run_id: str, config: dict[str, Any]) -> dict[str, Any]:
    return {
        "record_id": f"segment_{segment.asn}_{index}",
        "run_id": run_id,
        "schema_version": schema_version(config),
        "parser_version": parser_version(config),
        "asn": segment.asn,
        "segment_index": index,
        "start_month": months[segment.start_idx],
        "end_month": months[segment.end_idx],
        "duration_months": segment.end_idx - segment.start_idx + 1,
        "rir": segment.rir,
        "country": segment.country,
        "region": segment.region,
        "status": segment.status,
        "start_raw_evidence_path": segment.start_raw_evidence_path,
        "start_raw_evidence_sha256": segment.start_raw_evidence_sha256,
        "end_raw_evidence_path": segment.end_raw_evidence_path,
        "end_raw_evidence_sha256": segment.end_raw_evidence_sha256,
    }


def observed_segments(segments: list[Segment]) -> list[Segment]:
    return [segment for segment in segments if not segment.is_gap]


def sequence(values: Iterable[str]) -> list[str]:
    out: list[str] = []
    for value in values:
        if not out or out[-1] != value:
            out.append(value)
    return out


def count_changes(values: list[str]) -> int:
    return sum(1 for before, after in zip(values, values[1:]) if before != after)


def classify_trajectory(segments: list[Segment], months: list[str]) -> str:
    observed = observed_segments(segments)
    if not observed:
        return "data_gap"
    if any(segment.is_gap for segment in segments):
        return "data_gap"
    country_seq = sequence(segment.country for segment in observed)
    region_seq = sequence(segment.region for segment in observed)
    rir_seq = sequence(segment.rir for segment in observed)
    if len(country_seq) >= 3 and country_seq[0] == country_seq[-1] and len(set(country_seq)) > 1:
        return "temporary_revert"
    if len(country_seq) > len(set(country_seq)) or len(region_seq) > len(set(region_seq)) or len(rir_seq) > len(set(rir_seq)):
        return "oscillation"
    if len(rir_seq) > 1:
        return "cross_rir_move"
    if len(region_seq) > 1:
        return "cross_region_move"
    if len(country_seq) > 2:
        return "multi_country_move"
    if len(country_seq) == 2:
        return "single_country_move"
    if observed[0].start_idx > 0:
        return "appeared_late"
    if observed[-1].end_idx < len(months) - 1:
        return "disappeared_early"
    return "stable"


def trajectory_row(asn: int, segments: list[Segment], months: list[str], run_id: str, config: dict[str, Any]) -> dict[str, Any]:
    observed = observed_segments(segments)
    first = observed[0]
    last = observed[-1]
    rir_seq = sequence(segment.rir for segment in observed)
    country_seq = sequence(segment.country for segment in observed)
    region_seq = sequence(segment.region for segment in observed)
    status_seq = sequence(segment.status for segment in observed)
    observed_months = sum(segment.end_idx - segment.start_idx + 1 for segment in observed)
    return {
        "record_id": f"trajectory_{asn}",
        "run_id": run_id,
        "schema_version": schema_version(config),
        "parser_version": parser_version(config),
        "asn": asn,
        "first_seen_month": months[first.start_idx],
        "last_seen_month": months[last.end_idx],
        "observed_months": observed_months,
        "missing_months": len(months) - observed_months,
        "segment_count": len(observed),
        "rir_sequence": " -> ".join(rir_seq),
        "country_sequence": " -> ".join(country_seq),
        "region_sequence": " -> ".join(region_seq),
        "status_sequence": " -> ".join(status_seq),
        "changed_rir_count": count_changes(rir_seq),
        "changed_country_count": count_changes(country_seq),
        "changed_region_count": count_changes(region_seq),
        "max_stable_months": max(segment.end_idx - segment.start_idx + 1 for segment in observed),
        "trajectory_type": classify_trajectory(segments, months),
        "first_raw_evidence_path": first.start_raw_evidence_path,
        "first_raw_evidence_sha256": first.start_raw_evidence_sha256,
        "last_raw_evidence_path": last.end_raw_evidence_path,
        "last_raw_evidence_sha256": last.end_raw_evidence_sha256,
    }


def event_rows(asn: int, segments: list[Segment], months: list[str], run_id: str, config: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    observed = observed_segments(segments)
    if observed and observed[0].start_idx > 0:
        rows.append(_boundary_event(asn, None, observed[0], "appeared", months, run_id, config, len(rows) + 1))
    for before, after in zip(segments, segments[1:]):
        if before.is_gap and not after.is_gap:
            change_type = "gap_end"
        elif after.is_gap and not before.is_gap:
            change_type = "gap_start"
        elif before.is_gap or after.is_gap:
            change_type = "gap_start,gap_end"
        else:
            types: list[str] = []
            if before.rir != after.rir:
                types.append("rir_change")
            if before.country != after.country:
                types.append("country_change")
            if before.region != after.region:
                types.append("region_change")
            if before.status != after.status:
                types.append("status_change")
            change_type = ",".join(types) if types else "status_change"
        rows.append(_boundary_event(asn, before, after, change_type, months, run_id, config, len(rows) + 1))
    if observed and observed[-1].end_idx < len(months) - 1:
        rows.append(_boundary_event(asn, observed[-1], None, "disappeared", months, run_id, config, len(rows) + 1))
    return rows


def _boundary_event(
    asn: int,
    before: Segment | None,
    after: Segment | None,
    change_type: str,
    months: list[str],
    run_id: str,
    config: dict[str, Any],
    index: int,
) -> dict[str, Any]:
    from_idx = before.end_idx if before else max(after.start_idx - 1, 0)  # type: ignore[union-attr]
    to_idx = after.start_idx if after else min(before.end_idx + 1, len(months) - 1)  # type: ignore[union-attr]
    return {
        "record_id": f"event_{asn}_{index}",
        "run_id": run_id,
        "schema_version": schema_version(config),
        "parser_version": parser_version(config),
        "asn": asn,
        "from_month": months[from_idx],
        "to_month": months[to_idx],
        "from_rir": before.rir if before else "",
        "to_rir": after.rir if after else "",
        "from_country": before.country if before else "",
        "to_country": after.country if after else "",
        "from_region": before.region if before else "",
        "to_region": after.region if after else "",
        "from_status": before.status if before else "",
        "to_status": after.status if after else "",
        "change_type": change_type,
        "from_duration_months": before.end_idx - before.start_idx + 1 if before else 0,
        "to_duration_months": after.end_idx - after.start_idx + 1 if after else 0,
        "from_raw_evidence_path": before.end_raw_evidence_path if before else "",
        "from_raw_evidence_sha256": before.end_raw_evidence_sha256 if before else "",
        "to_raw_evidence_path": after.start_raw_evidence_path if after else "",
        "to_raw_evidence_sha256": after.start_raw_evidence_sha256 if after else "",
    }


def write_csv_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_reports(report_dir: Path, trajectories: list[dict[str, Any]], events: list[dict[str, Any]], months: list[str]) -> None:
    ensure_dirs([report_dir])
    observed_events = [row for row in events if row["change_type"] not in {"appeared", "disappeared", "gap_start", "gap_end"}]
    top_changed = sorted(
        trajectories,
        key=lambda row: (
            int(row["changed_region_count"]),
            int(row["changed_country_count"]),
            int(row["changed_rir_count"]),
            int(row["segment_count"]),
        ),
        reverse=True,
    )[:200]
    write_csv_rows(report_dir / "top_changed_asns.csv", top_changed)
    write_csv_rows(report_dir / "country_transition_matrix.csv", transition_matrix(observed_events, "from_country", "to_country"))
    write_csv_rows(report_dir / "rir_transition_matrix.csv", transition_matrix(observed_events, "from_rir", "to_rir"))
    write_csv_rows(report_dir / "region_transition_matrix.csv", transition_matrix(observed_events, "from_region", "to_region"))
    write_csv_rows(report_dir / "high_priority_review_candidates.csv", high_priority_candidates(trajectories, events))
    summary = build_summary_md(trajectories, events, months)
    (report_dir / "summary.md").write_text(summary, encoding="utf-8")


def transition_matrix(events: list[dict[str, Any]], from_field: str, to_field: str) -> list[dict[str, Any]]:
    counts: Counter[tuple[str, str]] = Counter()
    for row in events:
        source = str(row.get(from_field, ""))
        target = str(row.get(to_field, ""))
        if source and target and source != "gap" and target != "gap" and source != target:
            counts[(source, target)] += 1
    return [
        {"from": source, "to": target, "event_count": count}
        for (source, target), count in counts.most_common()
    ]


def high_priority_candidates(trajectories: list[dict[str, Any]], events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    events_by_asn: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        events_by_asn[int(event["asn"])].append(event)
    rows: list[dict[str, Any]] = []
    for row in trajectories:
        asn = int(row["asn"])
        event_list = events_by_asn.get(asn, [])
        reasons: list[str] = []
        if int(row["changed_rir_count"]) > 0 and int(row["changed_country_count"]) > 0:
            reasons.append("cross_rir_and_country")
        if int(row["changed_region_count"]) > 0:
            reasons.append("cross_region")
        if int(row["segment_count"]) > 2:
            reasons.append("multiple_changes")
        if row["trajectory_type"] in {"temporary_revert", "oscillation"}:
            reasons.append("revert_or_oscillation")
        if any(event["change_type"] != "disappeared" and str(event["to_status"]) in {"allocated", "assigned"} for event in event_list):
            reasons.append("changed_to_allocated_or_assigned")
        if reasons:
            rows.append({**row, "review_reasons": ";".join(reasons)})
    return sorted(
        rows,
        key=lambda item: (
            int(item["changed_region_count"]),
            int(item["changed_country_count"]),
            int(item["changed_rir_count"]),
            int(item["segment_count"]),
        ),
        reverse=True,
    )


def build_summary_md(trajectories: list[dict[str, Any]], events: list[dict[str, Any]], months: list[str]) -> str:
    type_counts = Counter(row["trajectory_type"] for row in trajectories)
    country_paths = Counter(row["country_sequence"] for row in trajectories if int(row["changed_country_count"]) > 0)
    rir_paths = Counter(row["rir_sequence"] for row in trajectories if int(row["changed_rir_count"]) > 0)
    lines = [
        "# ASN 近五年 registry 区域连续变化分析",
        "",
        f"- 分析窗口：`{months[0]}` 到 `{months[-1]}`",
        f"- ASN 轨迹数量：{len(trajectories)}",
        f"- 5 年稳定 ASN 数量：{type_counts.get('stable', 0)}",
        f"- 发生国家变化的 ASN 数量：{sum(1 for row in trajectories if int(row['changed_country_count']) > 0)}",
        f"- 发生 RIR 变化的 ASN 数量：{sum(1 for row in trajectories if int(row['changed_rir_count']) > 0)}",
        f"- 发生大区变化的 ASN 数量：{sum(1 for row in trajectories if int(row['changed_region_count']) > 0)}",
        f"- 一次迁移 ASN 数量：{type_counts.get('single_country_move', 0)}",
        f"- 多次迁移 ASN 数量：{type_counts.get('multi_country_move', 0) + type_counts.get('cross_region_move', 0) + type_counts.get('cross_rir_move', 0)}",
        f"- 反复变化 ASN 数量：{type_counts.get('temporary_revert', 0) + type_counts.get('oscillation', 0)}",
        f"- 短期变化后回退 ASN 数量：{type_counts.get('temporary_revert', 0)}",
        "",
        "## 轨迹类型分布",
        "",
    ]
    for item, count in sorted(type_counts.items()):
        lines.append(f"- `{item}`: {count}")
    lines.extend(["", "## 最常见国家变化路径", ""])
    for path, count in country_paths.most_common(20):
        lines.append(f"- `{path}`: {count}")
    lines.extend(["", "## 最常见 RIR 变化路径", ""])
    for path, count in rir_paths.most_common(20):
        lines.append(f"- `{path}`: {count}")
    lines.extend(
        [
            "",
            "## 方法边界",
            "",
            "本报告只基于 NRO delegated stats 的行政分配记录，输出用于人工复核候选，不代表最终异常裁定。",
            "IANA `available/reserved` 巨大区间未展开进 ASN 月度状态，也不参与跨 RIR 迁移判断。",
        ]
    )
    return "\n".join(lines) + "\n"


def run_analysis(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    run_id = args.run_id or str(config["run"]["run_id"])
    raw_dir = args.raw_dir if args.raw_dir.is_absolute() else Path.cwd() / args.raw_dir
    staging_dir = args.staging_dir if args.staging_dir.is_absolute() else Path.cwd() / args.staging_dir
    curated_dir = args.curated_dir if args.curated_dir.is_absolute() else Path.cwd() / args.curated_dir
    report_dir = args.report_dir if args.report_dir.is_absolute() else Path.cwd() / args.report_dir
    months = month_range(args.start_month, args.end_month)
    ensure_dirs([staging_dir, curated_dir, report_dir])

    inventory_rows = inventory_raw_files(raw_dir, months, report_dir / "raw_inventory_check.csv")
    bad_inventory = [
        row
        for row in inventory_rows
        if not row["exists"] or not row["index_present"] or not row["sha256_matches_index"] or not row["has_all_five_rirs"]
    ]
    if bad_inventory and not args.allow_bad_inventory:
        raise SystemExit(f"raw inventory check failed for {len(bad_inventory)} months; see {relative_to_root(report_dir / 'raw_inventory_check.csv')}")

    files_by_month = {month_from_filename(path): path for path in sorted(raw_dir.glob(RAW_PATTERN))}
    segments_by_asn: dict[int, list[Segment]] = {}
    duplicates = 0
    monthly_row_count = 0
    monthly_csv = staging_dir / "asn_delegated_monthly.csv"
    monthly_parquet = staging_dir / "asn_delegated_monthly.parquet"
    with TableSink(monthly_csv, monthly_parquet, MONTHLY_COLUMNS, args.parquet_chunk_size) as sink:
        for month_idx, month in enumerate(months):
            path = files_by_month[month]
            file_sha = sha256_file(path)
            seen_asns: set[int] = set()
            for state in parse_delegated_asn_states(path, month, file_sha):
                if state.asn in seen_asns:
                    duplicates += 1
                    continue
                seen_asns.add(state.asn)
                monthly_row_count += 1
                append_state_to_segments(segments_by_asn, state, month_idx)
                sink.write(state_to_monthly_row(state, run_id, config))
            print(f"[stage] {month}: {len(seen_asns)} ASN rows")
    segment_csv = curated_dir / "asn_region_state_segments.csv"
    segment_parquet = curated_dir / "asn_region_state_segments.parquet"
    trajectory_csv = curated_dir / "asn_region_trajectories.csv"
    trajectory_parquet = curated_dir / "asn_region_trajectories.parquet"
    event_csv = curated_dir / "asn_region_change_events.csv"
    event_parquet = curated_dir / "asn_region_change_events.parquet"

    trajectories: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    with TableSink(segment_csv, segment_parquet, SEGMENT_COLUMNS, args.parquet_chunk_size) as segment_sink:
        with TableSink(trajectory_csv, trajectory_parquet, TRAJECTORY_COLUMNS, args.parquet_chunk_size) as trajectory_sink:
            with TableSink(event_csv, event_parquet, EVENT_COLUMNS, args.parquet_chunk_size) as event_sink:
                for asn in sorted(segments_by_asn):
                    segments = segments_by_asn[asn]
                    for idx, segment in enumerate(segments, start=1):
                        segment_sink.write(segment_row(segment, idx, months, run_id, config))
                    trajectory = trajectory_row(asn, segments, months, run_id, config)
                    trajectories.append(trajectory)
                    trajectory_sink.write(trajectory)
                    asn_events = event_rows(asn, segments, months, run_id, config)
                    events.extend(asn_events)
                    event_sink.write_many(asn_events)

    write_reports(report_dir, trajectories, events, months)
    print(
        "saved delegated monthly analysis: "
        f"monthly_rows={monthly_row_count} segments={sum(len(value) for value in segments_by_asn.values())} "
        f"trajectories={len(trajectories)} events={len(events)} duplicates_skipped={duplicates}"
    )
    print(f"reports: {relative_to_root(report_dir)} generated_at={utc_now()}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build five-year ASN registry region-change outputs from local NRO delegated snapshots.")
    parser.add_argument("--config", type=Path, default=Path("configs/pipeline.yaml"))
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw/registry/delegated_monthly_go"))
    parser.add_argument("--staging-dir", type=Path, default=Path("data/staging/registry"))
    parser.add_argument("--curated-dir", type=Path, default=Path("data/curated/registry"))
    parser.add_argument("--report-dir", type=Path, default=Path("reports/asn_region_changes"))
    parser.add_argument("--start-month", default=DEFAULT_START_MONTH)
    parser.add_argument("--end-month", default=DEFAULT_END_MONTH)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--allow-bad-inventory", action="store_true")
    parser.add_argument("--parquet-chunk-size", type=int, default=100_000)
    args = parser.parse_args()
    run_analysis(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

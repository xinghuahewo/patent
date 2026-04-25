#!/usr/bin/env python3
"""Validate v1 pipeline outputs against the documented schema contracts."""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

try:
    from tqdm import tqdm
except ImportError:  # pragma: no cover - optional runtime dependency
    tqdm = None

from pipeline_utils import (
    COUNTRY_RE,
    add_common_args,
    as_bool,
    as_float,
    as_int,
    load_config,
    parse_asn,
    parse_month,
    read_table,
    repo_root,
    sha256_file,
)


REQUIRED = {
    "registry": [
        "record_id",
        "run_id",
        "schema_version",
        "parser_version",
        "asn",
        "analysis_month",
        "admin_conflict_flag",
        "multi_country_registry_flag",
        "cloud_or_cdn_flag",
        "crossborder_group_flag",
        "hosting_or_lease_hint_flag",
        "raw_evidence_path",
        "raw_evidence_sha256",
        "fetch_time",
    ],
    "links": [
        "record_id",
        "run_id",
        "schema_version",
        "parser_version",
        "asn",
        "analysis_month",
        "window_start",
        "window_end",
        "link_instability_flag",
        "border_as_flag",
        "topology_anomaly_flag",
        "raw_evidence_path",
        "raw_evidence_sha256",
    ],
    "prefixes": [
        "record_id",
        "run_id",
        "schema_version",
        "parser_version",
        "asn",
        "analysis_month",
        "source_collector",
        "source_snapshot_time",
        "prefix_count_v4",
        "prefix_count_v6",
        "total_prefix_count",
        "raw_evidence_path",
        "raw_evidence_sha256",
        "fetch_time",
    ],
    "stage1": [
        "record_id",
        "run_id",
        "schema_version",
        "parser_version",
        "asn",
        "month",
        "admin_conflict_flag",
        "geo_conflict_flag",
        "topology_anomaly_flag",
        "border_as_flag",
        "suspect_level",
        "review_required_flag",
        "raw_evidence_path",
        "raw_evidence_sha256",
    ],
    "delegated_monthly": [
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
    ],
    "region_segments": [
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
    ],
    "region_trajectories": [
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
    ],
    "region_change_events": [
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
    ],
}

BOOL_FIELDS = {
    "registry": [
        "admin_conflict_flag",
        "multi_country_registry_flag",
        "cloud_or_cdn_flag",
        "crossborder_group_flag",
        "hosting_or_lease_hint_flag",
    ],
    "links": ["link_instability_flag", "border_as_flag", "topology_anomaly_flag"],
    "prefixes": [],
    "stage1": ["admin_conflict_flag", "geo_conflict_flag", "topology_anomaly_flag", "border_as_flag", "review_required_flag"],
    "delegated_monthly": [],
    "region_segments": [],
    "region_trajectories": [],
    "region_change_events": [],
}

EXPECTED_RIRS = {"afrinic", "apnic", "arin", "lacnic", "ripencc"}
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
EVENT_TYPES = {"rir_change", "country_change", "region_change", "status_change", "appeared", "disappeared", "gap_start", "gap_end"}


@dataclass
class StageSummary:
    stage_name: str
    status: str
    row_count: int
    error_count: int
    elapsed_seconds: float


def configure_logging(verbose: bool, timestamp: str) -> tuple[logging.Logger, Path]:
    log_dir = Path("logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"validate_{timestamp}.log"

    logger = logging.getLogger("validate_outputs")
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    logger.handlers.clear()
    logger.propagate = False

    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

    stream_handler = logging.StreamHandler(sys.stderr)
    stream_handler.setLevel(logging.DEBUG if verbose else logging.INFO)
    stream_handler.setFormatter(formatter)

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    logger.addHandler(stream_handler)
    logger.addHandler(file_handler)
    return logger, log_path


def progress_iter(iterable: Iterable[Any], *, total: int | None, desc: str, enabled: bool) -> Iterable[Any]:
    if enabled and tqdm is not None:
        return tqdm(iterable, total=total, desc=desc, unit="rows")
    return iterable


def count_csv_rows(csv_path: Path) -> int:
    if not csv_path.exists() or csv_path.stat().st_size == 0:
        return 0
    with csv_path.open(encoding="utf-8") as f:
        return max(sum(1 for _ in f) - 1, 0)


def output_row_count(config: dict[str, Any], stage: str) -> int:
    csv_path, _ = stage_paths(config, stage)
    csv_path = csv_path if csv_path.is_absolute() else Path.cwd() / csv_path
    return count_csv_rows(csv_path)


def stage_paths(config: dict[str, Any], stage: str) -> tuple[Path, Path]:
    if stage == "registry":
        root = Path(config["paths"]["staging_root"]) / "registry"
        return root / "asn_registry_baseline_monthly.csv", root / "asn_registry_baseline_monthly.parquet"
    if stage == "links":
        root = Path(config["paths"]["staging_root"]) / "links"
        return root / "asn_link_summary_monthly.csv", root / "asn_link_summary_monthly.parquet"
    if stage == "prefixes":
        root = Path(config["paths"]["staging_root"]) / "prefixes"
        return root / "asn_prefix_inventory_monthly.csv", root / "asn_prefix_inventory_monthly.parquet"
    if stage == "delegated_monthly":
        root = Path(config["paths"]["staging_root"]) / "registry"
        return root / "asn_delegated_monthly.csv", root / "asn_delegated_monthly.parquet"
    if stage == "region_segments":
        root = Path(config["paths"]["curated_root"]) / "registry"
        return root / "asn_region_state_segments.csv", root / "asn_region_state_segments.parquet"
    if stage == "region_trajectories":
        root = Path(config["paths"]["curated_root"]) / "registry"
        return root / "asn_region_trajectories.csv", root / "asn_region_trajectories.parquet"
    if stage == "region_change_events":
        root = Path(config["paths"]["curated_root"]) / "registry"
        return root / "asn_region_change_events.csv", root / "asn_region_change_events.parquet"
    root = Path(config["paths"]["curated_root"]) / "stage1"
    return root / "asn_suspect_stage1.csv", root / "asn_suspect_stage1.parquet"


def validate_stage(config: dict[str, Any], stage: str, *, progress_enabled: bool = False) -> list[str]:
    if stage in {"delegated_monthly", "region_segments", "region_trajectories", "region_change_events"}:
        return validate_region_change_stage(config, stage, progress_enabled=progress_enabled)
    csv_path, parquet_path = stage_paths(config, stage)
    rows = read_table(csv_path if csv_path.is_absolute() else Path.cwd() / csv_path, parquet_path if parquet_path.is_absolute() else Path.cwd() / parquet_path)
    errors: list[str] = []
    if not rows:
        return [f"{stage}: no rows found at {csv_path}"]

    seen: set[tuple[str, str, str]] = set()
    for idx, row in enumerate(progress_iter(rows, total=len(rows), desc=stage, enabled=progress_enabled), start=2):
        context = f"{stage}:row{idx}"
        for field in REQUIRED[stage]:
            if field not in row or row[field] is None or str(row[field]).strip() == "":
                errors.append(f"{context}: missing required field {field}")
        try:
            asn = parse_asn(row.get("asn"), context)
        except ValueError as exc:
            errors.append(str(exc))
            asn = -1
        month_field = "month" if stage == "stage1" else "analysis_month"
        try:
            month = parse_month(row.get(month_field), context)
        except ValueError as exc:
            errors.append(str(exc))
            month = ""
        run_id = str(row.get("run_id", ""))
        key = (str(asn), month, run_id)
        if key in seen:
            errors.append(f"{context}: duplicate (asn, month, run_id) {key}")
        seen.add(key)

        for field in BOOL_FIELDS[stage]:
            try:
                as_bool(row.get(field))
            except ValueError as exc:
                errors.append(f"{context}: {field}: {exc}")

        if stage == "registry":
            for field in ("allocated_country", "registered_country"):
                value = row.get(field)
                if value and not COUNTRY_RE.match(str(value).strip().upper()):
                    errors.append(f"{context}: {field} must be ISO-like two-letter country code when present")
        if stage == "links":
            if str(row.get("window_start")) > str(row.get("window_end")):
                errors.append(f"{context}: window_start must be <= window_end")
            for field in (
                "observed_neighbor_count",
                "provider_count",
                "customer_count",
                "peer_count",
                "unknown_count",
                "new_neighbor_count",
                "lost_neighbor_count",
                "provider_switch_count",
            ):
                try:
                    if as_int(row.get(field), 0) < 0:
                        errors.append(f"{context}: {field} must be non-negative")
                except Exception:
                    errors.append(f"{context}: {field} must be integer-like")
            try:
                churn = as_float(row.get("neighbor_churn_rate"), 0.0)
                if not 0.0 <= churn <= 1.0:
                    errors.append(f"{context}: neighbor_churn_rate must be in [0.0, 1.0]")
            except Exception:
                errors.append(f"{context}: neighbor_churn_rate must be float-like")
        if stage == "prefixes":
            try:
                prefix_count_v4 = as_int(row.get("prefix_count_v4"), 0)
                prefix_count_v6 = as_int(row.get("prefix_count_v6"), 0)
                total_prefix_count = as_int(row.get("total_prefix_count"), 0)
                if min(prefix_count_v4, prefix_count_v6, total_prefix_count) < 0:
                    errors.append(f"{context}: prefix counts must be non-negative")
                if total_prefix_count != prefix_count_v4 + prefix_count_v6:
                    errors.append(f"{context}: total_prefix_count must equal prefix_count_v4 + prefix_count_v6")
            except Exception:
                errors.append(f"{context}: prefix counts must be integer-like")
        if stage == "stage1" and row.get("suspect_level") not in {"high", "medium", "low"}:
            errors.append(f"{context}: suspect_level must be high/medium/low")
    return errors


def validate_region_change_stage(config: dict[str, Any], stage: str, *, progress_enabled: bool = False) -> list[str]:
    csv_path, parquet_path = stage_paths(config, stage)
    csv_path = csv_path if csv_path.is_absolute() else Path.cwd() / csv_path
    parquet_path = parquet_path if parquet_path.is_absolute() else Path.cwd() / parquet_path
    errors: list[str] = []
    if not csv_path.exists() or csv_path.stat().st_size == 0:
        return [f"{stage}: no rows found at {csv_path}"]
    if not parquet_path.exists() or parquet_path.stat().st_size == 0:
        errors.append(f"{stage}: missing parquet output {parquet_path}")

    seen: set[tuple[str, ...]] = set()
    delegated_seen_asns: set[tuple[str, str]] = set()
    delegated_current_month = ""
    raw_sha_cache: dict[str, str] = {}
    row_count = 0
    total_rows = count_csv_rows(csv_path)
    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for idx, row in enumerate(progress_iter(reader, total=total_rows, desc=stage, enabled=progress_enabled), start=2):
            row_count += 1
            context = f"{stage}:row{idx}"
            for field in REQUIRED[stage]:
                if field not in row:
                    errors.append(f"{context}: missing required field {field}")
            if len(errors) > 200:
                return errors
            try:
                asn = parse_asn(row.get("asn"), context)
            except ValueError as exc:
                errors.append(str(exc))
                asn = -1
            if stage == "delegated_monthly":
                _validate_delegated_monthly_row(row, context, errors, raw_sha_cache)
                month = str(row.get("analysis_month") or "")
                if delegated_current_month and month < delegated_current_month:
                    errors.append(f"{context}: analysis_month must be non-decreasing")
                if month != delegated_current_month:
                    delegated_current_month = month
                    delegated_seen_asns.clear()
                key = (str(asn), str(row.get("run_id")))
                if key in delegated_seen_asns:
                    errors.append(f"{context}: duplicate (asn, analysis_month, run_id) {(asn, month, row.get('run_id'))}")
                delegated_seen_asns.add(key)
                continue
            elif stage == "region_segments":
                _validate_segment_row(row, context, errors, raw_sha_cache)
                key = (str(asn), str(row.get("segment_index")), str(row.get("run_id")))
            elif stage == "region_trajectories":
                _validate_trajectory_row(row, context, errors, raw_sha_cache)
                key = (str(asn), str(row.get("run_id")))
            else:
                _validate_event_row(row, context, errors, raw_sha_cache)
                key = (str(asn), str(row.get("record_id")), str(row.get("run_id")))
            if key in seen:
                errors.append(f"{context}: duplicate key {key}")
            seen.add(key)
            if len(errors) > 200:
                return errors
    if row_count == 0:
        errors.append(f"{stage}: no data rows found at {csv_path}")
    return errors


def _validate_delegated_monthly_row(row: dict[str, Any], context: str, errors: list[str], raw_sha_cache: dict[str, str]) -> None:
    try:
        parse_month(row.get("analysis_month"), context)
    except ValueError as exc:
        errors.append(str(exc))
    if row.get("rir") not in EXPECTED_RIRS:
        errors.append(f"{context}: rir must be one of {sorted(EXPECTED_RIRS)}")
    country = str(row.get("country") or "").upper()
    if country != "ZZ" and not COUNTRY_RE.match(country):
        errors.append(f"{context}: country must be two-letter country code or ZZ")
    if not str(row.get("region") or "").strip():
        errors.append(f"{context}: region must be non-empty")
    _validate_raw_sha(row.get("raw_evidence_path"), row.get("raw_evidence_sha256"), context, "raw_evidence", errors, raw_sha_cache)


def _validate_segment_row(row: dict[str, Any], context: str, errors: list[str], raw_sha_cache: dict[str, str]) -> None:
    start = _parse_month_or_error(row.get("start_month"), context, errors)
    end = _parse_month_or_error(row.get("end_month"), context, errors)
    try:
        duration = as_int(row.get("duration_months"))
        if duration <= 0:
            errors.append(f"{context}: duration_months must be positive")
        if start and end and duration != _duration_months(start, end):
            errors.append(f"{context}: duration_months does not match start/end")
    except Exception:
        errors.append(f"{context}: duration_months must be integer-like")
    if str(row.get("status")) == "gap":
        return
    _validate_raw_sha(row.get("start_raw_evidence_path"), row.get("start_raw_evidence_sha256"), context, "start_raw_evidence", errors, raw_sha_cache)
    _validate_raw_sha(row.get("end_raw_evidence_path"), row.get("end_raw_evidence_sha256"), context, "end_raw_evidence", errors, raw_sha_cache)


def _validate_trajectory_row(row: dict[str, Any], context: str, errors: list[str], raw_sha_cache: dict[str, str]) -> None:
    first = _parse_month_or_error(row.get("first_seen_month"), context, errors)
    last = _parse_month_or_error(row.get("last_seen_month"), context, errors)
    if first and last and first > last:
        errors.append(f"{context}: first_seen_month must be <= last_seen_month")
    for field in ("observed_months", "missing_months", "segment_count", "changed_rir_count", "changed_country_count", "changed_region_count", "max_stable_months"):
        try:
            if as_int(row.get(field)) < 0:
                errors.append(f"{context}: {field} must be non-negative")
        except Exception:
            errors.append(f"{context}: {field} must be integer-like")
    if row.get("trajectory_type") not in TRAJECTORY_TYPES:
        errors.append(f"{context}: trajectory_type is not allowed")
    _validate_raw_sha(row.get("first_raw_evidence_path"), row.get("first_raw_evidence_sha256"), context, "first_raw_evidence", errors, raw_sha_cache)
    _validate_raw_sha(row.get("last_raw_evidence_path"), row.get("last_raw_evidence_sha256"), context, "last_raw_evidence", errors, raw_sha_cache)


def _validate_event_row(row: dict[str, Any], context: str, errors: list[str], raw_sha_cache: dict[str, str]) -> None:
    from_month = _parse_month_or_error(row.get("from_month"), context, errors)
    to_month = _parse_month_or_error(row.get("to_month"), context, errors)
    if from_month and to_month and from_month > to_month:
        errors.append(f"{context}: from_month must be <= to_month")
    parts = {part for part in str(row.get("change_type") or "").split(",") if part}
    if not parts or not parts.issubset(EVENT_TYPES):
        errors.append(f"{context}: change_type has unsupported value")
    for field in ("from_duration_months", "to_duration_months"):
        try:
            if as_int(row.get(field)) < 0:
                errors.append(f"{context}: {field} must be non-negative")
        except Exception:
            errors.append(f"{context}: {field} must be integer-like")
    if row.get("from_raw_evidence_path"):
        _validate_raw_sha(row.get("from_raw_evidence_path"), row.get("from_raw_evidence_sha256"), context, "from_raw_evidence", errors, raw_sha_cache)
    if row.get("to_raw_evidence_path"):
        _validate_raw_sha(row.get("to_raw_evidence_path"), row.get("to_raw_evidence_sha256"), context, "to_raw_evidence", errors, raw_sha_cache)


def _parse_month_or_error(value: Any, context: str, errors: list[str]) -> str | None:
    try:
        return parse_month(value, context)
    except ValueError as exc:
        errors.append(str(exc))
        return None


def _duration_months(start: str, end: str) -> int:
    start_year, start_month = [int(part) for part in start.split("-")]
    end_year, end_month = [int(part) for part in end.split("-")]
    return (end_year - start_year) * 12 + end_month - start_month + 1


def _validate_raw_sha(
    raw_path: Any,
    expected_sha: Any,
    context: str,
    label: str,
    errors: list[str],
    raw_sha_cache: dict[str, str],
) -> None:
    path_text = str(raw_path or "").strip()
    sha_text = str(expected_sha or "").strip()
    if not path_text or not sha_text:
        errors.append(f"{context}: {label} path and sha256 are required")
        return
    path = Path(path_text)
    if not path.is_absolute():
        path = repo_root() / path
    if not path.exists():
        errors.append(f"{context}: {label} path does not exist: {path_text}")
        return
    if path_text not in raw_sha_cache:
        raw_sha_cache[path_text] = sha256_file(path)
    if raw_sha_cache[path_text] != sha_text:
        errors.append(f"{context}: {label} sha256 mismatch for {path_text}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate pipeline output tables.")
    add_common_args(parser)
    parser.add_argument(
        "--stage",
        choices=[
            "registry",
            "links",
            "prefixes",
            "stage1",
            "delegated_monthly",
            "region_segments",
            "region_trajectories",
            "region_change_events",
            "all",
        ],
        default="all",
    )
    parser.add_argument("--verbose", action="store_true", help="Enable detailed logs.")
    parser.add_argument("--fail-fast", action="store_true", help="Stop after the first failed stage.")
    parser.add_argument("--no-progress", action="store_true", help="Disable tqdm progress bars, useful for CI.")
    args = parser.parse_args(argv)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    logger, log_path = configure_logging(args.verbose, timestamp)
    progress_enabled = not args.no_progress
    if progress_enabled and tqdm is None:
        logger.warning("tqdm is not installed; continuing without progress bars. Install with: pip install tqdm")
        progress_enabled = False

    config = load_config(args.config)
    stages = [
        "registry",
        "links",
        "prefixes",
        "stage1",
        "delegated_monthly",
        "region_segments",
        "region_trajectories",
        "region_change_events",
    ] if args.stage == "all" else [args.stage]

    errors: list[str] = []
    summaries: list[StageSummary] = []
    logger.info("Validation started: stage=%s", args.stage)
    logger.info("Log file: %s", log_path)

    for stage in stages:
        stage_start = time.perf_counter()
        csv_path, parquet_path = stage_paths(config, stage)
        logger.info("Start stage: %s", stage)
        if args.verbose:
            logger.debug("CSV path: %s", csv_path)
            logger.debug("Parquet path: %s", parquet_path)

        stage_errors = validate_stage(config, stage, progress_enabled=progress_enabled)
        elapsed = time.perf_counter() - stage_start
        row_count = output_row_count(config, stage)
        status = "ok" if not stage_errors else "failed"
        summary = StageSummary(
            stage_name=stage,
            status=status,
            row_count=row_count,
            error_count=len(stage_errors),
            elapsed_seconds=round(elapsed, 3),
        )
        summaries.append(summary)

        if stage_errors:
            errors.extend(stage_errors)
            logger.error(
                "Stage failed: %s rows=%s errors=%s elapsed=%.3fs",
                stage,
                row_count,
                len(stage_errors),
                elapsed,
            )
            if args.fail_fast:
                logger.error("Fail-fast enabled; stopping after stage: %s", stage)
                break
        else:
            logger.info("Stage ok: %s rows=%s elapsed=%.3fs", stage, row_count, elapsed)

    reports_dir = Path("reports")
    reports_dir.mkdir(parents=True, exist_ok=True)
    error_report_path = reports_dir / f"validation_errors_{timestamp}.txt"
    summary_report_path = reports_dir / f"validation_summary_{timestamp}.json"

    error_report_path.write_text("\n".join(errors) + ("\n" if errors else ""), encoding="utf-8")
    summary_report_path.write_text(
        json.dumps([asdict(summary) for summary in summaries], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    logger.info("Validation summary:")
    for summary in summaries:
        logger.info(
            "- %s: %s, rows=%s, errors=%s, elapsed=%.3fs",
            summary.stage_name,
            summary.status,
            summary.row_count,
            summary.error_count,
            summary.elapsed_seconds,
        )
    logger.info("Error report: %s", error_report_path)
    logger.info("Summary report: %s", summary_report_path)

    if errors:
        for error in errors:
            logger.error(error)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Shared helpers for the file-first ASN mismatch pipeline."""

from __future__ import annotations

import argparse
import calendar
import csv
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


MONTH_RE = re.compile(r"^\d{4}-\d{2}$")
COUNTRY_RE = re.compile(r"^[A-Z]{2}$")


DEFAULT_CONFIG: dict[str, Any] = {
    "project": {
        "schema_version": "v1",
        "parser_version": "v1",
    },
    "run": {
        "run_id": "manual_2026_04_23_01",
    },
    "input": {
        "asn_months_csv": "data/input/asn_months.csv",
    },
    "paths": {
        "raw_root": "data/raw",
        "staging_root": "data/staging",
        "curated_root": "data/curated",
        "reports_root": "reports",
        "logs_root": "data/raw/_logs",
    },
    "thresholds": {
        "topology": {
            "high_neighbor_churn_rate": 0.50,
            "high_provider_switch_count": 2,
            "low_neighbor_count_threshold": 2,
        }
    },
}


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def utc_now_compact() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def append_only_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    candidate = path.with_name(f"{stem}_{utc_now_compact()}{suffix}")
    counter = 1
    while candidate.exists():
        candidate = path.with_name(f"{stem}_{utc_now_compact()}_{counter}{suffix}")
        counter += 1
    return candidate


def load_config(path: Path | None = None) -> dict[str, Any]:
    config_path = path or repo_root() / "configs" / "pipeline.yaml"
    if not config_path.exists():
        return DEFAULT_CONFIG.copy()
    try:
        import yaml  # type: ignore

        loaded = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        return _deep_merge(DEFAULT_CONFIG.copy(), loaded)
    except Exception:
        return _load_minimal_yaml(config_path)


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            base[key] = _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def _load_minimal_yaml(path: Path) -> dict[str, Any]:
    config = DEFAULT_CONFIG.copy()
    stack: list[tuple[int, dict[str, Any]]] = [(-1, config)]
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].rstrip()
        if not line.strip() or ":" not in line:
            continue
        indent = len(line) - len(line.lstrip(" "))
        key, raw_value = line.strip().split(":", 1)
        raw_value = raw_value.strip()
        while stack and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]
        if not raw_value:
            parent[key] = {}
            stack.append((indent, parent[key]))
        else:
            parent[key] = _coerce_scalar(raw_value)
    return config


def _coerce_scalar(value: str) -> Any:
    value = value.strip().strip('"').strip("'")
    if value.lower() == "true":
        return True
    if value.lower() == "false":
        return False
    try:
        return int(value)
    except ValueError:
        return value


def add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", type=Path, default=repo_root() / "configs" / "pipeline.yaml")
    parser.add_argument("--input", type=Path, default=None)
    parser.add_argument("--run-id", default=None)


def resolve_input(config: dict[str, Any], explicit: Path | None) -> Path:
    if explicit:
        return explicit
    return repo_root() / config["input"]["asn_months_csv"]


def resolve_run_id(config: dict[str, Any], explicit: str | None) -> str:
    return explicit or str(config["run"]["run_id"])


def schema_version(config: dict[str, Any]) -> str:
    return str(config["project"]["schema_version"])


def parser_version(config: dict[str, Any]) -> str:
    return str(config["project"]["parser_version"])


def read_asn_months(path: Path) -> list[dict[str, Any]]:
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != ["asn", "month"]:
            raise ValueError(f"{path} must have exact header: asn,month")
        rows: list[dict[str, Any]] = []
        for line_no, row in enumerate(reader, start=2):
            asn = parse_asn(row.get("asn"), f"{path}:{line_no}")
            month = parse_month(row.get("month"), f"{path}:{line_no}")
            rows.append({"asn": asn, "month": month})
    return rows


def parse_asn(value: Any, context: str = "asn") -> int:
    try:
        asn = int(str(value).strip())
    except Exception as exc:
        raise ValueError(f"{context}: ASN must be an integer") from exc
    if asn <= 0:
        raise ValueError(f"{context}: ASN must be positive")
    return asn


def parse_month(value: Any, context: str = "month") -> str:
    month = str(value or "").strip()
    if not MONTH_RE.match(month):
        raise ValueError(f"{context}: month must use YYYY-MM")
    year, month_num = month.split("-")
    if not 1 <= int(month_num) <= 12:
        raise ValueError(f"{context}: month must use a valid calendar month")
    return f"{int(year):04d}-{int(month_num):02d}"


def month_window(month: str) -> tuple[str, str]:
    year, month_num = [int(part) for part in month.split("-")]
    last_day = calendar.monthrange(year, month_num)[1]
    return (
        f"{year:04d}-{month_num:02d}-01T00:00:00Z",
        f"{year:04d}-{month_num:02d}-{last_day:02d}T23:59:59Z",
    )


def ensure_dirs(paths: Iterable[Path]) -> None:
    for path in paths:
        path.mkdir(parents=True, exist_ok=True)


def relative_to_root(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(repo_root()))
    except ValueError:
        return str(path)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_table(rows: list[dict[str, Any]], csv_path: Path, parquet_path: Path | None = None) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        csv_path.write_text("", encoding="utf-8")
    else:
        fieldnames = list(rows[0].keys())
        with csv_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow({key: _csv_value(value) for key, value in row.items()})
    if parquet_path is not None:
        try:
            import pandas as pd  # type: ignore

            parquet_path.parent.mkdir(parents=True, exist_ok=True)
            pd.DataFrame(rows).to_parquet(parquet_path, index=False)
        except Exception:
            # CSV remains the required fallback artifact when optional parquet deps are absent.
            pass


def read_table(csv_path: Path, parquet_path: Path | None = None) -> list[dict[str, Any]]:
    if parquet_path and parquet_path.exists():
        try:
            import pandas as pd  # type: ignore

            df = pd.read_parquet(parquet_path)
            return json.loads(df.to_json(orient="records"))
        except Exception:
            pass
    if not csv_path.exists() or csv_path.stat().st_size == 0:
        return []
    with csv_path.open(newline="", encoding="utf-8") as f:
        return [dict(row) for row in csv.DictReader(f)]


def _csv_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return value


def as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "y"}:
        return True
    if text in {"false", "0", "no", "n", ""}:
        return False
    raise ValueError(f"Invalid boolean value: {value!r}")


def as_int(value: Any, default: int = 0) -> int:
    if value is None or value == "":
        return default
    return int(value)


def as_float(value: Any, default: float = 0.0) -> float:
    if value is None or value == "":
        return default
    return float(value)


def normalize_country(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().upper()
    if not text:
        return None
    return text if COUNTRY_RE.match(text) else text


def clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text or None

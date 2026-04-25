#!/usr/bin/env python3
"""Download monthly NRO/RIR delegated stats snapshots.

The RIPE NCC mirror publishes NRO-combined delegated statistics under
``pub/stats/ripencc/nro-stats/YYYYMMDD``.  One month-end snapshot is enough for
the raw registry baseline use case here because the file already contains the
five RIR views in a single exchange-format file.
"""

from __future__ import annotations

import argparse
import calendar
import csv
import gzip
import shutil
import sys
import tempfile
from datetime import date
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from pipeline_utils import ensure_dirs, load_config, relative_to_root, sha256_file, utc_now, write_json


BASE_URL = "https://ftp.ripe.net/pub/stats/ripencc/nro-stats"
USER_AGENT = "asn-mismatch-pipeline/0.1 (+monthly rir delegated snapshots)"
SOURCE_CANDIDATES = ("nro-delegated-stats", "combined-stat")


def last_completed_month(today: date) -> str:
    year = today.year
    month = today.month - 1
    if month == 0:
        year -= 1
        month = 12
    return f"{year:04d}-{month:02d}"


def month_sequence(end_month: str, count: int) -> list[str]:
    year, month = [int(part) for part in end_month.split("-")]
    months: list[str] = []
    for _ in range(count):
        months.append(f"{year:04d}-{month:02d}")
        month -= 1
        if month == 0:
            year -= 1
            month = 12
    return list(reversed(months))


def month_end_yyyymmdd(month: str) -> str:
    year, month_num = [int(part) for part in month.split("-")]
    day = calendar.monthrange(year, month_num)[1]
    return f"{year:04d}{month_num:02d}{day:02d}"


def source_url(snapshot_date: str, source_name: str) -> str:
    return f"{BASE_URL}/{snapshot_date}/{source_name}"


def fetch_to_path(url: str, path: Path, timeout: int) -> int:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=timeout) as response:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as f:
            shutil.copyfileobj(response, f, length=1024 * 1024)
        return int(response.headers.get("Content-Length") or path.stat().st_size)


def try_download(snapshot_date: str, tmp_path: Path, timeout: int) -> tuple[str, str, int]:
    errors: list[str] = []
    for source_name in SOURCE_CANDIDATES:
        url = source_url(snapshot_date, source_name)
        try:
            size = fetch_to_path(url, tmp_path, timeout)
            return source_name, url, size
        except HTTPError as exc:
            if tmp_path.exists():
                tmp_path.unlink()
            errors.append(f"{source_name}: HTTP {exc.code}")
        except (URLError, TimeoutError, OSError) as exc:
            if tmp_path.exists():
                tmp_path.unlink()
            errors.append(f"{source_name}: {exc}")
    raise RuntimeError("; ".join(errors))


def gzip_file(src: Path, dst: Path) -> None:
    with src.open("rb") as f_in, gzip.open(dst, "wb", compresslevel=6) as f_out:
        shutil.copyfileobj(f_in, f_out, length=1024 * 1024)


def count_data_lines(path: Path) -> int:
    count = 0
    with path.open("rb") as f:
        for line in f:
            if line.strip():
                count += 1
    return count


def write_index(path: Path, rows: list[dict[str, str | int]]) -> None:
    fieldnames = [
        "month",
        "snapshot_date",
        "source_name",
        "source_url",
        "raw_evidence_path",
        "raw_evidence_sha256",
        "bytes",
        "line_count",
        "status",
        "fetched_at",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Download monthly NRO/RIR delegated stats snapshots.")
    parser.add_argument("--config", type=Path, default=Path("configs/pipeline.yaml"))
    parser.add_argument("--months", type=int, default=60)
    parser.add_argument("--end-month", default=last_completed_month(date.today()), help="Inclusive YYYY-MM month.")
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--timeout-sec", type=int, default=120)
    parser.add_argument("--compress", action="store_true", help="Store monthly files as local .gz files.")
    args = parser.parse_args()

    if args.months <= 0:
        raise ValueError("--months must be positive")

    config = load_config(args.config)
    output_dir = args.output_dir or Path(config["paths"]["raw_root"]) / "registry" / "delegated_monthly"
    ensure_dirs([output_dir])
    output_dir = output_dir.resolve()

    rows: list[dict[str, str | int]] = []
    errors: list[str] = []
    for month in month_sequence(args.end_month, args.months):
        snapshot_date = month_end_yyyymmdd(month)
        suffix = ".txt.gz" if args.compress else ".txt"
        final_path = output_dir / f"nro_delegated_stats_{month}_{snapshot_date}{suffix}"
        if final_path.exists():
            status = "skipped_existing"
            source_name = "unknown_existing"
            url = ""
            line_count = 0
            bytes_written = final_path.stat().st_size
        else:
            with tempfile.TemporaryDirectory(dir=output_dir) as tmp_dir:
                tmp_path = Path(tmp_dir) / f"{snapshot_date}.download"
                try:
                    source_name, url, _source_size = try_download(snapshot_date, tmp_path, args.timeout_sec)
                    line_count = count_data_lines(tmp_path)
                    if args.compress:
                        gzip_file(tmp_path, final_path)
                    else:
                        tmp_path.replace(final_path)
                    bytes_written = final_path.stat().st_size
                    status = "ok"
                except Exception as exc:
                    errors.append(f"{month} {snapshot_date}: {exc}")
                    print(f"[ERROR] {month} {snapshot_date}: {exc}", file=sys.stderr)
                    continue

        rows.append(
            {
                "month": month,
                "snapshot_date": snapshot_date,
                "source_name": source_name,
                "source_url": url,
                "raw_evidence_path": relative_to_root(final_path),
                "raw_evidence_sha256": sha256_file(final_path),
                "bytes": bytes_written,
                "line_count": line_count,
                "status": status,
                "fetched_at": utc_now(),
            }
        )
        print(f"[{status}] {month} -> {relative_to_root(final_path)}")

    index_path = output_dir / "index.csv"
    write_index(index_path, rows)
    log_path = output_dir / f"download_log_{utc_now().replace(':', '').replace('-', '')}.json"
    write_json(
        log_path,
        {
            "fetched_at": utc_now(),
            "source_base_url": BASE_URL,
            "months_requested": args.months,
            "months_saved": len(rows),
            "end_month": args.end_month,
            "output_dir": relative_to_root(output_dir),
            "index_path": relative_to_root(index_path),
            "errors": errors,
        },
    )
    print(f"saved {len(rows)} monthly delegated snapshots; index={relative_to_root(index_path)}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Batch precompute monthly ASN prefix inventories from local bviews.

This script is meant for long-running monthly cache builds. It reuses the raw
writer from ``collect_prefixes.py`` but replaces the single-thread parser with a
producer/worker pipeline so one local month-end bview can be parsed by multiple
threads before writing per-ASN raw evidence.
"""

from __future__ import annotations

import argparse
import queue
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from collect_prefixes import (
    discover_bview,
    load_entity_index,
    parse_mrt_line,
    resolve_months,
    write_month_manifest,
    write_raw_records,
)
from pipeline_utils import (
    add_common_args,
    load_config,
    relative_to_root,
    resolve_input,
    resolve_run_id,
    sha256_file,
)


@dataclass
class WorkerStats:
    total_lines: int = 0
    parsed_lines: int = 0
    matched_prefix_lines: int = 0
    invalid_lines: int = 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Batch precompute monthly ASN prefix inventories from local bviews.")
    add_common_args(parser)
    parser.add_argument("--country", default=None, help="Country code filter from as_entity.csv. Default comes from config.")
    parser.add_argument("--month", action="append", default=None, help="Analysis month YYYY-MM. Can be passed multiple times.")
    parser.add_argument("--pilot-limit", type=int, default=None, help="Optional top-N ASN subset by global_rank.")
    parser.add_argument("--threads", type=int, default=8, help="Worker thread count for line parsing.")
    parser.add_argument("--chunk-lines", type=int, default=50000, help="Producer batch size before handing work to a worker.")
    parser.add_argument("--max-lines", type=int, default=None, help="Optional line cap for smoke tests; omit in full runs.")
    parser.add_argument("--entity-csv", type=Path, default=None, help="Override as_entity.csv source path.")
    parser.add_argument("--bview-root", type=Path, default=None, help="Override local bview root.")
    parser.add_argument("--raw-dir", type=Path, default=None, help="Override raw output root.")
    parser.add_argument("--dump-dir", type=Path, default=None, help="Override local decompressed .data cache root.")
    parser.add_argument("--force-prepare", action="store_true", help="Rebuild the local .data dump even if it already exists.")
    parser.add_argument("--stage-after", action="store_true", help="Run stage_prefixes.py after the raw batch finishes.")
    return parser.parse_args(argv)


def _new_bucket() -> dict[str, set[str]]:
    return {"v4": set(), "v6": set()}


def dump_path_for(bview_path: Path, dump_root: Path) -> Path:
    month_dir = bview_path.parent.name
    collector = bview_path.parent.parent.name
    return dump_root / collector / month_dir / f"{bview_path.stem}.data"


def prepare_text_dump(
    bgpdump_bin: str,
    bview_path: Path,
    dump_root: Path,
    force_prepare: bool = False,
) -> Path:
    dump_path = dump_path_for(bview_path, dump_root)
    if dump_path.exists() and dump_path.stat().st_size > 0 and not force_prepare:
        print(f"[info] reuse_dump path={dump_path}", flush=True)
        return dump_path

    dump_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = dump_path.with_suffix(".data.part")
    if tmp_path.exists():
        tmp_path.unlink()

    print(f"[info] prepare_dump_start src={bview_path} dst={dump_path}", flush=True)
    with tmp_path.open("w", encoding="utf-8") as output:
        process = subprocess.run(
            [bgpdump_bin, "-m", str(bview_path)],
            stdout=output,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    if process.returncode != 0:
        if tmp_path.exists():
            tmp_path.unlink()
        raise RuntimeError(f"bgpdump failed while preparing dump for {bview_path} with exit code {process.returncode}")

    if not tmp_path.exists():
        if dump_path.exists() and dump_path.stat().st_size > 0:
            print(f"[info] prepare_dump_reuse_after_race path={dump_path}", flush=True)
            return dump_path
        raise FileNotFoundError(f"prepared temp dump missing: {tmp_path}")

    tmp_path.replace(dump_path)
    print(f"[info] prepare_dump_done path={dump_path}", flush=True)
    return dump_path


def scan_bview_file_threaded(
    dump_path: Path,
    target_asns: set[int],
    threads: int,
    chunk_lines: int,
    max_lines: int | None = None,
    progress_label: str | None = None,
) -> tuple[dict[int, dict[str, set[str]]], dict[str, int]]:
    task_queue: queue.Queue[list[str] | None] = queue.Queue(maxsize=max(threads * 2, 4))
    result_queue: queue.Queue[tuple[dict[int, dict[str, set[str]]], WorkerStats]] = queue.Queue()

    def worker() -> None:
        while True:
            batch = task_queue.get()
            if batch is None:
                task_queue.task_done()
                return
            local_results: dict[int, dict[str, set[str]]] = {}
            local_stats = WorkerStats()
            for line in batch:
                local_stats.total_lines += 1
                parsed = parse_mrt_line(line)
                if parsed is None:
                    local_stats.invalid_lines += 1
                    continue
                origin_asn, prefix = parsed
                local_stats.parsed_lines += 1
                if origin_asn not in target_asns:
                    continue
                bucket = local_results.setdefault(origin_asn, _new_bucket())
                family = "v6" if ":" in prefix else "v4"
                bucket[family].add(prefix)
                local_stats.matched_prefix_lines += 1
            result_queue.put((local_results, local_stats))
            task_queue.task_done()

    workers = [threading.Thread(target=worker, daemon=True) for _ in range(max(1, threads))]
    for thread in workers:
        thread.start()

    dispatched_batches = 0
    batch: list[str] = []
    capped = False
    lines_read = 0
    with dump_path.open("r", encoding="utf-8", errors="replace") as source:
        for line in source:
            batch.append(line)
            lines_read += 1
            if lines_read % 1_000_000 == 0:
                label = f"{progress_label} " if progress_label else ""
                print(
                    f"[progress] {label}parse_read_lines={lines_read} dispatched_batches={dispatched_batches}",
                    flush=True,
                )
            if max_lines is not None and dispatched_batches * max(1, chunk_lines) + len(batch) >= max_lines:
                capped = True
            if len(batch) >= max(1, chunk_lines):
                task_queue.put(batch)
                dispatched_batches += 1
                batch = []
            if capped:
                break
    if batch:
        task_queue.put(batch)
        dispatched_batches += 1

    for _ in workers:
        task_queue.put(None)
    task_queue.join()

    merged_results = {asn: _new_bucket() for asn in target_asns}
    stats = WorkerStats()
    for merged_batches in range(1, dispatched_batches + 1):
        local_results, local_stats = result_queue.get()
        stats.total_lines += local_stats.total_lines
        stats.parsed_lines += local_stats.parsed_lines
        stats.matched_prefix_lines += local_stats.matched_prefix_lines
        stats.invalid_lines += local_stats.invalid_lines
        for asn, bucket in local_results.items():
            merged = merged_results[asn]
            merged["v4"].update(bucket["v4"])
            merged["v6"].update(bucket["v6"])
        if merged_batches % 100 == 0 or merged_batches == dispatched_batches:
            label = f"{progress_label} " if progress_label else ""
            print(
                f"[progress] {label}parse_merged_batches={merged_batches}/{dispatched_batches} "
                f"matched_prefix_lines={stats.matched_prefix_lines}",
                flush=True,
            )

    return merged_results, {
        "total_lines": stats.total_lines,
        "parsed_lines": stats.parsed_lines,
        "matched_prefix_lines": stats.matched_prefix_lines,
        "invalid_lines": stats.invalid_lines,
    }


def maybe_stage(
    month: str,
    country: str,
    run_id: str,
    config_path: Path,
    cwd: Path,
) -> None:
    command = [
        sys.executable,
        str(cwd / "scripts" / "stage_prefixes.py"),
        "--config",
        str(config_path),
        "--run-id",
        run_id,
        "--month",
        month,
        "--country",
        country,
    ]
    subprocess.run(command, cwd=str(cwd), check=True)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    config = load_config(args.config)
    config_path = args.config if args.config.is_absolute() else Path.cwd() / args.config
    run_id = resolve_run_id(config, args.run_id)
    prefix_config = config.get("sources", {}).get("prefixes", {})
    as_entity_config = prefix_config.get("as_entity", {})
    bview_config = prefix_config.get("local_bview", {})

    country = str(args.country or as_entity_config.get("default_country") or "IR").upper()
    entity_path = args.entity_csv or Path(as_entity_config.get("source_path", "/home/experiment/info/as_entity.csv"))
    bview_root = args.bview_root or Path(bview_config.get("root", "/home/bgpdata/data/ripe/rrc25"))
    bgpdump_bin = str(bview_config.get("bgpdump_bin", "/usr/bin/bgpdump"))
    raw_root = args.raw_dir or Path(config["paths"]["raw_root"])
    dump_root = args.dump_dir or (Path(config["paths"]["raw_root"]) / "prefixes" / "decompressed")
    input_path = resolve_input(config, args.input) if (args.input or args.month is None) else None

    cwd = Path.cwd()
    entity_path = entity_path if entity_path.is_absolute() else cwd / entity_path
    bview_root = bview_root if bview_root.is_absolute() else cwd / bview_root
    raw_root = raw_root if raw_root.is_absolute() else cwd / raw_root
    dump_root = dump_root if dump_root.is_absolute() else cwd / dump_root
    if input_path is not None and not input_path.is_absolute():
        input_path = cwd / input_path

    months = resolve_months(args, input_path)
    entity_index = load_entity_index(entity_path, country, pilot_limit=args.pilot_limit)
    if not entity_index:
        raise ValueError(f"no ASN rows matched country={country} in {entity_path}")
    entity_sha256 = sha256_file(entity_path)
    target_asns = set(entity_index)

    print(f"[info] country={country} matched_asns={len(entity_index)} months={','.join(months)} threads={args.threads}", flush=True)
    print(f"[info] entity_csv={entity_path}", flush=True)

    for month in months:
        bview_path = discover_bview(month, bview_root)
        print(f"[info] month={month} bview={bview_path}", flush=True)
        bview_sha256 = sha256_file(bview_path)
        dump_path = prepare_text_dump(
            bgpdump_bin=bgpdump_bin,
            bview_path=bview_path,
            dump_root=dump_root,
            force_prepare=args.force_prepare,
        )
        print(f"[info] month={month} scan_start dump={dump_path}", flush=True)
        scan_results, stats = scan_bview_file_threaded(
            dump_path=dump_path,
            target_asns=target_asns,
            threads=args.threads,
            chunk_lines=args.chunk_lines,
            max_lines=args.max_lines,
            progress_label=f"month={month}",
        )
        print(
            f"[info] month={month} scan_done total_lines={stats['total_lines']} "
            f"matched_prefix_lines={stats['matched_prefix_lines']}",
            flush=True,
        )
        written_paths = write_raw_records(
            month=month,
            run_id=run_id,
            country=country,
            entity_index=entity_index,
            entity_path=entity_path,
            entity_sha256=entity_sha256,
            bview_path=bview_path,
            bview_sha256=bview_sha256,
            scan_results=scan_results,
            config=config,
            raw_root=raw_root,
        )
        manifest_path = write_month_manifest(
            month=month,
            run_id=run_id,
            country=country,
            entity_count=len(entity_index),
            entity_path=entity_path,
            entity_sha256=entity_sha256,
            bview_path=bview_path,
            bview_sha256=bview_sha256,
            stats=stats,
            stderr_text="",
            written_paths=written_paths,
            input_path=input_path,
            config=config,
            raw_root=raw_root,
        )
        print(
            f"[info] month={month} raw_done raw_files={len(written_paths)} manifest={relative_to_root(manifest_path)}",
            flush=True,
        )
        if args.stage_after:
            maybe_stage(month=month, country=country, run_id=run_id, config_path=config_path, cwd=cwd)
            print(f"[info] month={month} stage_done", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Check repository hygiene rules that are easy to regress during edits."""

from __future__ import annotations

import subprocess
import sys
import argparse
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

ALLOWED_DOCS_ROOT = {
    "archive",
    "artifacts.md",
    "roadmap.md",
    "runbook.md",
    "schema.md",
    "schemas",
    "status.md",
    "worklog.md",
}

ALLOWED_TRACKED_GENERATED = {
    "data/raw/.gitkeep",
    "data/staging/.gitkeep",
    "data/curated/.gitkeep",
    "reports/.gitkeep",
    "logs/.gitkeep",
}

GENERATED_PREFIXES = (
    "data/raw/",
    "data/staging/",
    "data/curated/",
    "reports/",
    "logs/",
)

CORE_OUTPUT_SUFFIXES = (".csv", ".parquet")


def main() -> int:
    args = parse_args()
    errors: list[str] = []
    check_docs_root(errors)
    check_worklog(errors)
    check_archive_status(errors)
    check_schema_registry(errors)
    check_artifact_registration(errors)
    check_tracked_generated_files(errors)
    if args.require_worklog_change:
        check_worklog_changed(errors, args.require_worklog_change)
    if errors:
        print("repo rules check failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    print("repo rules check passed")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check repository hygiene rules.")
    parser.add_argument(
        "--require-worklog-change",
        metavar="BASE_REF",
        default=None,
        help="Fail if tracked source/docs changes since BASE_REF do not include docs/worklog.md.",
    )
    return parser.parse_args()


def check_docs_root(errors: list[str]) -> None:
    docs = ROOT / "docs"
    if not docs.exists():
        errors.append("missing docs/ directory")
        return
    for child in docs.iterdir():
        if child.name not in ALLOWED_DOCS_ROOT:
            errors.append(
                f"docs/{child.name} is not an allowed top-level docs entry; "
                "use docs/worklog.md, docs/roadmap.md, docs/runbook.md, docs/status.md, docs/schema.md, docs/schemas/, or docs/archive/"
            )


def check_worklog(errors: list[str]) -> None:
    worklog = ROOT / "docs" / "worklog.md"
    if not worklog.exists():
        errors.append("missing docs/worklog.md; every handoff needs a fixed next-entry log")
        return
    text = read_text(worklog)
    required = [
        "状态：active",
        "## 当前接手入口",
        "## 最近一次工作记录",
        "## 下次打开先做什么",
        "## 记录模板",
    ]
    for marker in required:
        if marker not in text:
            errors.append(f"docs/worklog.md must contain `{marker}`")


def check_archive_status(errors: list[str]) -> None:
    archive = ROOT / "docs" / "archive"
    if not archive.exists():
        return
    for path in sorted(archive.iterdir()):
        if path.name == "README.md" or not path.is_file() or path.suffix not in {".md", ".txt"}:
            continue
        text = read_text(path)
        if "状态：archived" not in text[:400] and "状态：archived-source" not in text[:400]:
            errors.append(f"{relative(path)} is archived but lacks 状态：archived or 状态：archived-source near the top")
        if "归档原因" not in text[:600] and path.suffix == ".md":
            errors.append(f"{relative(path)} is archived but lacks 归档原因 near the top")


def check_schema_registry(errors: list[str]) -> None:
    schema_dir = ROOT / "docs" / "schemas"
    readme = schema_dir / "README.md"
    if not schema_dir.exists():
        errors.append("missing docs/schemas/ directory")
        return
    if not readme.exists():
        errors.append("missing docs/schemas/README.md")
        return
    readme_text = read_text(readme)
    for path in sorted(schema_dir.glob("*.md")):
        if path.name == "README.md":
            continue
        if path.name not in readme_text:
            errors.append(f"{relative(path)} is not registered in docs/schemas/README.md")
    schema_summary = ROOT / "docs" / "schema.md"
    if schema_summary.exists() and "docs/schemas/" not in read_text(schema_summary):
        errors.append("docs/schema.md must point readers to docs/schemas/")


def check_artifact_registration(errors: list[str]) -> None:
    artifacts = ROOT / "docs" / "artifacts.md"
    if not artifacts.exists():
        errors.append("missing docs/artifacts.md")
        return
    text = read_text(artifacts)
    for base in (ROOT / "data" / "staging", ROOT / "data" / "curated"):
        if not base.exists():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file() or path.suffix not in CORE_OUTPUT_SUFFIXES:
                continue
            rel = relative(path)
            if rel not in text:
                errors.append(f"{rel} exists under data/staging or data/curated but is not registered in docs/artifacts.md")


def check_tracked_generated_files(errors: list[str]) -> None:
    tracked = git_lines(["git", "ls-files"])
    for rel in tracked:
        if rel in ALLOWED_TRACKED_GENERATED:
            continue
        if rel.startswith(GENERATED_PREFIXES):
            errors.append(f"{rel} is a generated artifact tracked by Git; keep generated data/reports/logs out of Git")


def check_worklog_changed(errors: list[str], base_ref: str) -> None:
    changed = git_lines(["git", "diff", "--name-only", f"{base_ref}...HEAD"])
    if not changed:
        return
    meaningful = [
        path
        for path in changed
        if not path.startswith(GENERATED_PREFIXES)
        and path != "docs/worklog.md"
        and not path.startswith(".git")
    ]
    if meaningful and "docs/worklog.md" not in changed:
        errors.append(
            "docs/worklog.md must be updated when changing source, docs, tests, configs, or CI files; "
            f"changed_without_worklog={', '.join(meaningful[:8])}"
        )


def git_lines(cmd: list[str]) -> list[str]:
    try:
        result = subprocess.run(cmd, cwd=ROOT, check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def relative(path: Path) -> str:
    return str(path.relative_to(ROOT))


if __name__ == "__main__":
    sys.exit(main())

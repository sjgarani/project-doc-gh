#!/usr/bin/env python3
"""
doc2gh CLI — Document lifecycle, status, and GitHub metadata management tool.

This tool manages the dedicated management areas of ADRs, RFCs, and Specs
(both the managed YAML frontmatter header and the read-only Document Management
Markdown block). Do not edit those managed sections manually.
"""

from __future__ import annotations

import argparse
from datetime import date
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any, Dict, List, Optional, Set, Tuple

DOC_CONFIG = {
    "adr": {
        "dir": "adrs",
        "prefix": "ADR",
        "type_label": "ADR",
        "default_status": "proposed",
        "valid_statuses": ["proposed", "accepted", "deprecated", "superseded"],
    },
    "rfc": {
        "dir": "rfcs",
        "prefix": "RFC",
        "type_label": "RFC",
        "default_status": "draft",
        "valid_statuses": ["draft", "review", "approved", "rejected", "implemented"],
    },
    "spec": {
        "dir": "specs",
        "prefix": "SPEC",
        "type_label": "SPEC",
        "default_status": "draft",
        "valid_statuses": ["draft", "ready", "in-progress", "done", "archived"],
    },
}

DIR_TO_TYPE = {cfg["dir"]: doc_type for doc_type, cfg in DOC_CONFIG.items()}

SUPPORTED_DEFAULT_BRANCHES = ("main", "master")

MGMT_START_MARKER = (
    "<!-- DOC2GH:MANAGEMENT:START - DO NOT EDIT THIS SECTION MANUALLY. "
    "Use `python3 tools/doc2gh.py` to manage status and GitHub links. -->"
)
MGMT_END_MARKER = "<!-- DOC2GH:MANAGEMENT:END -->"

MGMT_BLOCK_REGEX = re.compile(
    r"<!-- DOC2GH:MANAGEMENT:START[^>]*-->.*?<!-- DOC2GH:MANAGEMENT:END -->",
    re.DOTALL,
)

ISSUE_MGMT_START_MARKER = "<!-- DOC2GH:ISSUE:START -->"
ISSUE_MGMT_END_MARKER = "<!-- DOC2GH:ISSUE:END -->"

ISSUE_MGMT_BLOCK_REGEX = re.compile(
    r"<!-- DOC2GH:ISSUE:START -->.*?<!-- DOC2GH:ISSUE:END -->",
    re.DOTALL,
)

LEGACY_ISSUE_MGMT_REGEX = re.compile(
    r"### Document Tracked by doc2gh\n.*?> This Issue is automatically synchronized from the repository's doc2gh management metadata\.",
    re.DOTALL,
)

FRONTMATTER_REGEX = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)

GITHUB_REMOTE_REGEX = re.compile(
    r"^(?:https?://(?:[^@/]+@)?github\.com/|ssh://(?:[^@/]+@)?github\.com/|[^@/\s]+@github\.com:)([^/\s]+)/([^/\s]+?)(?:\.git)?/?$"
)


def _has_doc2gh_layout(directory: Path) -> bool:
    if not directory.is_dir():
        return False
    return any((directory / name).exists() for name in ("adrs", "rfcs", "specs", "workflows"))


def get_base_dir(custom_root: Optional[str] = None) -> Path:
    if custom_root:
        return Path(custom_root).resolve()
    script_base = Path(__file__).resolve().parent.parent
    if _has_doc2gh_layout(script_base):
        return script_base
    for sub in ("doc", "docs"):
        candidate = script_base / sub
        if _has_doc2gh_layout(candidate):
            return candidate.resolve()
    return script_base


def get_repo_root(base_dir: Path, custom_repo_root: Optional[str] = None) -> Path:
    if custom_repo_root:
        return Path(custom_repo_root).resolve()
    if (base_dir / ".git").exists():
        return base_dir
    if base_dir.name in ("doc", "docs"):
        return base_dir.parent.resolve()
    for candidate in base_dir.parents:
        if (candidate / ".git").exists():
            return candidate
    return base_dir


def get_doc_roots(
    base_dir: Path, repo_root: Path, explicit_root: Optional[str] = None
) -> List[Path]:
    roots = [base_dir]
    if not explicit_root and base_dir == repo_root:
        for sub in ("doc", "docs"):
            sub_path = (repo_root / sub).resolve()
            if sub_path.is_dir() and any(
                (sub_path / cfg["dir"]).is_dir() for cfg in DOC_CONFIG.values()
            ):
                if sub_path not in roots:
                    roots.append(sub_path)
    return roots


DEFAULT_LABELS: List[Tuple[str, str, str]] = [
    ("adr", "0E8A16", "Architecture Decision Record managed by doc2gh"),
    ("rfc", "1D76DB", "Request for Comments managed by doc2gh"),
    ("spec", "5319E7", "Technical & Functional Specification managed by doc2gh"),
    ("status:proposed", "FBCA04", "Document status: proposed"),
    ("status:accepted", "0E8A16", "Document status: accepted"),
    ("status:deprecated", "D93F0B", "Document status: deprecated"),
    ("status:superseded", "BFDADC", "Document status: superseded"),
    ("status:draft", "EDEDED", "Document status: draft"),
    ("status:review", "FBCA04", "Document status: review"),
    ("status:approved", "0E8A16", "Document status: approved"),
    ("status:rejected", "B60205", "Document status: rejected"),
    ("status:implemented", "1D76DB", "Document status: implemented"),
    ("status:ready", "0052CC", "Document status: ready"),
    ("status:in-progress", "C2E0C6", "Document status: in-progress"),
    ("status:done", "0E8A16", "Document status: done"),
    ("status:archived", "D4C5F9", "Document status: archived"),
]


def slugify(text: str) -> str:
    slug = text.lower().strip()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"[\s_-]+", "-", slug)
    return slug.strip("-") or "untitled"


def parse_yaml_scalar(raw_val: str) -> str:
    raw_val = raw_val.strip()
    if not raw_val:
        return ""
    if raw_val.startswith('"'):
        m = re.match(r'^"((?:[^"\\]|\\.)*)"', raw_val)
        if m:
            return m.group(1).replace('\\"', '"')
    if raw_val.startswith("'"):
        m = re.match(r"^'([^']*)'", raw_val)
        if m:
            return m.group(1)
    return raw_val.split("#")[0].strip()


def parse_frontmatter(content: str) -> Tuple[Optional[Dict[str, str]], Optional[str]]:
    match = FRONTMATTER_REGEX.match(content)
    if not match:
        return None, None
    raw_fm = match.group(1)
    fields: Dict[str, str] = {}
    for line in raw_fm.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        m = re.match(r"^([a-zA-Z0-9_]+):\s*(.*)$", stripped)
        if m:
            key = m.group(1)
            fields[key] = parse_yaml_scalar(m.group(2))
    return fields, raw_fm


def build_management_section(
    doc_id: str,
    doc_type: str,
    status: str,
    created_at: str,
    updated_at: str,
    github_issue: str,
    github_pr: str,
    superseded_by: str = "",
) -> str:
    cfg = DOC_CONFIG[doc_type]
    issue_display = github_issue if github_issue else "_None_"
    pr_display = github_pr if github_pr else "_None_"
    lines = [
        MGMT_START_MARKER,
        "## Document Management (Managed by doc2gh)",
        "",
        "> [!WARNING]",
        "> **Do not edit this section or the managed frontmatter fields manually.**",
        "> All status transitions and GitHub tracking links must be updated via `python3 tools/doc2gh.py`.",
        "",
        "| Field | Value |",
        "| :--- | :--- |",
        f"| **Document ID** | `{doc_id}` |",
        f"| **Type** | `{cfg['type_label']}` |",
        f"| **Status** | `{status}` |",
        f"| **Created At** | `{created_at}` |",
        f"| **Updated At** | `{updated_at}` |",
        f"| **GitHub Issue** | {issue_display} |",
        f"| **GitHub PR** | {pr_display} |",
    ]
    if doc_type == "adr":
        sup_display = f"`{superseded_by}`" if superseded_by else "_None_"
        lines.append(f"| **Superseded By** | {sup_display} |")
    lines.append(MGMT_END_MARKER)
    return "\n".join(lines)


def format_yaml_field(key: str, val: str) -> str:
    if key == "title" or val == "" or ":" in val or "#" in val or " " in val:
        escaped = val.replace('"', '\\"')
        return f'{key}: "{escaped}"'
    return f"{key}: {val}"


def update_frontmatter_fields(raw_fm: str, updates: Dict[str, str]) -> str:
    lines = raw_fm.splitlines()
    updated_keys = set()
    new_lines = []
    for line in lines:
        m = re.match(r"^(\s*[a-zA-Z0-9_]+):\s*(.*)$", line)
        if m:
            key = m.group(1).strip()
            if key in updates:
                new_lines.append(format_yaml_field(key, updates[key]))
                updated_keys.add(key)
                continue
        new_lines.append(line)

    for key, val in updates.items():
        if key not in updated_keys:
            new_lines.append(format_yaml_field(key, val))

    return "\n".join(new_lines)


def detect_doc_type(filepath: Path, fields: Optional[Dict[str, str]] = None) -> Optional[str]:
    if fields and fields.get("type") in DOC_CONFIG:
        return fields["type"]
    parent_name = filepath.parent.name
    if parent_name in DIR_TO_TYPE:
        return DIR_TO_TYPE[parent_name]
    if fields and fields.get("id"):
        prefix = fields["id"].split("-")[0].upper()
        for dt, cfg in DOC_CONFIG.items():
            if cfg["prefix"] == prefix:
                return dt
    return None


def next_sequence_number(doc_dir: Path) -> int:
    max_num = 0
    if not doc_dir.exists():
        return 1
    for f in doc_dir.glob("*.md"):
        m = re.match(r"^(\d{4})-", f.name)
        if m:
            num = int(m.group(1))
            if num > max_num:
                max_num = num
    return max_num + 1


def resolve_doc_path(base_dir: Path, target: str) -> Path:
    candidate = Path(target)
    if candidate.exists():
        return candidate.resolve()
    rel_candidate = (base_dir / target).resolve()
    if rel_candidate.exists():
        return rel_candidate

    search_roots = [base_dir]
    for sub in ("doc", "docs"):
        sub_dir = base_dir / sub
        if sub_dir.is_dir() and sub_dir not in search_roots:
            search_roots.append(sub_dir)

    id_upper = target.strip().upper()
    for root in search_roots:
        rel_in_root = (root / target).resolve()
        if rel_in_root.exists():
            return rel_in_root
        for cfg in DOC_CONFIG.values():
            folder = root / cfg["dir"]
            if not folder.exists():
                continue
            for md_file in sorted(folder.glob("*.md")):
                if md_file.name in ("README.md", "template.md"):
                    continue
                content = md_file.read_text(encoding="utf-8")
                fields, _ = parse_frontmatter(content)
                if fields and fields.get("id", "").upper() == id_upper:
                    return md_file.resolve()

    raise FileNotFoundError(f"Document not found: '{target}'")


def cmd_new(args: argparse.Namespace) -> int:
    base_dir = get_base_dir(args.root)
    doc_type = args.type.lower()
    cfg = DOC_CONFIG[doc_type]
    doc_dir = base_dir / cfg["dir"]
    template_path = doc_dir / "template.md"

    if not template_path.exists():
        print(f"Error: Template not found at {template_path}", file=sys.stderr)
        return 1

    seq = args.number if args.number is not None else next_sequence_number(doc_dir)
    seq_str = f"{seq:04d}"
    doc_id = f"{cfg['prefix']}-{seq_str}"
    slug = slugify(args.title)
    filename = f"{seq_str}-{slug}.md"
    target_path = doc_dir / filename

    if target_path.exists():
        print(f"Error: Document already exists at {target_path}", file=sys.stderr)
        return 1

    today = date.today().isoformat()
    status = args.status if args.status else cfg["default_status"]
    if status not in cfg["valid_statuses"]:
        print(
            f"Error: Invalid status '{status}' for {doc_type}. "
            f"Valid options: {', '.join(cfg['valid_statuses'])}",
            file=sys.stderr,
        )
        return 1

    content = template_path.read_text(encoding="utf-8")
    fields, raw_fm = parse_frontmatter(content)
    if raw_fm is None:
        print(f"Error: Template {template_path} is missing YAML frontmatter.", file=sys.stderr)
        return 1

    updates = {
        "id": doc_id,
        "type": doc_type,
        "title": args.title,
        "status": status,
        "created_at": today,
        "updated_at": today,
        "github_issue": args.issue or "",
        "github_pr": args.pr or "",
    }
    if doc_type == "adr":
        updates["superseded_by"] = ""

    new_fm = update_frontmatter_fields(raw_fm, updates)
    content = FRONTMATTER_REGEX.sub(f"---\n{new_fm}\n---\n", content, count=1)

    # Replace placeholder heading e.g. "# ADR-0000: ..."
    content = re.sub(
        rf"^#\s+{cfg['prefix']}-\d{{4}}:.*$",
        f"# {doc_id}: {args.title}",
        content,
        count=1,
        flags=re.MULTILINE,
    )

    mgmt_block = build_management_section(
        doc_id=doc_id,
        doc_type=doc_type,
        status=status,
        created_at=today,
        updated_at=today,
        github_issue=args.issue or "",
        github_pr=args.pr or "",
        superseded_by="",
    )

    if MGMT_BLOCK_REGEX.search(content):
        content = MGMT_BLOCK_REGEX.sub(mgmt_block, content, count=1)
    else:
        content = content + "\n\n" + mgmt_block + "\n"

    target_path.write_text(content, encoding="utf-8")
    print(f"Created {doc_id} at {target_path.relative_to(base_dir)}")
    if getattr(args, "sync_github", False):
        return sync_document_to_github(base_dir, target_path)
    return 0


def apply_document_updates(
    doc_path: Path,
    new_status: Optional[str] = None,
    issue: Optional[str] = None,
    pr: Optional[str] = None,
    superseded_by: Optional[str] = None,
    skip_if_unchanged: bool = False,
) -> int:
    content = doc_path.read_text(encoding="utf-8")
    fields, raw_fm = parse_frontmatter(content)
    if fields is None or raw_fm is None:
        print(f"Error: {doc_path} is missing valid YAML frontmatter.", file=sys.stderr)
        return 1

    doc_type = detect_doc_type(doc_path, fields)
    if not doc_type:
        print(f"Error: Could not determine document type for {doc_path}.", file=sys.stderr)
        return 1

    cfg = DOC_CONFIG[doc_type]
    status = new_status if new_status is not None else fields.get("status", cfg["default_status"])
    if status not in cfg["valid_statuses"]:
        print(
            f"Error: Invalid status '{status}' for {doc_type.upper()}. "
            f"Allowed values: {', '.join(cfg['valid_statuses'])}",
            file=sys.stderr,
        )
        return 1

    if doc_type == "adr" and status == "superseded" and not (
        superseded_by or fields.get("superseded_by")
    ):
        print(
            "Error: Marking an ADR as 'superseded' requires --superseded-by <ADR-NNNN>.",
            file=sys.stderr,
        )
        return 1

    today = date.today().isoformat()
    doc_id = fields.get("id", f"{cfg['prefix']}-0000")
    created_at = fields.get("created_at", today)
    if created_at == "YYYY-MM-DD":
        created_at = today
    github_issue = issue if issue is not None else fields.get("github_issue", "")
    github_pr = pr if pr is not None else fields.get("github_pr", "")
    sup_by = (
        superseded_by
        if superseded_by is not None
        else fields.get("superseded_by", "")
    )

    if skip_if_unchanged:
        existing_updated_at = fields.get("updated_at", today)
        expected_existing_block = build_management_section(
            doc_id=doc_id,
            doc_type=doc_type,
            status=status,
            created_at=created_at,
            updated_at=existing_updated_at,
            github_issue=github_issue,
            github_pr=github_pr,
            superseded_by=sup_by,
        )
        mgmt_match = MGMT_BLOCK_REGEX.search(content)
        if (
            fields.get("status") == status
            and fields.get("github_issue", "") == github_issue
            and fields.get("github_pr", "") == github_pr
            and fields.get("superseded_by", "") == sup_by
            and mgmt_match
            and mgmt_match.group(0).strip() == expected_existing_block.strip()
        ):
            print(f"No changes required for {doc_id} ({doc_path.name}); already synchronized.")
            return 0

    updated_at = today

    updates = {
        "id": doc_id,
        "type": doc_type,
        "status": status,
        "created_at": created_at,
        "updated_at": updated_at,
        "github_issue": github_issue,
        "github_pr": github_pr,
    }
    if doc_type == "adr":
        updates["superseded_by"] = sup_by

    new_fm = update_frontmatter_fields(raw_fm, updates)
    content = FRONTMATTER_REGEX.sub(f"---\n{new_fm}\n---\n", content, count=1)

    mgmt_block = build_management_section(
        doc_id=doc_id,
        doc_type=doc_type,
        status=status,
        created_at=created_at,
        updated_at=updated_at,
        github_issue=github_issue,
        github_pr=github_pr,
        superseded_by=sup_by,
    )

    if MGMT_BLOCK_REGEX.search(content):
        content = MGMT_BLOCK_REGEX.sub(mgmt_block, content, count=1)
    else:
        print(
            f"Error: {doc_path} is missing the managed DOC2GH:MANAGEMENT block.",
            file=sys.stderr,
        )
        return 1

    doc_path.write_text(content, encoding="utf-8")
    print(f"Updated {doc_id} ({doc_path.name}) -> status='{status}', issue='{github_issue}', pr='{github_pr}'")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    base_dir = get_base_dir(args.root)
    try:
        doc_path = resolve_doc_path(base_dir, args.document)
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    rc = apply_document_updates(
        doc_path=doc_path,
        new_status=args.status,
        issue=args.issue,
        pr=args.pr,
        superseded_by=args.superseded_by,
    )
    if rc == 0 and getattr(args, "sync_github", False):
        return sync_document_to_github(base_dir, doc_path)
    return rc


def cmd_link(args: argparse.Namespace) -> int:
    base_dir = get_base_dir(args.root)
    try:
        doc_path = resolve_doc_path(base_dir, args.document)
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    rc = apply_document_updates(
        doc_path=doc_path,
        new_status=None,
        issue=args.issue,
        pr=args.pr,
        superseded_by=None,
    )
    if rc == 0 and getattr(args, "sync_github", False):
        return sync_document_to_github(base_dir, doc_path)
    return rc


def validate_single_document(filepath: Path, doc_type: str, is_template: bool = False) -> List[str]:
    errors: List[str] = []
    cfg = DOC_CONFIG[doc_type]
    filename = filepath.name

    if not is_template:
        if not re.match(r"^\d{4}-[a-z0-9-]+\.md$", filename):
            errors.append(
                f"{filepath}: Invalid filename '{filename}'. Expected 'NNNN-kebab-case-title.md'."
            )

    content = filepath.read_text(encoding="utf-8")
    fields, _ = parse_frontmatter(content)
    if fields is None:
        errors.append(f"{filepath}: Missing YAML frontmatter block.")
        return errors

    expected_prefix = cfg["prefix"]
    doc_id = fields.get("id", "")
    if not re.match(rf"^{expected_prefix}-\d{{4}}$", doc_id):
        errors.append(
            f"{filepath}: Invalid 'id' field ('{doc_id}'). Expected '{expected_prefix}-NNNN'."
        )
    elif not is_template:
        file_num = filename.split("-")[0]
        id_num = doc_id.split("-")[1]
        if file_num != id_num:
            errors.append(
                f"{filepath}: Filename prefix '{file_num}' does not match frontmatter id '{doc_id}'."
            )

    fm_type = fields.get("type", "")
    if fm_type != doc_type:
        errors.append(
            f"{filepath}: Invalid or missing 'type' in frontmatter ('{fm_type}'). Expected '{doc_type}'."
        )

    if not fields.get("title"):
        errors.append(f"{filepath}: Required field 'title' is missing or empty.")

    status = fields.get("status", "")
    if status not in cfg["valid_statuses"]:
        errors.append(
            f"{filepath}: Invalid status '{status}'. Valid statuses for {doc_type.upper()}: "
            f"{', '.join(cfg['valid_statuses'])}."
        )

    for date_field in ("created_at", "updated_at"):
        val = fields.get(date_field, "")
        if is_template and val == "YYYY-MM-DD":
            continue
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", val):
            errors.append(
                f"{filepath}: Field '{date_field}' must follow YYYY-MM-DD format (got '{val}')."
            )

    mgmt_match = MGMT_BLOCK_REGEX.search(content)
    if not mgmt_match:
        errors.append(
            f"{filepath}: Missing managed section markers "
            "(<!-- DOC2GH:MANAGEMENT:START ... --> ... <!-- DOC2GH:MANAGEMENT:END -->)."
        )
    else:
        expected_block = build_management_section(
            doc_id=doc_id,
            doc_type=doc_type,
            status=status,
            created_at=fields.get("created_at", ""),
            updated_at=fields.get("updated_at", ""),
            github_issue=fields.get("github_issue", ""),
            github_pr=fields.get("github_pr", ""),
            superseded_by=fields.get("superseded_by", ""),
        )
        actual_block = mgmt_match.group(0).strip()
        if actual_block != expected_block.strip():
            errors.append(
                f"{filepath}: The managed Document Management section is out of sync with "
                "frontmatter or was edited manually. Run `python3 tools/doc2gh.py status` or `link`."
            )

    return errors


def collect_validation_errors(
    base_dir: Path, include_templates: bool = False
) -> Tuple[int, List[str]]:
    errors: List[str] = []
    checked_count = 0
    seen_ids: Dict[str, Path] = {}

    for doc_type, cfg in DOC_CONFIG.items():
        folder = base_dir / cfg["dir"]
        if not folder.exists():
            continue
        for md_file in sorted(folder.glob("*.md")):
            if md_file.name == "README.md":
                continue
            is_template = md_file.name == "template.md"
            if is_template and not include_templates:
                continue
            checked_count += 1
            file_errors = validate_single_document(md_file, doc_type, is_template=is_template)
            errors.extend(file_errors)
            if not is_template and not file_errors:
                fields, _ = parse_frontmatter(md_file.read_text(encoding="utf-8"))
                doc_id = (fields or {}).get("id", "")
                if doc_id:
                    if doc_id in seen_ids:
                        errors.append(
                            f"{md_file}: Duplicate document ID '{doc_id}' (already defined in {seen_ids[doc_id]})."
                        )
                    else:
                        seen_ids[doc_id] = md_file

    return checked_count, errors


def cmd_validate(args: argparse.Namespace) -> int:
    base_dir = get_base_dir(args.root)
    checked_count, errors = collect_validation_errors(
        base_dir, include_templates=args.include_templates
    )

    print(f"Validated {checked_count} document(s) in {base_dir}")
    if errors:
        print("\nValidation failed with the following errors:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    print("All checked documents conform to doc2gh standards.")
    return 0


def list_tracked_documents(
    base_dir: Path,
    filter_type: Optional[str] = None,
    filter_status: Optional[str] = None,
) -> List[Dict[str, str]]:
    items: List[Dict[str, str]] = []
    for doc_type, cfg in DOC_CONFIG.items():
        if filter_type and filter_type.lower() != doc_type:
            continue
        folder = base_dir / cfg["dir"]
        if not folder.exists():
            continue
        for md_file in sorted(folder.glob("*.md")):
            if md_file.name in ("README.md", "template.md"):
                continue
            content = md_file.read_text(encoding="utf-8")
            fields, _ = parse_frontmatter(content)
            if not fields:
                continue
            if filter_status and fields.get("status") != filter_status:
                continue
            items.append(
                {
                    "id": fields.get("id", ""),
                    "type": doc_type,
                    "title": fields.get("title", ""),
                    "status": fields.get("status", ""),
                    "created_at": fields.get("created_at", ""),
                    "updated_at": fields.get("updated_at", ""),
                    "github_issue": fields.get("github_issue", ""),
                    "github_pr": fields.get("github_pr", ""),
                    "path": str(md_file.relative_to(base_dir)),
                    "abs_path": str(md_file.resolve()),
                }
            )
    return items


def cmd_list(args: argparse.Namespace) -> int:
    base_dir = get_base_dir(args.root)
    raw_items = list_tracked_documents(base_dir, filter_type=args.type, filter_status=args.status)
    items = [{k: v for k, v in item.items() if k != "abs_path"} for item in raw_items]

    if args.format == "json":
        print(json.dumps(items, indent=2))
        return 0

    if not items:
        print("No documents found.")
        return 0

    header = f"{'ID':<12} {'TYPE':<6} {'STATUS':<14} {'ISSUE':<10} {'PR':<10} {'TITLE'}"
    print(header)
    print("-" * len(header))
    for item in items:
        print(
            f"{item['id']:<12} {item['type'].upper():<6} {item['status']:<14} "
            f"{(item['github_issue'] or '-'):<10} {(item['github_pr'] or '-'):<10} {item['title']}"
        )
    return 0


def resolve_workflows_dir(base_dir: Path, repo_root: Path) -> Optional[Path]:
    candidates = [base_dir / "workflows"]
    if base_dir == repo_root:
        candidates.extend([repo_root / "doc" / "workflows", repo_root / "docs" / "workflows"])
    for cand in candidates:
        if cand.is_dir() and list(cand.glob("*.yml")):
            return cand
    return base_dir / "workflows"


def setup_workflow_symlinks(
    base_dir: Path,
    repo_root: Path,
    link_mode: str = "files",
    force: bool = False,
    dry_run: bool = False,
) -> Tuple[int, List[str]]:
    workflows_dir = resolve_workflows_dir(base_dir, repo_root)
    if not workflows_dir or not workflows_dir.exists():
        print(f"Error: Workflows directory not found at {base_dir / 'workflows'}", file=sys.stderr)
        return 1, []

    workflow_files = sorted(workflows_dir.glob("*.yml"))
    if not workflow_files:
        print(f"Error: No workflow .yml files found in {workflows_dir}", file=sys.stderr)
        return 1, []

    github_dir = repo_root / ".github"
    target_workflows_dir = github_dir / "workflows"
    created_links: List[str] = []

    if os.path.lexists(github_dir) and not github_dir.is_dir():
        print(
            "Error: Conflict at '.github': path exists as a file/symlink and was preserved.",
            file=sys.stderr,
        )
        return 1, []

    if link_mode == "dir":
        rel_target = os.path.relpath(workflows_dir, github_dir)
        rel_link_display = str(target_workflows_dir.relative_to(repo_root))

        if target_workflows_dir.is_symlink():
            current_target = os.readlink(target_workflows_dir)
            resolves_ok = (
                target_workflows_dir.exists()
                and target_workflows_dir.resolve() == workflows_dir.resolve()
            )
            if current_target == rel_target and resolves_ok:
                for wf_file in workflow_files:
                    linked_wf = target_workflows_dir / wf_file.name
                    if not (linked_wf.exists() and linked_wf.resolve() == wf_file.resolve()):
                        print(
                            f"Error: Workflow '{wf_file.name}' did not resolve through {rel_link_display}.",
                            file=sys.stderr,
                        )
                        return 1, []
                print(
                    f"Workflow directory symlink already up to date: {rel_link_display} -> {rel_target}"
                )
                return 0, [rel_link_display]

            if dry_run:
                print(
                    f"[dry-run] Would repair workflow directory symlink: {rel_link_display} -> {rel_target} "
                    f"(currently '{current_target}')"
                )
                return 0, [rel_link_display]

            target_workflows_dir.unlink()
            os.symlink(rel_target, target_workflows_dir)
            if not (
                target_workflows_dir.is_symlink()
                and os.readlink(target_workflows_dir) == rel_target
                and target_workflows_dir.resolve() == workflows_dir.resolve()
            ):
                print(
                    f"Error: Failed to verify repaired workflow directory symlink {rel_link_display}.",
                    file=sys.stderr,
                )
                return 1, []
            print(f"Repaired workflow directory symlink: {rel_link_display} -> {rel_target}")
            return 0, [rel_link_display]

        if os.path.lexists(target_workflows_dir):
            print(
                f"Error: Conflict at '{rel_link_display}': path exists as a regular file or directory and was preserved.",
                file=sys.stderr,
            )
            return 1, []

        if dry_run:
            print(f"[dry-run] Would symlink directory {rel_link_display} -> {rel_target}")
            return 0, [rel_link_display]

        github_dir.mkdir(parents=True, exist_ok=True)
        os.symlink(rel_target, target_workflows_dir)
        if not (
            target_workflows_dir.is_symlink()
            and os.readlink(target_workflows_dir) == rel_target
            and target_workflows_dir.resolve() == workflows_dir.resolve()
        ):
            print(
                f"Error: Failed to verify created workflow directory symlink {rel_link_display}.",
                file=sys.stderr,
            )
            return 1, []
        print(f"Created workflow directory symlink: {rel_link_display} -> {rel_target}")
        return 0, [rel_link_display]

    # Default: link_mode == "files" (symlinks each *.yml file into .github/workflows/)
    if target_workflows_dir.is_symlink():
        current_dir_target = os.readlink(target_workflows_dir)
        expected_dir_target = os.path.relpath(workflows_dir, github_dir)
        dir_resolves = (
            target_workflows_dir.exists()
            and target_workflows_dir.resolve() == workflows_dir.resolve()
        )
        if current_dir_target == expected_dir_target and dir_resolves and not force:
            rel_link_display = str(target_workflows_dir.relative_to(repo_root))
            print(
                f"Workflow directory is already a valid symlink: {rel_link_display} -> {current_dir_target}"
            )
            return 0, [rel_link_display]
        if dry_run:
            print(
                f"[dry-run] Would replace directory symlink '.github/workflows' (-> '{current_dir_target}') "
                "with relative workflow file symlinks."
            )
        else:
            target_workflows_dir.unlink()
            target_workflows_dir.mkdir(parents=True, exist_ok=True)
    elif os.path.lexists(target_workflows_dir) and not target_workflows_dir.is_dir():
        print(
            "Error: Conflict at '.github/workflows': path exists as a regular file and was preserved.",
            file=sys.stderr,
        )
        return 1, []
    elif not dry_run:
        target_workflows_dir.mkdir(parents=True, exist_ok=True)

    conflicts: List[str] = []
    for wf_file in workflow_files:
        dest_link = target_workflows_dir / wf_file.name
        rel_source = os.path.relpath(wf_file, target_workflows_dir)
        rel_dest_display = str(dest_link.relative_to(repo_root))

        if dest_link.is_symlink():
            current_target = os.readlink(dest_link)
            resolves_ok = dest_link.exists() and dest_link.resolve() == wf_file.resolve()
            if current_target == rel_source and resolves_ok:
                print(f"Workflow symlink already up to date: {rel_dest_display} -> {rel_source}")
                created_links.append(rel_dest_display)
                continue

            if dry_run:
                print(
                    f"[dry-run] Would repair workflow symlink: {rel_dest_display} -> {rel_source} "
                    f"(currently '{current_target}')"
                )
                created_links.append(rel_dest_display)
                continue

            dest_link.unlink()
            os.symlink(rel_source, dest_link)
            if not (
                dest_link.is_symlink()
                and os.readlink(dest_link) == rel_source
                and dest_link.exists()
                and dest_link.resolve() == wf_file.resolve()
            ):
                print(
                    f"Error: Failed to verify repaired workflow symlink '{rel_dest_display}'.",
                    file=sys.stderr,
                )
                conflicts.append(rel_dest_display)
            else:
                print(f"Repaired workflow symlink: {rel_dest_display} -> {rel_source}")
                created_links.append(rel_dest_display)
            continue

        if os.path.lexists(dest_link):
            kind = "directory" if dest_link.is_dir() else "regular file"
            print(
                f"Error: Conflict at '{rel_dest_display}': existing {kind} preserved without overwriting.",
                file=sys.stderr,
            )
            conflicts.append(rel_dest_display)
            continue

        if dry_run:
            print(f"[dry-run] Would create workflow symlink: {rel_dest_display} -> {rel_source}")
            created_links.append(rel_dest_display)
            continue

        os.symlink(rel_source, dest_link)
        if not (
            dest_link.is_symlink()
            and os.readlink(dest_link) == rel_source
            and dest_link.exists()
            and dest_link.resolve() == wf_file.resolve()
        ):
            print(
                f"Error: Failed to verify created workflow symlink '{rel_dest_display}'.",
                file=sys.stderr,
            )
            conflicts.append(rel_dest_display)
        else:
            print(f"Created workflow symlink: {rel_dest_display} -> {rel_source}")
            created_links.append(rel_dest_display)

    if conflicts:
        return 1, created_links
    return 0, created_links


def parse_github_remote_url(remote_url: str) -> Optional[Tuple[str, str]]:
    m = GITHUB_REMOTE_REGEX.match(remote_url.strip())
    if m:
        return m.group(1), m.group(2)
    return None


def resolve_github_target(
    repo_root: Path,
    explicit_repo: Optional[str] = None,
    explicit_owner: Optional[str] = None,
    existing_cfg: Optional[Dict[str, Any]] = None,
) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    """
    Resolve (owner, repo_name, origin_url, error_message).
    Never guesses the owner when remotes are missing, non-GitHub, or ambiguous.
    """
    exp_owner = explicit_owner.strip() if explicit_owner and explicit_owner.strip() else None
    exp_repo: Optional[str] = None

    if explicit_repo and explicit_repo.strip():
        raw_repo = explicit_repo.strip()
        if "/" in raw_repo:
            parts = raw_repo.split("/")
            if len(parts) != 2 or not parts[0].strip() or not parts[1].strip():
                return (
                    None,
                    None,
                    None,
                    f"Error: Invalid --repo value '{raw_repo}'. Expected 'OWNER/REPO'.",
                )
            repo_owner, repo_name = parts[0].strip(), parts[1].strip()
            if exp_owner and exp_owner.lower() != repo_owner.lower():
                return (
                    None,
                    None,
                    None,
                    f"Error: Conflicting options: --owner '{exp_owner}' does not match --repo '{raw_repo}'.",
                )
            exp_owner = repo_owner
            exp_repo = repo_name
        else:
            exp_repo = raw_repo

    origin_url: Optional[str] = None
    try:
        res = subprocess.run(
            ["git", "-C", str(repo_root), "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode == 0 and res.stdout.strip():
            origin_url = res.stdout.strip()
    except FileNotFoundError:
        pass

    if origin_url:
        parsed_origin = parse_github_remote_url(origin_url)
        if parsed_origin is None:
            if exp_owner and exp_repo:
                return (
                    None,
                    None,
                    origin_url,
                    f"Error: Conflicting remote 'origin' ('{origin_url}') is not a GitHub remote matching '{exp_owner}/{exp_repo}'.",
                )
            return (
                None,
                None,
                origin_url,
                f"Error: Configured remote 'origin' ('{origin_url}') is not a GitHub remote. "
                "Configure a GitHub remote or pass --repo OWNER/REPO explicitly.",
            )

        orig_owner, orig_repo = parsed_origin
        if exp_owner and exp_owner.lower() != orig_owner.lower():
            return (
                None,
                None,
                origin_url,
                f"Error: Conflicting remote 'origin' ('{origin_url}' -> {orig_owner}/{orig_repo}) "
                f"does not match target '{exp_owner}/{exp_repo or orig_repo}'.",
            )
        if exp_repo and exp_repo.lower() != orig_repo.lower():
            return (
                None,
                None,
                origin_url,
                f"Error: Conflicting remote 'origin' ('{origin_url}' -> {orig_owner}/{orig_repo}) "
                f"does not match target '{exp_owner or orig_owner}/{exp_repo}'.",
            )
        return exp_owner or orig_owner, exp_repo or orig_repo, origin_url, None

    # No 'origin' remote configured; check if other remotes exist (ambiguous remotes)
    other_remotes: List[str] = []
    try:
        rem_res = subprocess.run(
            ["git", "-C", str(repo_root), "remote"],
            capture_output=True,
            text=True,
            check=False,
        )
        if rem_res.returncode == 0 and rem_res.stdout.strip():
            other_remotes = [
                r.strip() for r in rem_res.stdout.splitlines() if r.strip() and r.strip() != "origin"
            ]
    except FileNotFoundError:
        pass

    if other_remotes and not (exp_owner and exp_repo):
        return (
            None,
            None,
            None,
            f"Error: Ambiguous Git remote(s) without 'origin' ({', '.join(other_remotes)}). "
            "Pass --repo OWNER/REPO explicitly.",
        )

    if exp_owner and exp_repo:
        return exp_owner, exp_repo, None, None
    if exp_owner and not exp_repo:
        return exp_owner, repo_root.name, None, None

    if existing_cfg:
        cfg_repo = (existing_cfg.get("repo") or "").strip()
        cfg_owner = (existing_cfg.get("owner") or "").strip()
        if "/" in cfg_repo:
            c_owner, c_name = cfg_repo.split("/", 1)
            if c_owner.strip() and c_name.strip():
                return c_owner.strip(), c_name.strip(), None, None
        elif cfg_owner and cfg_repo:
            return cfg_owner, cfg_repo, None, None

    return (
        None,
        exp_repo,
        None,
        "Error: Could not determine GitHub owner/repository (no 'origin' remote configured and "
        "no explicit --repo OWNER/REPO provided; owner is never guessed).",
    )


def detect_github_repo(
    repo_root: Path, explicit_repo: Optional[str] = None, explicit_owner: Optional[str] = None
) -> Tuple[Optional[str], Optional[str]]:
    owner, repo, _, _ = resolve_github_target(
        repo_root=repo_root,
        explicit_repo=explicit_repo,
        explicit_owner=explicit_owner,
    )
    return owner, repo


def get_current_branch(repo_root: Path) -> Tuple[Optional[str], Optional[str]]:
    """Return (branch_name, error_message)."""
    try:
        res = subprocess.run(
            ["git", "-C", str(repo_root), "symbolic-ref", "--quiet", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode == 0 and res.stdout.strip():
            branch = res.stdout.strip()
            if branch != "HEAD":
                return branch, None
        elif res.returncode != 0 and (res.stderr.strip() or res.stdout.strip()):
            err_detail = (res.stderr or res.stdout).strip()
            if "detached" in err_detail.lower() or "not a symbolic ref" in err_detail.lower():
                return None, "Error: Repository is in a detached HEAD state (missing active branch)."
    except FileNotFoundError:
        return None, "Error: 'git' executable not found."

    head_file = repo_root / ".git" / "HEAD"
    if head_file.is_file():
        head_text = head_file.read_text(encoding="utf-8").strip()
        if head_text.startswith("ref: refs/heads/"):
            return head_text[len("ref: refs/heads/") :].strip(), None
        return None, "Error: Repository is in a detached HEAD state (missing active branch)."

    return None, "Error: Could not determine active Git branch (missing branch)."


def verify_clean_worktree(repo_root: Path) -> Optional[str]:
    res = subprocess.run(
        ["git", "-C", str(repo_root), "status", "--porcelain"],
        capture_output=True,
        text=True,
        check=False,
    )
    if res.returncode != 0:
        err = (res.stderr or res.stdout).strip()
        return f"Error: Could not inspect Git working tree status: {err}"
    if res.stdout.strip():
        return (
            "Error: Dirty worktree detected (uncommitted changes present). "
            "Commit or stash changes before pushing."
        )
    return None


def confirm_action(auto_confirm: bool, prompt_text: str) -> bool:
    if auto_confirm:
        return True
    try:
        answer = input(prompt_text).strip().lower()
    except EOFError:
        return False
    return answer in ("y", "yes")


def is_supported_branch_for_bootstrap(branch: str) -> bool:
    if branch in SUPPORTED_DEFAULT_BRANCHES:
        return True
    if branch == "devel" or branch.startswith(
        ("feat/", "feature/", "spec/", "rfc/", "adr/", "fix/", "bugfix/", "chore/", "docs/")
    ):
        return True
    return False


def ensure_github_repository_and_remote(
    repo_root: Path,
    owner: str,
    repo_name: str,
    origin_url: Optional[str],
    args: argparse.Namespace,
    completed_actions: List[str],
) -> Tuple[int, str]:
    """
    Verify or create the remote GitHub repository, configure 'origin' if needed,
    and optionally push the current branch safely (never force-pushing).
    Returns (exit_code, resolved_default_branch).
    """
    full_repo = f"{owner}/{repo_name}"
    default_branch = getattr(args, "base_branch", None) or "main"

    if getattr(args, "base_branch", None) and args.base_branch not in SUPPORTED_DEFAULT_BRANCHES:
        print(
            f"Error: Unsupported default branch '{args.base_branch}'. "
            f"Supported default branches are: {', '.join(SUPPORTED_DEFAULT_BRANCHES)}.",
            file=sys.stderr,
        )
        return 1, default_branch

    if args.dry_run:
        if origin_url:
            print(f"[dry-run] Would verify and reuse existing GitHub repository '{full_repo}' (origin: {origin_url})")
        else:
            print(
                f"[dry-run] Would check if GitHub repository '{full_repo}' exists; "
                f"if missing, create '{full_repo}', configure remote 'origin', and push current branch"
            )
        if getattr(args, "push", False):
            print(f"[dry-run] Would push current branch to 'origin' ({full_repo}) without force-pushing")
        return 0, default_branch

    view_res = subprocess.run(
        [
            "gh",
            "repo",
            "view",
            full_repo,
            "--json",
            "name,owner,url,defaultBranchRef,viewerPermission",
        ],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
    )

    if view_res.returncode == 0:
        repo_info: Dict[str, Any] = {}
        if view_res.stdout.strip():
            try:
                parsed = json.loads(view_res.stdout)
                if isinstance(parsed, dict):
                    repo_info = parsed
            except json.JSONDecodeError:
                repo_info = {}

        perm = (repo_info.get("viewerPermission") or "").strip().upper()
        if perm and perm in ("READ", "TRIAGE", "NONE"):
            print(
                f"Error: Insufficient permissions ('{perm}') on repository '{full_repo}'. "
                "Write or admin access is required.",
                file=sys.stderr,
            )
            return 1, default_branch

        default_ref = repo_info.get("defaultBranchRef")
        if isinstance(default_ref, dict) and default_ref.get("name"):
            remote_default = str(default_ref["name"]).strip()
            if remote_default not in SUPPORTED_DEFAULT_BRANCHES:
                print(
                    f"Error: Unsupported default branch '{remote_default}' in '{full_repo}'. "
                    f"Supported default branches are: {', '.join(SUPPORTED_DEFAULT_BRANCHES)}.",
                    file=sys.stderr,
                )
                return 1, remote_default
            default_branch = remote_default

        print(f"Reusing existing GitHub repository '{full_repo}'.")
        completed_actions.append(f"Verified existing GitHub repository '{full_repo}'")

        if not origin_url:
            target_remote_url = repo_info.get("url") or f"https://github.com/{full_repo}.git"
            if not target_remote_url.endswith(".git"):
                target_remote_url = f"{target_remote_url}.git"
            add_rem = subprocess.run(
                ["git", "-C", str(repo_root), "remote", "add", "origin", target_remote_url],
                capture_output=True,
                text=True,
                check=False,
            )
            if add_rem.returncode != 0:
                err = (add_rem.stderr or add_rem.stdout).strip()
                print(f"Error configuring remote 'origin': {err}", file=sys.stderr)
                return 1, default_branch
            completed_actions.append(f"Configured remote 'origin' -> {target_remote_url}")

        if getattr(args, "push", False):
            rc = validate_and_push_branch(
                repo_root=repo_root,
                full_repo=full_repo,
                auto_confirm=getattr(args, "yes", False),
                require_upstream_check=True,
                completed_actions=completed_actions,
            )
            if rc != 0:
                return rc, default_branch

        return 0, default_branch

    # Repository view returned non-zero: check if auth/permission error vs repository not found
    err_output = f"{view_res.stderr or ''}\n{view_res.stdout or ''}".strip()
    lower_err = err_output.lower()
    if any(
        token in lower_err
        for token in (
            "403",
            "forbidden",
            "insufficient",
            "permission",
            "resource not accessible",
            "401",
            "bad credentials",
            "authentication",
        )
    ):
        print(
            f"Error: Authentication or permission failure accessing '{full_repo}': {err_output}",
            file=sys.stderr,
        )
        return 1, default_branch

    # Target GitHub repository does not exist -> preflight local git state before creating/pushing
    branch, branch_err = get_current_branch(repo_root)
    if branch_err or not branch:
        print(branch_err or "Error: Missing active Git branch.", file=sys.stderr)
        return 1, default_branch

    if not is_supported_branch_for_bootstrap(branch):
        print(
            f"Error: Unsupported default branch '{branch}'. "
            f"Supported default branches are: {', '.join(SUPPORTED_DEFAULT_BRANCHES)}.",
            file=sys.stderr,
        )
        return 1, default_branch

    dirty_err = verify_clean_worktree(repo_root)
    if dirty_err:
        print(dirty_err, file=sys.stderr)
        return 1, default_branch

    if not confirm_action(
        getattr(args, "yes", False),
        f"Target GitHub repository '{full_repo}' does not exist. "
        f"Create it, configure remote 'origin', and push branch '{branch}'? [y/N]: ",
    ):
        print(
            f"Error: Creation of remote repository '{full_repo}' and branch push were not confirmed. "
            "Pass --yes to confirm non-interactively.",
            file=sys.stderr,
        )
        return 1, default_branch

    visibility = getattr(args, "visibility", "private") or "private"
    vis_flag = f"--{visibility}"
    create_repo_res = subprocess.run(
        ["gh", "repo", "create", full_repo, vis_flag],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
    )
    if create_repo_res.returncode != 0:
        err = (create_repo_res.stderr or create_repo_res.stdout).strip()
        print(f"Error creating GitHub repository '{full_repo}': {err}", file=sys.stderr)
        return 1, default_branch

    print(f"Created GitHub repository '{full_repo}' ({visibility}).")
    completed_actions.append(f"Created GitHub repository '{full_repo}'")

    if not origin_url:
        remote_url = f"https://github.com/{full_repo}.git"
        add_rem = subprocess.run(
            ["git", "-C", str(repo_root), "remote", "add", "origin", remote_url],
            capture_output=True,
            text=True,
            check=False,
        )
        if add_rem.returncode != 0:
            err = (add_rem.stderr or add_rem.stdout).strip()
            print(f"Error configuring remote 'origin': {err}", file=sys.stderr)
            return 1, default_branch
        print(f"Configured remote 'origin' -> {remote_url}")
        completed_actions.append(f"Configured remote 'origin' -> {remote_url}")

    push_res = subprocess.run(
        ["git", "-C", str(repo_root), "push", "-u", "origin", branch],
        capture_output=True,
        text=True,
        check=False,
    )
    if push_res.returncode != 0:
        err = (push_res.stderr or push_res.stdout).strip()
        print(f"Error pushing branch '{branch}' to 'origin': {err}", file=sys.stderr)
        return 1, default_branch

    print(f"Pushed branch '{branch}' to 'origin' ({full_repo}).")
    completed_actions.append(f"Pushed branch '{branch}' to 'origin'")
    if branch in SUPPORTED_DEFAULT_BRANCHES:
        default_branch = branch
    return 0, default_branch


def validate_and_push_branch(
    repo_root: Path,
    full_repo: str,
    auto_confirm: bool,
    require_upstream_check: bool,
    completed_actions: List[str],
) -> int:
    branch, branch_err = get_current_branch(repo_root)
    if branch_err or not branch:
        print(branch_err or "Error: Missing active Git branch.", file=sys.stderr)
        return 1

    if not is_supported_branch_for_bootstrap(branch):
        print(
            f"Error: Unsupported branch '{branch}'. "
            f"Supported default branches are: {', '.join(SUPPORTED_DEFAULT_BRANCHES)}.",
            file=sys.stderr,
        )
        return 1

    dirty_err = verify_clean_worktree(repo_root)
    if dirty_err:
        print(dirty_err, file=sys.stderr)
        return 1

    if require_upstream_check:
        up_res = subprocess.run(
            [
                "git",
                "-C",
                str(repo_root),
                "rev-parse",
                "--abbrev-ref",
                "--symbolic-full-name",
                "@{u}",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if up_res.returncode != 0 and not auto_confirm:
            if not confirm_action(
                False,
                f"Branch '{branch}' has no upstream tracking branch. Push '{branch}' to 'origin' ({full_repo})? [y/N]: ",
            ):
                print(
                    f"Error: Branch '{branch}' has no upstream branch and push was not confirmed.",
                    file=sys.stderr,
                )
                return 1
        elif not confirm_action(
            auto_confirm,
            f"Push branch '{branch}' to 'origin' ({full_repo})? [y/N]: ",
        ):
            print(f"Error: Push of branch '{branch}' was not confirmed.", file=sys.stderr)
            return 1

    push_res = subprocess.run(
        ["git", "-C", str(repo_root), "push", "-u", "origin", branch],
        capture_output=True,
        text=True,
        check=False,
    )
    if push_res.returncode != 0:
        err = (push_res.stderr or push_res.stdout).strip()
        print(f"Error pushing branch '{branch}' to 'origin': {err}", file=sys.stderr)
        return 1

    print(f"Pushed branch '{branch}' to 'origin' ({full_repo}).")
    completed_actions.append(f"Pushed branch '{branch}' to 'origin'")
    return 0


def collect_tracked_issue_or_pr_urls(base_dir: Path, owner: str, repo_name: str) -> List[str]:
    urls: List[str] = []
    for cfg in DOC_CONFIG.values():
        folder = base_dir / cfg["dir"]
        if not folder.exists():
            continue
        for md_file in sorted(folder.glob("*.md")):
            if md_file.name in ("README.md", "template.md"):
                continue
            content = md_file.read_text(encoding="utf-8")
            fields, _ = parse_frontmatter(content)
            if not fields:
                continue
            for key, kind in (("github_issue", "issues"), ("github_pr", "pull")):
                ref = (fields.get(key) or "").strip()
                if not ref:
                    continue
                if ref.startswith("http://") or ref.startswith("https://"):
                    if ref not in urls:
                        urls.append(ref)
                else:
                    m = re.match(r"^#?(\d+)$", ref)
                    if m:
                        url = f"https://github.com/{owner}/{repo_name}/{kind}/{m.group(1)}"
                        if url not in urls:
                            urls.append(url)
    return urls


def get_existing_project_item_urls(repo_root: Path, owner: str, proj_num: str) -> Set[str]:
    urls: Set[str] = set()
    res = subprocess.run(
        ["gh", "project", "item-list", proj_num, "--owner", owner, "--format", "json"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
    )
    if res.returncode == 0 and res.stdout.strip():
        try:
            data = json.loads(res.stdout)
            items = data.get("items", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
            for item in items:
                if not isinstance(item, dict):
                    continue
                content = item.get("content") or {}
                url = content.get("url") or item.get("url")
                if url:
                    urls.add(str(url).strip())
        except json.JSONDecodeError:
            pass
    return urls


def setup_github_project_and_tools(
    base_dir: Path,
    repo_root: Path,
    owner: Optional[str],
    repo_name: Optional[str],
    project_title: str,
    skip_labels: bool = False,
    dry_run: bool = False,
) -> Tuple[int, Dict[str, Any]]:
    project_meta: Dict[str, Any] = {
        "owner": owner or "",
        "repo": f"{owner}/{repo_name}" if (owner and repo_name) else (repo_name or ""),
        "project_title": project_title,
        "project_number": None,
        "project_id": "",
        "project_url": "",
    }

    if dry_run:
        target_owner = owner or "<owner>"
        target_repo = f"{target_owner}/{repo_name or '<repo>'}"
        print(
            f"[dry-run] Would create/ensure GitHub Project '{project_title}' for owner '{target_owner}' "
            f"(gh project create --owner {target_owner} --title \"{project_title}\" --format json)"
        )
        print(
            f"[dry-run] Would link GitHub Project to repository '{target_repo}' "
            f"(gh project link <number> --owner {target_owner} --repo {target_repo})"
        )
        if not skip_labels:
            print(
                f"[dry-run] Would provision {len(DEFAULT_LABELS)} doc2gh labels (adr, rfc, spec, status:*) "
                f"in repository '{target_repo}'"
            )
        return 0, project_meta

    if not shutil.which("gh"):
        print(
            "Error: GitHub CLI ('gh') is not installed. "
            "Install 'gh' and authenticate, or pass --skip-github.",
            file=sys.stderr,
        )
        return 1, project_meta

    auth_check = subprocess.run(
        ["gh", "auth", "status"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
    )
    if auth_check.returncode != 0:
        err_detail = (auth_check.stderr or auth_check.stdout).strip()
        print(
            f"Error: GitHub CLI ('gh') is not authenticated: {err_detail}\n"
            "Authenticate with:\n"
            "  gh auth login --scopes repo,project,read:org\n"
            "and re-run: python3 tools/doc2gh.py init",
            file=sys.stderr,
        )
        return 1, project_meta

    if not owner:
        print(
            "Error: GitHub owner/organization could not be determined. "
            "Pass --repo OWNER/REPO or --owner OWNER explicitly.",
            file=sys.stderr,
        )
        return 1, project_meta

    # 1. Check if a GitHub Project with this title already exists for the owner
    existing_project: Optional[Dict[str, Any]] = None
    list_res = subprocess.run(
        ["gh", "project", "list", "--owner", owner, "--format", "json"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
    )
    if list_res.returncode != 0:
        err_msg = (list_res.stderr or list_res.stdout).strip()
        lower_err = err_msg.lower()
        if any(
            tok in lower_err
            for tok in ("scope", "permission", "forbidden", "403", "401", "authentication", "unauthorized")
        ):
            print(
                f"Error listing GitHub Projects for '{owner}': {err_msg}\n"
                "Ensure your token has project permissions: gh auth refresh -s project",
                file=sys.stderr,
            )
            return 1, project_meta
    elif list_res.stdout.strip():
        try:
            parsed_list = json.loads(list_res.stdout)
            projects = (
                parsed_list.get("projects", [])
                if isinstance(parsed_list, dict)
                else (parsed_list if isinstance(parsed_list, list) else [])
            )
            for proj in projects:
                if isinstance(proj, dict) and proj.get("title") == project_title:
                    existing_project = proj
                    break
        except json.JSONDecodeError:
            pass

    if existing_project:
        project_meta["project_number"] = existing_project.get("number")
        project_meta["project_id"] = existing_project.get("id", "")
        project_meta["project_url"] = existing_project.get("url", "")
        print(
            f"Found existing GitHub Project #{project_meta['project_number']}: "
            f"'{project_title}' ({project_meta['project_url']})"
        )
    else:
        create_res = subprocess.run(
            [
                "gh",
                "project",
                "create",
                "--owner",
                owner,
                "--title",
                project_title,
                "--format",
                "json",
            ],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=False,
        )
        if create_res.returncode != 0:
            err_msg = create_res.stderr.strip() or create_res.stdout.strip()
            print(
                f"Error creating GitHub Project '{project_title}' for '{owner}': {err_msg}\n"
                "Ensure your token has project permissions: gh auth refresh -s project",
                file=sys.stderr,
            )
            return 1, project_meta

        try:
            created_proj = json.loads(create_res.stdout)
        except json.JSONDecodeError:
            created_proj = {}

        project_meta["project_number"] = created_proj.get("number")
        project_meta["project_id"] = created_proj.get("id", "")
        project_meta["project_url"] = created_proj.get("url", "")
        print(
            f"Created GitHub Project #{project_meta['project_number']}: "
            f"'{project_title}' ({project_meta['project_url']})"
        )

    # 2. Link the GitHub Project to the repository and configure labels if repo_name is known
    if repo_name and project_meta.get("project_number") is not None:
        full_repo = f"{owner}/{repo_name}"
        proj_num = str(project_meta["project_number"])

        link_res = subprocess.run(
            [
                "gh",
                "project",
                "link",
                proj_num,
                "--owner",
                owner,
                "--repo",
                full_repo,
            ],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=False,
        )
        if link_res.returncode == 0:
            print(f"Linked GitHub Project #{proj_num} to repository '{full_repo}'.")
        else:
            link_err = (link_res.stderr or link_res.stdout).strip()
            if "already linked" in link_err.lower():
                print(f"GitHub Project #{proj_num} is already linked to repository '{full_repo}'.")
            elif any(
                tok in link_err.lower()
                for tok in ("permission", "forbidden", "403", "401", "scope", "unauthorized")
            ):
                print(
                    f"Error linking Project #{proj_num} to '{full_repo}': {link_err}",
                    file=sys.stderr,
                )
                return 1, project_meta
            else:
                print(
                    f"Note: Could not link Project #{proj_num} to '{full_repo}': {link_err}",
                    file=sys.stderr,
                )

        if not skip_labels:
            existing_label_names: Set[str] = set()
            lbl_list_res = subprocess.run(
                [
                    "gh",
                    "label",
                    "list",
                    "--repo",
                    full_repo,
                    "--limit",
                    "100",
                    "--json",
                    "name,color,description",
                ],
                cwd=str(repo_root),
                capture_output=True,
                text=True,
                check=False,
            )
            if lbl_list_res.returncode == 0 and lbl_list_res.stdout.strip():
                try:
                    parsed_lbls = json.loads(lbl_list_res.stdout)
                    if isinstance(parsed_lbls, list):
                        for item in parsed_lbls:
                            if isinstance(item, dict) and item.get("name"):
                                existing_label_names.add(str(item["name"]))
                except json.JSONDecodeError:
                    pass

            synced_labels = 0
            created_labels = 0
            for label_name, color, description in DEFAULT_LABELS:
                if label_name in existing_label_names:
                    synced_labels += 1
                    continue
                lbl_res = subprocess.run(
                    [
                        "gh",
                        "label",
                        "create",
                        label_name,
                        "--repo",
                        full_repo,
                        "--color",
                        color,
                        "--description",
                        description,
                        "--force",
                    ],
                    cwd=str(repo_root),
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if lbl_res.returncode == 0:
                    synced_labels += 1
                    created_labels += 1
                else:
                    lbl_err = (lbl_res.stderr or lbl_res.stdout).strip()
                    print(
                        f"Error provisioning label '{label_name}' in '{full_repo}': {lbl_err}",
                        file=sys.stderr,
                    )
                    return 1, project_meta
            print(
                f"Synchronized {synced_labels}/{len(DEFAULT_LABELS)} doc2gh labels in '{full_repo}' "
                f"({created_labels} created/updated)."
            )

    return 0, project_meta


CLOSED_DOCUMENT_STATUSES = {
    "done",
    "archived",
    "rejected",
    "superseded",
    "deprecated",
    "implemented",
}


def build_issue_managed_block(
    doc_id: str,
    doc_type: str,
    status: str,
    updated_at: str,
    github_pr: str,
    rel_doc_path: str,
    cfg_data: Dict[str, Any],
) -> str:
    body_lines = [
        ISSUE_MGMT_START_MARKER,
        "### Document Tracked by doc2gh",
        f"- **Document ID**: `{doc_id}`",
        f"- **Type**: `{doc_type.upper()}`",
        f"- **Status**: `{status}`",
        f"- **Updated At**: `{updated_at}`",
        f"- **Linked PR**: {github_pr or '_None_'}",
    ]
    if cfg_data.get("project_url"):
        proj_label = cfg_data.get("project_title") or f"#{cfg_data.get('project_number')}"
        body_lines.append(f"- **GitHub Project**: [{proj_label}]({cfg_data['project_url']})")
    body_lines.extend(
        [
            f"- **Source File**: `{rel_doc_path}`",
            "",
            "> This Issue is automatically synchronized from the repository's doc2gh management metadata.",
            ISSUE_MGMT_END_MARKER,
        ]
    )
    return "\n".join(body_lines)


def merge_issue_body(existing_body: str, managed_block: str) -> str:
    """Preserve any manual Issue description outside the doc2gh managed block."""
    if not existing_body or not existing_body.strip():
        return managed_block
    if ISSUE_MGMT_BLOCK_REGEX.search(existing_body):
        return ISSUE_MGMT_BLOCK_REGEX.sub(managed_block, existing_body, count=1)
    if LEGACY_ISSUE_MGMT_REGEX.search(existing_body):
        return LEGACY_ISSUE_MGMT_REGEX.sub(managed_block, existing_body, count=1)
    return existing_body.rstrip() + "\n\n" + managed_block


def sync_document_to_github(
    base_dir: Path,
    doc_path: Path,
    explicit_repo: Optional[str] = None,
    project_meta: Optional[Dict[str, Any]] = None,
    existing_project_items: Optional[Set[str]] = None,
    dry_run: bool = False,
    strict: bool = False,
) -> int:
    """Synchronize a local document's status and metadata to its GitHub Issue and Project via `gh`."""
    repo_root = get_repo_root(base_dir)
    content = doc_path.read_text(encoding="utf-8")
    fields, _ = parse_frontmatter(content)
    if not fields:
        print(f"Error: {doc_path} is missing YAML frontmatter.", file=sys.stderr)
        return 1

    doc_type = detect_doc_type(doc_path, fields) or "spec"
    doc_id = fields.get("id", "")
    title = fields.get("title", "")
    status = fields.get("status", "")
    updated_at = fields.get("updated_at", "")
    github_issue = (fields.get("github_issue") or "").strip()
    github_pr = (fields.get("github_pr") or "").strip()

    config_path = base_dir / ".doc2gh.json"
    if not config_path.exists() and (repo_root / ".doc2gh.json").exists():
        config_path = repo_root / ".doc2gh.json"
    cfg_data: Dict[str, Any] = {}
    if config_path.exists():
        try:
            cfg_data = json.loads(config_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            cfg_data = {}
    if project_meta:
        for k, v in project_meta.items():
            if v is not None and v != "":
                cfg_data[k] = v

    owner, repo_name, _, repo_err = resolve_github_target(
        repo_root=repo_root,
        explicit_repo=explicit_repo or cfg_data.get("repo"),
        explicit_owner=cfg_data.get("owner"),
        existing_cfg=cfg_data,
    )
    if not owner or not repo_name:
        msg = repo_err or "Error: Could not determine GitHub repository (OWNER/REPO) for synchronization."
        print(msg, file=sys.stderr)
        return 1 if strict else 0

    full_repo = f"{owner}/{repo_name}"
    issue_title = f"[{doc_id}] {title}"
    type_label = doc_type.lower()
    status_label = f"status:{status}"
    try:
        rel_doc_path = str(doc_path.resolve().relative_to(repo_root.resolve()))
    except ValueError:
        rel_doc_path = str(doc_path.name)

    managed_block = build_issue_managed_block(
        doc_id=doc_id,
        doc_type=doc_type,
        status=status,
        updated_at=updated_at,
        github_pr=github_pr,
        rel_doc_path=rel_doc_path,
        cfg_data=cfg_data,
    )

    if dry_run:
        print(
            f"[dry-run] Would synchronize {doc_id} ('{title}') with GitHub Issue in '{full_repo}' "
            f"(labels: {type_label}, {status_label})"
        )
        if cfg_data.get("project_number") or project_meta:
            print(f"[dry-run] Would ensure {doc_id} Issue is added to GitHub Project for '{owner}'")
        return 0

    if not shutil.which("gh"):
        msg = "Error: 'gh' CLI not found; cannot synchronize GitHub Issues."
        print(msg, file=sys.stderr)
        return 1 if strict else 0

    issue_num: Optional[str] = None
    found_issue: Optional[Dict[str, Any]] = None

    m_issue = re.match(r"^#?(\d+)$", github_issue)
    linked_issue_num = m_issue.group(1) if m_issue else None
    if not linked_issue_num and github_issue:
        m_url_issue = re.search(r"/issues/(\d+)$", github_issue)
        if m_url_issue:
            linked_issue_num = m_url_issue.group(1)

    search_res = subprocess.run(
        [
            "gh",
            "issue",
            "list",
            "--repo",
            full_repo,
            "--state",
            "all",
            "--search",
            f"\"[{doc_id}]\" in:title",
            "--json",
            "number,title,body,labels,state",
        ],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
    )
    if search_res.returncode != 0 and strict:
        err_msg = (search_res.stderr or search_res.stdout).strip()
        if any(
            tok in err_msg.lower()
            for tok in ("permission", "forbidden", "403", "401", "authentication", "unauthorized")
        ):
            print(f"Error searching Issues in '{full_repo}': {err_msg}", file=sys.stderr)
            return 1

    if search_res.returncode == 0 and search_res.stdout.strip():
        try:
            found_issues = json.loads(search_res.stdout)
            if isinstance(found_issues, list):
                for item in found_issues:
                    if not isinstance(item, dict):
                        continue
                    item_title = item.get("title") or ""
                    item_body = item.get("body") or ""
                    item_num = str(item.get("number") or "")
                    if (
                        item_title.startswith(f"[{doc_id}]")
                        or f"[{doc_id}]" in item_title
                        or f"`{doc_id}`" in item_body
                        or (linked_issue_num and item_num == linked_issue_num)
                    ):
                        issue_num = item_num
                        found_issue = item
                        break
        except json.JSONDecodeError:
            pass

    if not issue_num and linked_issue_num:
        issue_num = linked_issue_num
        view_issue_res = subprocess.run(
            [
                "gh",
                "issue",
                "view",
                issue_num,
                "--repo",
                full_repo,
                "--json",
                "number,title,body,labels,state",
            ],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=False,
        )
        if view_issue_res.returncode == 0 and view_issue_res.stdout.strip():
            try:
                parsed_issue = json.loads(view_issue_res.stdout)
                if isinstance(parsed_issue, dict) and parsed_issue.get("number"):
                    found_issue = parsed_issue
            except json.JSONDecodeError:
                pass

    if not issue_num:
        create_res = subprocess.run(
            [
                "gh",
                "issue",
                "create",
                "--repo",
                full_repo,
                "--title",
                issue_title,
                "--body",
                managed_block,
                "--label",
                f"{type_label},{status_label}",
            ],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=False,
        )
        if create_res.returncode != 0:
            err_msg = (create_res.stderr or create_res.stdout).strip()
            print(
                f"Error creating GitHub Issue for {doc_id} in '{full_repo}': {err_msg}",
                file=sys.stderr,
            )
            return 1

        out_url = create_res.stdout.strip()
        m_url = re.search(r"/issues/(\d+)", out_url)
        if m_url:
            issue_num = m_url.group(1)
        elif out_url.isdigit():
            issue_num = out_url
        else:
            try:
                created_json = json.loads(out_url)
                if isinstance(created_json, dict) and created_json.get("number"):
                    issue_num = str(created_json["number"])
            except json.JSONDecodeError:
                pass

        if issue_num:
            if status in CLOSED_DOCUMENT_STATUSES:
                subprocess.run(
                    ["gh", "issue", "close", issue_num, "--repo", full_repo],
                    cwd=str(repo_root),
                    capture_output=True,
                    text=True,
                    check=False,
                )
            apply_document_updates(doc_path, issue=f"#{issue_num}", skip_if_unchanged=True)
            print(f"Created and linked GitHub Issue #{issue_num} for {doc_id}.")
    else:
        existing_body = (found_issue or {}).get("body") or ""
        merged_body = merge_issue_body(existing_body, managed_block)

        raw_labels = (found_issue or {}).get("labels") if found_issue else None
        existing_labels: List[str] = []
        if isinstance(raw_labels, list):
            for lbl in raw_labels:
                if isinstance(lbl, dict) and lbl.get("name"):
                    existing_labels.append(str(lbl["name"]))
                elif isinstance(lbl, str):
                    existing_labels.append(lbl)

        stale_status_labels = [
            l for l in existing_labels if l.startswith("status:") and l != status_label
        ]
        missing_required_labels = [
            l for l in (type_label, status_label) if l not in existing_labels
        ]

        has_full_metadata = (
            found_issue is not None
            and "body" in found_issue
            and "labels" in found_issue
            and "title" in found_issue
        )
        needs_edit = True
        if has_full_metadata:
            needs_edit = (
                (found_issue.get("title") or "") != issue_title
                or existing_body.strip() != merged_body.strip()
                or bool(stale_status_labels)
                or bool(missing_required_labels)
            )

        if needs_edit:
            edit_cmd = [
                "gh",
                "issue",
                "edit",
                issue_num,
                "--repo",
                full_repo,
                "--title",
                issue_title,
                "--body",
                merged_body,
                "--add-label",
                f"{type_label},{status_label}",
            ]
            if stale_status_labels:
                edit_cmd.extend(["--remove-label", ",".join(stale_status_labels)])
            edit_res = subprocess.run(
                edit_cmd,
                cwd=str(repo_root),
                capture_output=True,
                text=True,
                check=False,
            )
            if edit_res.returncode != 0:
                err_msg = (edit_res.stderr or edit_res.stdout).strip()
                print(
                    f"Error updating GitHub Issue #{issue_num} for {doc_id}: {err_msg}",
                    file=sys.stderr,
                )
                return 1

        expected_state = "CLOSED" if status in CLOSED_DOCUMENT_STATUSES else "OPEN"
        current_state = ((found_issue or {}).get("state") or "").upper()
        if not current_state or current_state != expected_state:
            state_cmd = "close" if expected_state == "CLOSED" else "reopen"
            subprocess.run(
                ["gh", "issue", state_cmd, issue_num, "--repo", full_repo],
                cwd=str(repo_root),
                capture_output=True,
                text=True,
                check=False,
            )

        apply_document_updates(doc_path, issue=f"#{issue_num}", skip_if_unchanged=True)
        print(f"Synchronized {doc_id} with GitHub Issue #{issue_num} ({status_label}).")

    proj_num = cfg_data.get("project_number")
    proj_owner = cfg_data.get("owner") or owner
    if issue_num and proj_num is not None and proj_owner:
        issue_url = f"https://github.com/{full_repo}/issues/{issue_num}"
        if existing_project_items is None or issue_url not in existing_project_items:
            add_res = subprocess.run(
                [
                    "gh",
                    "project",
                    "item-add",
                    str(proj_num),
                    "--owner",
                    str(proj_owner),
                    "--url",
                    issue_url,
                ],
                cwd=str(repo_root),
                capture_output=True,
                text=True,
                check=False,
            )
            if add_res.returncode == 0 and existing_project_items is not None:
                existing_project_items.add(issue_url)

    return 0


def sync_all_documents(
    doc_roots: List[Path],
    explicit_repo: Optional[str] = None,
    project_meta: Optional[Dict[str, Any]] = None,
    existing_project_items: Optional[Set[str]] = None,
    dry_run: bool = False,
    strict: bool = False,
    completed_actions: Optional[List[str]] = None,
) -> int:
    for root in doc_roots:
        for cfg in DOC_CONFIG.values():
            folder = root / cfg["dir"]
            if not folder.exists():
                continue
            for md_file in sorted(folder.glob("*.md")):
                if md_file.name in ("README.md", "template.md"):
                    continue
                rc = sync_document_to_github(
                    base_dir=root,
                    doc_path=md_file,
                    explicit_repo=explicit_repo,
                    project_meta=project_meta,
                    existing_project_items=existing_project_items,
                    dry_run=dry_run,
                    strict=strict,
                )
                if rc != 0:
                    return rc
                if completed_actions is not None and not dry_run:
                    fields, _ = parse_frontmatter(md_file.read_text(encoding="utf-8"))
                    doc_id = (fields or {}).get("id", md_file.name)
                    completed_actions.append(f"Synchronized document {doc_id} to GitHub Issue/Project")
    return 0


def find_relevant_docs_for_branch(doc_roots: List[Path], branch: str) -> List[Tuple[Path, Path]]:
    """Return list of (doc_root, doc_path) relevant to the current feature branch."""
    matched: List[Tuple[Path, Path]] = []
    seen: Set[Path] = set()

    # 1. Explicit ADR-NNNN / RFC-NNNN / SPEC-NNNN or type/NNNN in branch name
    branch_doc_ids = {
        m.upper() for m in re.findall(r"\b(?:ADR|RFC|SPEC)-\d{4}\b", branch, flags=re.IGNORECASE)
    }
    m_prefix_num = re.search(r"\b(adr|rfc|spec)s?[/-](\d{4})\b", branch, flags=re.IGNORECASE)
    if m_prefix_num:
        branch_doc_ids.add(f"{m_prefix_num.group(1).upper()}-{m_prefix_num.group(2)}")

    all_docs: List[Tuple[Path, Path]] = []
    for root in doc_roots:
        for cfg in DOC_CONFIG.values():
            folder = root / cfg["dir"]
            if not folder.exists():
                continue
            for md_file in sorted(folder.glob("*.md")):
                if md_file.name in ("README.md", "template.md"):
                    continue
                resolved = md_file.resolve()
                all_docs.append((root, resolved))
                content = resolved.read_text(encoding="utf-8")
                fields, _ = parse_frontmatter(content)
                doc_id = ((fields or {}).get("id") or "").upper()
                if doc_id in branch_doc_ids and resolved not in seen:
                    seen.add(resolved)
                    matched.append((root, resolved))

    if matched:
        return matched
    return all_docs


def setup_branch_pull_request(
    repo_root: Path,
    doc_roots: List[Path],
    owner: str,
    repo_name: str,
    base_branch: str,
    project_meta: Dict[str, Any],
    existing_project_items: Set[str],
    args: argparse.Namespace,
    completed_actions: List[str],
) -> int:
    full_repo = f"{owner}/{repo_name}"
    branch, branch_err = get_current_branch(repo_root)
    if branch_err or not branch:
        print(branch_err or "Error: Missing active Git branch for Pull Request.", file=sys.stderr)
        return 1

    if branch in SUPPORTED_DEFAULT_BRANCHES or branch == base_branch:
        print(
            f"Error: Cannot create a Pull Request from default/base branch '{branch}'. "
            "Switch to a feature branch first.",
            file=sys.stderr,
        )
        return 1

    relevant_docs = find_relevant_docs_for_branch(doc_roots, branch)
    doc_ids: List[str] = []
    issue_refs: List[str] = []
    primary_title = branch

    for _, doc_path in relevant_docs:
        fields, _ = parse_frontmatter(doc_path.read_text(encoding="utf-8"))
        if not fields:
            continue
        did = fields.get("id", "")
        dtitle = fields.get("title", "")
        dissue = (fields.get("github_issue") or "").strip()
        if did:
            doc_ids.append(did)
            if len(doc_ids) == 1 and dtitle:
                primary_title = f"[{did}] {dtitle}"
        if dissue and dissue not in issue_refs:
            issue_refs.append(dissue)

    pr_title = getattr(args, "pr_title", None) or primary_title
    if getattr(args, "pr_body", None):
        pr_body = args.pr_body
    else:
        body_parts = ["### Summary", "Automated doc2gh initialization and specification tracking PR."]
        if doc_ids:
            body_parts.append("\n### Tracked Documents\n" + "\n".join(f"- `{d}`" for d in doc_ids))
        if issue_refs:
            body_parts.append("\n### Linked Issues\n" + "\n".join(f"- Refs {i}" for i in issue_refs))
        pr_body = "\n".join(body_parts)

    if args.dry_run:
        docs_label = ", ".join(doc_ids) if doc_ids else "none"
        print(
            f"[dry-run] Would create or reuse Pull Request from '{branch}' into '{base_branch}' "
            f"in '{full_repo}' and link to document(s): {docs_label}"
        )
        return 0

    # Check if an open PR already exists for this branch
    pr_list_res = subprocess.run(
        [
            "gh",
            "pr",
            "list",
            "--repo",
            full_repo,
            "--head",
            branch,
            "--state",
            "open",
            "--json",
            "number,url,title,body",
        ],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
    )

    pr_num: Optional[str] = None
    pr_url: Optional[str] = None
    if pr_list_res.returncode == 0 and pr_list_res.stdout.strip():
        try:
            prs = json.loads(pr_list_res.stdout)
            if isinstance(prs, list) and prs:
                first_pr = prs[0]
                if isinstance(first_pr, dict) and first_pr.get("number"):
                    pr_num = str(first_pr["number"])
                    pr_url = str(first_pr.get("url") or f"https://github.com/{full_repo}/pull/{pr_num}")
        except json.JSONDecodeError:
            pass

    if pr_num:
        print(f"Reusing existing Pull Request #{pr_num} ({pr_url}) for branch '{branch}'.")
        completed_actions.append(f"Reused Pull Request #{pr_num} for branch '{branch}'")
    else:
        # Ensure branch is pushed before opening PR if not already pushed
        if not any(act.startswith(f"Pushed branch '{branch}'") for act in completed_actions):
            up_res = subprocess.run(
                [
                    "git",
                    "-C",
                    str(repo_root),
                    "rev-parse",
                    "--abbrev-ref",
                    "--symbolic-full-name",
                    "@{u}",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            if up_res.returncode != 0:
                rc = validate_and_push_branch(
                    repo_root=repo_root,
                    full_repo=full_repo,
                    auto_confirm=getattr(args, "yes", False),
                    require_upstream_check=True,
                    completed_actions=completed_actions,
                )
                if rc != 0:
                    return rc

        pr_create_cmd = [
            "gh",
            "pr",
            "create",
            "--repo",
            full_repo,
            "--base",
            base_branch,
            "--head",
            branch,
            "--title",
            pr_title,
            "--body",
            pr_body,
        ]
        if getattr(args, "draft_pr", False):
            pr_create_cmd.append("--draft")

        pr_create_res = subprocess.run(
            pr_create_cmd,
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=False,
        )
        if pr_create_res.returncode != 0:
            err = (pr_create_res.stderr or pr_create_res.stdout).strip()
            print(f"Error creating Pull Request for branch '{branch}': {err}", file=sys.stderr)
            return 1

        out_str = pr_create_res.stdout.strip()
        m_pr = re.search(r"/pull/(\d+)", out_str)
        if m_pr:
            pr_num = m_pr.group(1)
            pr_url = out_str
        elif out_str.isdigit():
            pr_num = out_str
            pr_url = f"https://github.com/{full_repo}/pull/{pr_num}"
        else:
            try:
                pr_json = json.loads(out_str)
                if isinstance(pr_json, dict) and pr_json.get("number"):
                    pr_num = str(pr_json["number"])
                    pr_url = str(pr_json.get("url") or f"https://github.com/{full_repo}/pull/{pr_num}")
            except json.JSONDecodeError:
                pass

        if not pr_num:
            print("Error: Could not parse Pull Request number from 'gh pr create' output.", file=sys.stderr)
            return 1

        print(f"Created Pull Request #{pr_num} ({pr_url}) for branch '{branch}'.")
        completed_actions.append(f"Created Pull Request #{pr_num} for branch '{branch}'")

    # Link PR to relevant documents and re-sync their tracking Issues
    for doc_root, doc_path in relevant_docs:
        apply_document_updates(doc_path, pr=f"#{pr_num}", skip_if_unchanged=True)
        sync_document_to_github(
            base_dir=doc_root,
            doc_path=doc_path,
            explicit_repo=full_repo,
            project_meta=project_meta,
            existing_project_items=existing_project_items,
            dry_run=False,
            strict=False,
        )

    return 0


def report_partial_failure(completed_actions: List[str], failed_step: str) -> None:
    if not completed_actions:
        return
    print("\nPartial setup completed before failure:", file=sys.stderr)
    for act in completed_actions:
        print(f"  - Completed: {act}", file=sys.stderr)
    print(f"  - Failed during: {failed_step}", file=sys.stderr)
    print(
        "Safe to retry: Resolve the error above and re-run `doc2gh.py init`. "
        "Completed steps are idempotent and will be reused.",
        file=sys.stderr,
    )


def cmd_init(args: argparse.Namespace) -> int:
    base_dir = get_base_dir(args.root)
    repo_root = get_repo_root(base_dir, args.repo_root)
    doc_roots = get_doc_roots(base_dir, repo_root, explicit_root=args.root)
    completed_actions: List[str] = []

    # Phase 1: Validate all local documents and templates before any mutations (FR-02)
    total_checked = 0
    all_val_errors: List[str] = []
    for d_root in doc_roots:
        checked, errs = collect_validation_errors(d_root, include_templates=True)
        total_checked += checked
        all_val_errors.extend(errs)

    if total_checked == 0:
        print(
            f"Error: No doc2gh documents or templates found in {base_dir}.",
            file=sys.stderr,
        )
        return 1

    if all_val_errors:
        print("Validation failed before initialization:", file=sys.stderr)
        for err in all_val_errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    print(f"Validated {total_checked} local document(s) and template(s).")

    # Phase 2: Git & Repository preflight checks (FR-01, FR-03)
    if not shutil.which("git"):
        print("Error: 'git' is not installed or not in PATH.", file=sys.stderr)
        return 1

    if not (repo_root / ".git").exists():
        git_check = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "--is-inside-work-tree"],
            capture_output=True,
            text=True,
            check=False,
        )
        if git_check.returncode != 0:
            print(
                f"Error: '{repo_root}' is not a Git repository. Run 'git init' first.",
                file=sys.stderr,
            )
            return 1

    config_path = base_dir / ".doc2gh.json"
    existing_cfg: Dict[str, Any] = {}
    if config_path.exists():
        try:
            existing_cfg = json.loads(config_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            existing_cfg = {}

    owner, detected_repo, origin_url, repo_err = resolve_github_target(
        repo_root=repo_root,
        explicit_repo=args.repo,
        explicit_owner=args.owner,
        existing_cfg=existing_cfg,
    )

    if not args.skip_github:
        if repo_err or not owner or not detected_repo:
            print(
                repo_err
                or "Error: Could not resolve GitHub owner/repository. Pass --repo OWNER/REPO.",
                file=sys.stderr,
            )
            return 1

        if not args.dry_run:
            if not shutil.which("gh"):
                print(
                    "Error: GitHub CLI ('gh') is not installed. "
                    "Install 'gh' and authenticate, or pass --skip-github.",
                    file=sys.stderr,
                )
                return 1

            auth_check = subprocess.run(
                ["gh", "auth", "status"],
                cwd=str(repo_root),
                capture_output=True,
                text=True,
                check=False,
            )
            if auth_check.returncode != 0:
                err_detail = (auth_check.stderr or auth_check.stdout).strip()
                print(
                    f"Error: GitHub CLI ('gh') is not authenticated: {err_detail}\n"
                    "Authenticate with: gh auth login --scopes repo,project,read:org",
                    file=sys.stderr,
                )
                return 1

    repo_name = detected_repo or repo_root.name
    project_title = args.project_title or f"{repo_name} - doc2gh Governance"
    default_branch = getattr(args, "base_branch", None) or "main"

    if owner and repo_name:
        print(f"Target GitHub repository: {owner}/{repo_name} (root: {repo_root})")

    # Phase 3: Ensure remote GitHub repository exists (or create/push with confirmation) (FR-04)
    if not args.skip_github and owner and detected_repo:
        repo_rc, default_branch = ensure_github_repository_and_remote(
            repo_root=repo_root,
            owner=owner,
            repo_name=detected_repo,
            origin_url=origin_url,
            args=args,
            completed_actions=completed_actions,
        )
        if repo_rc != 0:
            report_partial_failure(completed_actions, "GitHub repository setup and push")
            return repo_rc

    # Phase 4: Inspect, create, or repair workflow symbolic links in .github/workflows/ (FR-06, FR-07)
    rc, symlinks = setup_workflow_symlinks(
        base_dir=base_dir,
        repo_root=repo_root,
        link_mode=args.link_mode,
        force=args.force,
        dry_run=args.dry_run,
    )
    if rc != 0:
        report_partial_failure(completed_actions, "workflow symbolic link setup")
        return rc
    if not args.dry_run:
        completed_actions.append(f"Configured {len(symlinks)} workflow link(s) in .github/workflows/")

    # Phase 5: Provision or reuse GitHub Project and required labels (FR-06)
    project_meta: Dict[str, Any] = {
        "owner": owner or "",
        "repo": f"{owner}/{repo_name}" if (owner and repo_name) else repo_name,
        "project_title": project_title,
        "project_number": None,
        "project_id": "",
        "project_url": "",
    }
    if not args.skip_github:
        gh_rc, project_meta = setup_github_project_and_tools(
            base_dir=base_dir,
            repo_root=repo_root,
            owner=owner,
            repo_name=detected_repo,
            project_title=project_title,
            skip_labels=args.skip_labels,
            dry_run=args.dry_run,
        )
        if gh_rc != 0:
            report_partial_failure(completed_actions, "GitHub Project and label provisioning")
            return gh_rc
        if not args.dry_run:
            completed_actions.append(
                f"Provisioned GitHub Project '{project_title}' and repository labels"
            )
    else:
        print("Skipped GitHub Project and Issue setup (--skip-github).")

    # Phase 6: Persist doc2gh configuration metadata (.doc2gh.json)
    config_data: Dict[str, Any] = {
        "owner": project_meta.get("owner") or existing_cfg.get("owner", ""),
        "repo": project_meta.get("repo") or existing_cfg.get("repo", ""),
        "project_title": project_meta.get("project_title")
        or existing_cfg.get("project_title", project_title),
        "project_number": (
            project_meta.get("project_number")
            if project_meta.get("project_number") is not None
            else existing_cfg.get("project_number")
        ),
        "project_id": project_meta.get("project_id") or existing_cfg.get("project_id", ""),
        "project_url": project_meta.get("project_url") or existing_cfg.get("project_url", ""),
        "workflow_link_mode": args.link_mode,
        "workflow_symlinks": symlinks,
        "updated_at": date.today().isoformat(),
    }

    if args.dry_run:
        try:
            rel_cfg = config_path.relative_to(repo_root)
        except ValueError:
            rel_cfg = config_path.relative_to(base_dir)
        print(f"[dry-run] Would write configuration to {rel_cfg}")
    else:
        config_path.write_text(json.dumps(config_data, indent=2) + "\n", encoding="utf-8")
        try:
            rel_cfg = config_path.relative_to(repo_root)
        except ValueError:
            rel_cfg = config_path.relative_to(base_dir)
        print(f"Saved doc2gh project configuration to {rel_cfg}")
        completed_actions.append(f"Saved configuration to {rel_cfg}")

    # Phase 7: Synchronize local ADRs, RFCs, and Specs with GitHub Issues & Project items (FR-05, FR-08)
    existing_project_items: Set[str] = set()
    if not args.skip_github and not getattr(args, "skip_issues", False) and owner and detected_repo:
        if not args.dry_run and config_data.get("project_number") is not None:
            existing_project_items = get_existing_project_item_urls(
                repo_root=repo_root,
                owner=owner,
                proj_num=str(config_data["project_number"]),
            )

        sync_rc = sync_all_documents(
            doc_roots=doc_roots,
            explicit_repo=f"{owner}/{detected_repo}",
            project_meta=config_data,
            existing_project_items=existing_project_items,
            dry_run=args.dry_run,
            strict=True,
            completed_actions=completed_actions,
        )
        if sync_rc != 0:
            report_partial_failure(completed_actions, "document-to-GitHub Issue synchronization")
            return sync_rc

    # Phase 8: Optional Pull Request creation/reuse when explicitly requested on a feature branch (FR-09)
    if getattr(args, "create_pr", False) and not args.skip_github and owner and detected_repo:
        pr_rc = setup_branch_pull_request(
            repo_root=repo_root,
            doc_roots=doc_roots,
            owner=owner,
            repo_name=detected_repo,
            base_branch=default_branch,
            project_meta=config_data,
            existing_project_items=existing_project_items,
            args=args,
            completed_actions=completed_actions,
        )
        if pr_rc != 0:
            report_partial_failure(completed_actions, "Pull Request setup and linking")
            return pr_rc

    return 0


def cmd_sync(args: argparse.Namespace) -> int:
    base_dir = get_base_dir(args.root)
    repo_root = get_repo_root(base_dir)
    dry_run = getattr(args, "dry_run", False)

    if args.document:
        try:
            doc_path = resolve_doc_path(base_dir, args.document)
        except FileNotFoundError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        doc_type = detect_doc_type(doc_path) or "spec"
        val_errs = validate_single_document(doc_path, doc_type, is_template=False)
        if val_errs:
            for err in val_errs:
                print(f"  - {err}", file=sys.stderr)
            return 1
        return sync_document_to_github(
            base_dir, doc_path, explicit_repo=args.repo, dry_run=dry_run
        )

    doc_roots = get_doc_roots(base_dir, repo_root, explicit_root=args.root)
    rc = 0
    for root in doc_roots:
        for cfg in DOC_CONFIG.values():
            folder = root / cfg["dir"]
            if not folder.exists():
                continue
            for md_file in sorted(folder.glob("*.md")):
                if md_file.name in ("README.md", "template.md"):
                    continue
                if (
                    sync_document_to_github(
                        root, md_file, explicit_repo=args.repo, dry_run=dry_run
                    )
                    != 0
                ):
                    rc = 1
    return rc


def find_matching_documents(
    base_dir: Path,
    text_blobs: List[str],
    issue_ref: Optional[str] = None,
    pr_ref: Optional[str] = None,
    modified_files: Optional[List[str]] = None,
) -> List[Path]:
    matched_paths: List[Path] = []
    seen: set[Path] = set()

    combined_text = "\n".join(t for t in text_blobs if t)
    doc_ids = {
        m.upper()
        for m in re.findall(r"\b(?:ADR|RFC|SPEC)-\d{4}\b", combined_text, flags=re.IGNORECASE)
    }

    for doc_id in sorted(doc_ids):
        try:
            resolved = resolve_doc_path(base_dir, doc_id)
            if resolved not in seen:
                seen.add(resolved)
                matched_paths.append(resolved)
        except FileNotFoundError:
            pass

    repo_root = get_repo_root(base_dir)
    doc_roots = get_doc_roots(base_dir, repo_root)

    if modified_files:
        for rel_file in modified_files:
            candidate = (repo_root / rel_file).resolve()
            if (
                candidate.exists()
                and candidate.suffix == ".md"
                and candidate.name not in ("README.md", "template.md")
                and candidate.parent.name in DIR_TO_TYPE
            ):
                in_known_root = False
                for d_root in doc_roots:
                    try:
                        candidate.relative_to(d_root)
                        in_known_root = True
                        break
                    except ValueError:
                        continue
                if in_known_root and candidate not in seen:
                    seen.add(candidate)
                    matched_paths.append(candidate)

    for d_root in doc_roots:
        for cfg in DOC_CONFIG.values():
            folder = d_root / cfg["dir"]
            if not folder.exists():
                continue
            for md_file in sorted(folder.glob("*.md")):
                if md_file.name in ("README.md", "template.md"):
                    continue
                resolved = md_file.resolve()
                if resolved in seen:
                    continue
                content = resolved.read_text(encoding="utf-8")
                fields, _ = parse_frontmatter(content)
                if not fields:
                    continue
                if issue_ref and (fields.get("github_issue") or "").strip() == issue_ref:
                    seen.add(resolved)
                    matched_paths.append(resolved)
                elif pr_ref and (fields.get("github_pr") or "").strip() == pr_ref:
                    seen.add(resolved)
                    matched_paths.append(resolved)

    return matched_paths


def handle_slash_command_in_comment(
    base_dir: Path,
    comment_body: str,
    default_issue_ref: Optional[str],
    default_pr_ref: Optional[str],
) -> int:
    """Parse `/doc2gh status ...` or `/doc2gh link ...` commands from GitHub Issue/PR comments."""
    rc = 0
    for raw_line in comment_body.splitlines():
        line = raw_line.strip()
        if not line.startswith("/doc2gh "):
            continue
        tokens = line.split()
        if len(tokens) < 3:
            continue
        subcmd = tokens[1].lower()
        doc_target = tokens[2]
        try:
            doc_path = resolve_doc_path(base_dir, doc_target)
        except FileNotFoundError as exc:
            print(f"Warning: {exc}", file=sys.stderr)
            continue

        issue_arg = default_issue_ref
        pr_arg = default_pr_ref
        sup_by: Optional[str] = None

        i = 3
        new_status: Optional[str] = None
        if subcmd == "status" and len(tokens) >= 4:
            new_status = tokens[3].lower()
            i = 4

        while i < len(tokens):
            tok = tokens[i]
            if tok == "--issue" and i + 1 < len(tokens):
                issue_arg = tokens[i + 1]
                i += 2
            elif tok == "--pr" and i + 1 < len(tokens):
                pr_arg = tokens[i + 1]
                i += 2
            elif tok == "--superseded-by" and i + 1 < len(tokens):
                sup_by = tokens[i + 1].upper()
                i += 2
            else:
                i += 1

        if subcmd in ("status", "link"):
            res = apply_document_updates(
                doc_path=doc_path,
                new_status=new_status if subcmd == "status" else None,
                issue=issue_arg,
                pr=pr_arg,
                superseded_by=sup_by,
                skip_if_unchanged=True,
            )
            if res != 0:
                rc = res
            else:
                doc_type = detect_doc_type(doc_path) or "spec"
                if validate_single_document(doc_path, doc_type, is_template=False):
                    rc = 1
    return rc


def cmd_gh_event(args: argparse.Namespace) -> int:
    """Apply doc2gh document management rules in response to GitHub Issue, PR, or Comment events."""
    base_dir = get_base_dir(args.root)
    event_name = (args.event_name or os.environ.get("GITHUB_EVENT_NAME") or "").strip()
    event_path = (args.event_path or os.environ.get("GITHUB_EVENT_PATH") or "").strip()

    if not event_name or not event_path or not Path(event_path).exists():
        print(
            "Error: Valid --event-name ($GITHUB_EVENT_NAME) and --event-path ($GITHUB_EVENT_PATH) are required.",
            file=sys.stderr,
        )
        return 1

    payload = json.loads(Path(event_path).read_text(encoding="utf-8"))
    action = payload.get("action", "")
    modified_files = [f.strip() for f in (args.files or []) if f.strip()]

    if event_name == "issue_comment":
        comment = payload.get("comment") or {}
        issue = payload.get("issue") or {}
        num = issue.get("number")
        is_pr = "pull_request" in issue
        default_issue_ref = f"#{num}" if (num and not is_pr) else None
        default_pr_ref = f"#{num}" if (num and is_pr) else None
        return handle_slash_command_in_comment(
            base_dir=base_dir,
            comment_body=comment.get("body") or "",
            default_issue_ref=default_issue_ref,
            default_pr_ref=default_pr_ref,
        )

    if event_name == "issues":
        issue = payload.get("issue") or {}
        issue_num = issue.get("number")
        if not issue_num:
            return 0
        issue_ref = f"#{issue_num}"
        docs = find_matching_documents(
            base_dir=base_dir,
            text_blobs=[issue.get("title") or "", issue.get("body") or ""],
            issue_ref=issue_ref,
        )
        if not docs:
            print(f"No tracked doc2gh documents matched Issue {issue_ref}.")
            return 0

        rc = 0
        for doc_path in docs:
            content = doc_path.read_text(encoding="utf-8")
            fields, _ = parse_frontmatter(content)
            if not fields:
                continue
            doc_type = detect_doc_type(doc_path, fields)
            if not doc_type:
                continue
            cfg = DOC_CONFIG[doc_type]
            current_status = fields.get("status", cfg["default_status"])
            target_status: Optional[str] = None

            if action == "labeled":
                label_name = ((payload.get("label") or {}).get("name") or "").strip()
                if label_name.startswith("status:"):
                    candidate_status = label_name.split(":", 1)[1].strip().lower()
                    if candidate_status in cfg["valid_statuses"]:
                        target_status = candidate_status
                    else:
                        print(
                            f"Warning: Ignoring invalid status label '{label_name}' for {doc_type.upper()} ({doc_path.name}).",
                            file=sys.stderr,
                        )
            elif action in ("opened", "edited"):
                for lbl in issue.get("labels") or []:
                    lbl_name = (lbl.get("name") if isinstance(lbl, dict) else str(lbl)).strip()
                    if lbl_name.startswith("status:"):
                        cand = lbl_name.split(":", 1)[1].strip().lower()
                        if cand in cfg["valid_statuses"]:
                            target_status = cand
                            break
            elif action == "closed":
                state_reason = (issue.get("state_reason") or "completed").lower()
                if current_status not in CLOSED_DOCUMENT_STATUSES:
                    if doc_type == "spec":
                        target_status = "archived" if state_reason == "not_planned" else "done"
                    elif doc_type == "rfc":
                        target_status = "rejected" if state_reason == "not_planned" else "implemented"
                    elif doc_type == "adr":
                        target_status = "deprecated" if state_reason == "not_planned" else "accepted"
            elif action == "reopened":
                if current_status in CLOSED_DOCUMENT_STATUSES:
                    reopen_map = {"spec": "in-progress", "rfc": "review", "adr": "proposed"}
                    target_status = reopen_map.get(doc_type, cfg["default_status"])

            res = apply_document_updates(
                doc_path=doc_path,
                new_status=target_status,
                issue=issue_ref,
                skip_if_unchanged=True,
            )
            if res != 0:
                rc = res
            elif validate_single_document(doc_path, doc_type, is_template=False):
                rc = 1
        return rc

    if event_name in ("pull_request", "pull_request_target"):
        pr = payload.get("pull_request") or {}
        pr_num = pr.get("number")
        if not pr_num:
            return 0
        pr_ref = f"#{pr_num}"
        merged = bool(pr.get("merged"))
        pr_state = (pr.get("state") or "").lower()

        docs = find_matching_documents(
            base_dir=base_dir,
            text_blobs=[pr.get("title") or "", pr.get("body") or ""],
            pr_ref=pr_ref,
            modified_files=modified_files,
        )
        if not docs:
            print(f"No tracked doc2gh documents matched Pull Request {pr_ref}.")
            return 0

        rc = 0
        for doc_path in docs:
            content = doc_path.read_text(encoding="utf-8")
            fields, _ = parse_frontmatter(content)
            if not fields:
                continue
            doc_type = detect_doc_type(doc_path, fields)
            if not doc_type:
                continue
            cfg = DOC_CONFIG[doc_type]
            current_status = fields.get("status", cfg["default_status"])
            target_status: Optional[str] = None

            if action == "closed" and merged:
                if doc_type == "adr" and current_status == "proposed":
                    target_status = "accepted"
                elif doc_type == "rfc" and current_status in ("draft", "review"):
                    target_status = "approved"
                elif doc_type == "spec" and current_status in ("draft", "ready", "in-progress"):
                    target_status = "done"
            elif action in ("opened", "reopened", "edited", "synchronize") and pr_state == "open":
                if doc_type == "rfc" and current_status == "draft":
                    target_status = "review"
                elif doc_type == "spec" and current_status in ("draft", "ready"):
                    target_status = "in-progress"

            res = apply_document_updates(
                doc_path=doc_path,
                new_status=target_status,
                pr=pr_ref,
                skip_if_unchanged=True,
            )
            if res != 0:
                rc = res
            elif validate_single_document(doc_path, doc_type, is_template=False):
                rc = 1
        return rc

    print(f"Unhandled GitHub event '{event_name}'; nothing to update.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="doc2gh",
        description="CLI tool to manage doc2gh documents (ADRs, RFCs, Specs), statuses, and GitHub links.",
    )
    parser.add_argument(
        "--root",
        help="Path to the doc2gh root directory (defaults to auto-detected parent of tools/).",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # init
    p_init = subparsers.add_parser(
        "init",
        help=(
            "Bootstrap doc2gh in the repository: validate documents, prepare/verify GitHub repository, "
            "provision GitHub Project and labels, symlink workflows, and synchronize tracking Issues."
        ),
    )
    p_init.add_argument(
        "--repo-root",
        dest="repo_root",
        help="Path to the host Git repository root (auto-detected if omitted).",
    )
    p_init.add_argument(
        "--repo",
        help="Target GitHub repository in 'OWNER/REPO' format (auto-detected from git remote if omitted).",
    )
    p_init.add_argument(
        "--owner",
        help="GitHub user or organization login for the repository and GitHub Project.",
    )
    p_init.add_argument(
        "--project-title",
        "--title",
        dest="project_title",
        help="Title of the GitHub Project to create or reuse (defaults to '<repo> - doc2gh Governance').",
    )
    p_init.add_argument(
        "--link-mode",
        dest="link_mode",
        choices=["files", "dir"],
        default="files",
        help="How to symlink workflows into .github/workflows: 'files' (symlink each .yml file, default) or 'dir' (symlink .github/workflows directory).",
    )
    p_init.add_argument(
        "--force",
        action="store_true",
        help="Replace directory symlinks when switching link modes (regular files/directories are always preserved).",
    )
    p_init.add_argument(
        "--skip-github",
        dest="skip_github",
        action="store_true",
        help="Validate documents and configure workflow symbolic links locally without executing GitHub CLI ('gh') commands.",
    )
    p_init.add_argument(
        "--skip-labels",
        dest="skip_labels",
        action="store_true",
        help="Skip creating/updating standard doc2gh labels on GitHub.",
    )
    p_init.add_argument(
        "--skip-issues",
        "--skip-sync",
        dest="skip_issues",
        action="store_true",
        help="Skip synchronizing local documents to GitHub Issues during init.",
    )
    p_init.add_argument(
        "--yes",
        "-y",
        "--confirm",
        dest="yes",
        action="store_true",
        help="Automatically confirm remote repository creation and branch push.",
    )
    p_init.add_argument(
        "--visibility",
        choices=["private", "public", "internal"],
        default="private",
        help="Repository visibility when creating a missing GitHub repository (default: private).",
    )
    p_init.add_argument(
        "--push",
        action="store_true",
        help="Push the current branch to 'origin' (after confirmation) even when the remote repository already exists.",
    )
    p_init.add_argument(
        "--default-branch",
        "--base",
        dest="base_branch",
        help="Expected default/base branch name ('main' or 'master').",
    )
    p_init.add_argument(
        "--create-pr",
        "--pr",
        dest="create_pr",
        action="store_true",
        help="Create or reuse a Pull Request when on a non-default branch and link it to tracked documents/Issues.",
    )
    p_init.add_argument(
        "--pr-title",
        dest="pr_title",
        help="Optional title when creating a Pull Request with --create-pr.",
    )
    p_init.add_argument(
        "--pr-body",
        dest="pr_body",
        help="Optional body when creating a Pull Request with --create-pr.",
    )
    p_init.add_argument(
        "--draft-pr",
        dest="draft_pr",
        action="store_true",
        help="Create the Pull Request as a draft when --create-pr is used.",
    )
    p_init.add_argument(
        "--dry-run",
        "--plan",
        dest="dry_run",
        action="store_true",
        help="Preview validation, Git/remote actions, workflow symlinks, GitHub Project, labels, Issues, and PR plan without applying changes.",
    )
    p_init.set_defaults(func=cmd_init)

    # new
    p_new = subparsers.add_parser("new", help="Create a new ADR, RFC, or Spec from template.")
    p_new.add_argument("type", choices=["adr", "rfc", "spec"], help="Document type.")
    p_new.add_argument("title", help="Document title.")
    p_new.add_argument("--status", help="Initial status (defaults to type default).")
    p_new.add_argument("--issue", help="GitHub Issue reference (e.g. '#12').")
    p_new.add_argument("--pr", help="GitHub Pull Request reference (e.g. '#15').")
    p_new.add_argument("--number", type=int, help="Explicit sequence number (defaults to next available).")
    p_new.add_argument(
        "--sync-github",
        dest="sync_github",
        action="store_true",
        help="Immediately create/update the corresponding GitHub Issue and Project item via 'gh'.",
    )
    p_new.set_defaults(func=cmd_new)

    # status
    p_status = subparsers.add_parser(
        "status", help="Update the status of a document and refresh its managed section."
    )
    p_status.add_argument("document", help="Document path or ID (e.g. 'ADR-0001' or 'adrs/0001-foo.md').")
    p_status.add_argument("status", help="New status value.")
    p_status.add_argument("--issue", help="Optional GitHub Issue reference to set/update.")
    p_status.add_argument("--pr", help="Optional GitHub PR reference to set/update.")
    p_status.add_argument(
        "--superseded-by",
        dest="superseded_by",
        help="Required when setting an ADR status to 'superseded' (e.g. 'ADR-0002').",
    )
    p_status.add_argument(
        "--sync-github",
        dest="sync_github",
        action="store_true",
        help="Immediately synchronize the updated status and labels to the GitHub Issue/Project via 'gh'.",
    )
    p_status.set_defaults(func=cmd_status)

    # link
    p_link = subparsers.add_parser(
        "link", help="Update GitHub Issue and/or Pull Request references in the managed section."
    )
    p_link.add_argument("document", help="Document path or ID (e.g. 'SPEC-0001').")
    p_link.add_argument("--issue", help="GitHub Issue reference (e.g. '#20').")
    p_link.add_argument("--pr", help="GitHub PR reference (e.g. '#25').")
    p_link.add_argument(
        "--sync-github",
        dest="sync_github",
        action="store_true",
        help="Immediately synchronize the linked metadata to GitHub Issue/Project via 'gh'.",
    )
    p_link.set_defaults(func=cmd_link)

    # sync
    p_sync = subparsers.add_parser(
        "sync",
        help="Synchronize one or all local documents to GitHub Issues, labels, and Project via 'gh'.",
    )
    p_sync.add_argument(
        "document",
        nargs="?",
        help="Optional document ID or path (e.g. 'SPEC-0001'). If omitted, syncs all tracked documents.",
    )
    p_sync.add_argument("--repo", help="Optional GitHub repository in 'OWNER/REPO' format.")
    p_sync.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        help="Preview synchronization actions without calling GitHub CLI write commands.",
    )
    p_sync.set_defaults(func=cmd_sync)

    # gh-event
    p_ghe = subparsers.add_parser(
        "gh-event",
        help="Process a GitHub Actions event (issues, pull_request, issue_comment) and update managed document sections.",
    )
    p_ghe.add_argument(
        "--event-name",
        dest="event_name",
        help="GitHub event name (defaults to $GITHUB_EVENT_NAME).",
    )
    p_ghe.add_argument(
        "--event-path",
        dest="event_path",
        help="Path to GitHub event payload JSON (defaults to $GITHUB_EVENT_PATH).",
    )
    p_ghe.add_argument(
        "--files",
        nargs="*",
        help="Optional list of modified file paths in a Pull Request.",
    )
    p_ghe.set_defaults(func=cmd_gh_event)

    # validate
    p_val = subparsers.add_parser(
        "validate", help="Validate frontmatter, statuses, and managed sections of all documents."
    )
    p_val.add_argument(
        "--include-templates",
        action="store_true",
        help="Also validate template.md files in each directory.",
    )
    p_val.set_defaults(func=cmd_validate)

    # list
    p_list = subparsers.add_parser("list", help="List tracked documents and their metadata.")
    p_list.add_argument("--type", choices=["adr", "rfc", "spec"], help="Filter by document type.")
    p_list.add_argument("--status", help="Filter by status.")
    p_list.add_argument(
        "--format", choices=["table", "json"], default="table", help="Output format."
    )
    p_list.set_defaults(func=cmd_list)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

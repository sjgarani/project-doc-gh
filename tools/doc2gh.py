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
from typing import Any, Dict, List, Optional, Tuple

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

MGMT_START_MARKER = (
    "<!-- DOC2GH:MANAGEMENT:START - DO NOT EDIT THIS SECTION MANUALLY. "
    "Use `python3 tools/doc2gh.py` to manage status and GitHub links. -->"
)
MGMT_END_MARKER = "<!-- DOC2GH:MANAGEMENT:END -->"

MGMT_BLOCK_REGEX = re.compile(
    r"<!-- DOC2GH:MANAGEMENT:START[^>]*-->.*?<!-- DOC2GH:MANAGEMENT:END -->",
    re.DOTALL,
)

FRONTMATTER_REGEX = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def get_base_dir(custom_root: Optional[str] = None) -> Path:
    if custom_root:
        return Path(custom_root).resolve()
    return Path(__file__).resolve().parent.parent


def get_repo_root(base_dir: Path, custom_repo_root: Optional[str] = None) -> Path:
    if custom_repo_root:
        return Path(custom_repo_root).resolve()
    for candidate in (base_dir, *base_dir.parents):
        if (candidate / ".git").exists():
            return candidate
    if base_dir.name in ("doc", "docs"):
        return base_dir.parent
    return base_dir


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

    # Try resolving by document ID (e.g. ADR-0001, RFC-0002, SPEC-0001)
    id_upper = target.strip().upper()
    for cfg in DOC_CONFIG.values():
        folder = base_dir / cfg["dir"]
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


def cmd_validate(args: argparse.Namespace) -> int:
    base_dir = get_base_dir(args.root)
    errors: List[str] = []
    checked_count = 0

    for doc_type, cfg in DOC_CONFIG.items():
        folder = base_dir / cfg["dir"]
        if not folder.exists():
            continue
        for md_file in sorted(folder.glob("*.md")):
            if md_file.name == "README.md":
                continue
            is_template = md_file.name == "template.md"
            if is_template and not args.include_templates:
                continue
            checked_count += 1
            errors.extend(validate_single_document(md_file, doc_type, is_template=is_template))

    print(f"Validated {checked_count} document(s) in {base_dir}")
    if errors:
        print("\nValidation failed with the following errors:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    print("All checked documents conform to doc2gh standards.")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    base_dir = get_base_dir(args.root)
    items = []

    for doc_type, cfg in DOC_CONFIG.items():
        if args.type and args.type.lower() != doc_type:
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
            if args.status and fields.get("status") != args.status:
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
                }
            )

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


def setup_workflow_symlinks(
    base_dir: Path,
    repo_root: Path,
    link_mode: str = "files",
    force: bool = False,
    dry_run: bool = False,
) -> Tuple[int, List[str]]:
    workflows_dir = base_dir / "workflows"
    if not workflows_dir.exists():
        print(f"Error: Workflows directory not found at {workflows_dir}", file=sys.stderr)
        return 1, []

    workflow_files = sorted(workflows_dir.glob("*.yml"))
    if not workflow_files:
        print(f"Error: No workflow .yml files found in {workflows_dir}", file=sys.stderr)
        return 1, []

    github_dir = repo_root / ".github"
    target_workflows_dir = github_dir / "workflows"
    created_links: List[str] = []

    if link_mode == "dir":
        rel_target = os.path.relpath(workflows_dir, github_dir)
        rel_link_display = str(target_workflows_dir.relative_to(repo_root))
        if dry_run:
            print(f"[dry-run] Would symlink directory {rel_link_display} -> {rel_target}")
            return 0, [rel_link_display]

        github_dir.mkdir(parents=True, exist_ok=True)
        if target_workflows_dir.is_symlink():
            current_target = os.readlink(target_workflows_dir)
            if current_target == rel_target:
                print(f"Workflow directory symlink already up to date: {rel_link_display} -> {rel_target}")
                return 0, [rel_link_display]
            if force:
                target_workflows_dir.unlink()
            else:
                print(
                    f"Error: {rel_link_display} already points to '{current_target}'. Use --force to overwrite.",
                    file=sys.stderr,
                )
                return 1, []
        elif target_workflows_dir.exists():
            if force:
                shutil.rmtree(target_workflows_dir)
            else:
                print(
                    f"Error: {rel_link_display} already exists as a directory. "
                    "Use --link-mode files (default) or pass --force.",
                    file=sys.stderr,
                )
                return 1, []

        os.symlink(rel_target, target_workflows_dir)
        print(f"Created workflow directory symlink: {rel_link_display} -> {rel_target}")
        return 0, [rel_link_display]

    # Default: link_mode == "files" (symlinks each *.yml file into .github/workflows/)
    if not dry_run:
        if target_workflows_dir.is_symlink():
            if force:
                target_workflows_dir.unlink()
            else:
                rel_link_display = str(target_workflows_dir.relative_to(repo_root))
                print(
                    f"Workflow directory is already a symlink: {rel_link_display} -> {os.readlink(target_workflows_dir)}"
                )
                return 0, [rel_link_display]
        target_workflows_dir.mkdir(parents=True, exist_ok=True)

    for wf_file in workflow_files:
        dest_link = target_workflows_dir / wf_file.name
        rel_source = os.path.relpath(wf_file, target_workflows_dir)
        rel_dest_display = str(dest_link.relative_to(repo_root))

        if dry_run:
            print(f"[dry-run] Would create workflow symlink: {rel_dest_display} -> {rel_source}")
            created_links.append(rel_dest_display)
            continue

        if dest_link.is_symlink() or dest_link.exists():
            if dest_link.is_symlink() and os.readlink(dest_link) == rel_source:
                print(f"Workflow symlink already up to date: {rel_dest_display} -> {rel_source}")
                created_links.append(rel_dest_display)
                continue
            if force:
                dest_link.unlink()
            else:
                print(
                    f"Error: {rel_dest_display} already exists. Re-run with --force to replace it with a symlink.",
                    file=sys.stderr,
                )
                return 1, created_links

        os.symlink(rel_source, dest_link)
        print(f"Created workflow symlink: {rel_dest_display} -> {rel_source}")
        created_links.append(rel_dest_display)

    return 0, created_links


def detect_github_repo(repo_root: Path, explicit_repo: Optional[str] = None) -> Tuple[Optional[str], Optional[str]]:
    if explicit_repo:
        if "/" in explicit_repo:
            owner, repo = explicit_repo.split("/", 1)
            return owner.strip(), repo.strip()
        return None, explicit_repo.strip()

    try:
        res = subprocess.run(
            ["git", "-C", str(repo_root), "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode == 0 and res.stdout.strip():
            remote_url = res.stdout.strip()
            m = re.search(r"github\.com[:/]([^/]+)/([^/\s]+?)(?:\.git)?$", remote_url)
            if m:
                return m.group(1), m.group(2)
    except FileNotFoundError:
        pass

    if shutil.which("gh"):
        try:
            res = subprocess.run(
                ["gh", "repo", "view", "--json", "owner,name"],
                cwd=str(repo_root),
                capture_output=True,
                text=True,
                check=False,
            )
            if res.returncode == 0 and res.stdout.strip():
                data = json.loads(res.stdout)
                owner = (data.get("owner") or {}).get("login")
                name = data.get("name")
                if owner and name:
                    return owner, name
        except Exception:
            pass

    return None, None


def detect_github_owner(repo_root: Path, explicit_owner: Optional[str], detected_owner: Optional[str]) -> Optional[str]:
    if explicit_owner:
        return explicit_owner.strip()
    if detected_owner:
        return detected_owner
    if shutil.which("gh"):
        try:
            res = subprocess.run(
                ["gh", "api", "user", "--jq", ".login"],
                cwd=str(repo_root),
                capture_output=True,
                text=True,
                check=False,
            )
            if res.returncode == 0 and res.stdout.strip():
                return res.stdout.strip()
        except Exception:
            pass
    return None


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
            "Warning: GitHub CLI ('gh') is not installed. "
            "Workflow symlinks were created locally; install 'gh' and re-run 'doc2gh.py init' "
            "to create the GitHub Project.",
            file=sys.stderr,
        )
        return 0, project_meta

    auth_check = subprocess.run(
        ["gh", "auth", "status"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
    )
    if auth_check.returncode != 0:
        print(
            "Warning: GitHub CLI ('gh') is not authenticated (or missing 'project' scope). "
            "Workflow symlinks were created locally.\n"
            "To create and link the GitHub Project on GitHub, authenticate with:\n"
            "  gh auth login --scopes repo,project,read:org\n"
            "and re-run: python3 tools/doc2gh.py init",
            file=sys.stderr,
        )
        return 0, project_meta

    if not owner:
        print(
            "Warning: Could not auto-detect GitHub owner/organization. "
            "Pass --owner <owner> (and optionally --repo <owner/repo>) to create the GitHub Project.",
            file=sys.stderr,
        )
        return 0, project_meta

    # 1. Check if a GitHub Project with this title already exists for the owner
    existing_project: Optional[Dict[str, Any]] = None
    list_res = subprocess.run(
        ["gh", "project", "list", "--owner", owner, "--format", "json"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
    )
    if list_res.returncode == 0 and list_res.stdout.strip():
        try:
            parsed_list = json.loads(list_res.stdout)
            projects = parsed_list.get("projects", []) if isinstance(parsed_list, dict) else []
            for proj in projects:
                if proj.get("title") == project_title:
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

    # 2. Link the GitHub Project to the repository and configure labels/items if repo_name is known
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
            else:
                print(
                    f"Note: Could not link Project #{proj_num} to '{full_repo}': {link_err}",
                    file=sys.stderr,
                )

        if not skip_labels:
            synced_labels = 0
            for label_name, color, description in DEFAULT_LABELS:
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
            print(f"Synchronized {synced_labels}/{len(DEFAULT_LABELS)} doc2gh labels in '{full_repo}'.")

        item_urls = collect_tracked_issue_or_pr_urls(base_dir, owner, repo_name)
        for item_url in item_urls:
            add_res = subprocess.run(
                [
                    "gh",
                    "project",
                    "item-add",
                    proj_num,
                    "--owner",
                    owner,
                    "--url",
                    item_url,
                ],
                cwd=str(repo_root),
                capture_output=True,
                text=True,
                check=False,
            )
            if add_res.returncode == 0:
                print(f"Added '{item_url}' to GitHub Project #{proj_num}.")

    return 0, project_meta


def cmd_init(args: argparse.Namespace) -> int:
    base_dir = get_base_dir(args.root)
    repo_root = get_repo_root(base_dir, args.repo_root)

    # 1. Create symbolic links for GitHub Actions workflows in .github/workflows/
    rc, symlinks = setup_workflow_symlinks(
        base_dir=base_dir,
        repo_root=repo_root,
        link_mode=args.link_mode,
        force=args.force,
        dry_run=args.dry_run,
    )
    if rc != 0:
        return rc

    # 2. Detect GitHub repository and owner
    detected_owner, detected_repo = detect_github_repo(repo_root, args.repo)
    owner = detect_github_owner(repo_root, args.owner, detected_owner)
    repo_name = detected_repo or repo_root.name
    project_title = args.project_title or f"{repo_name} - doc2gh Governance"

    # 3. Create / configure the GitHub Project to manage GitHub tools (Issues, PRs, Labels, Workflows)
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
            return gh_rc
    else:
        print("Skipped GitHub Project creation (--skip-github).")

    # 4. Persist doc2gh configuration metadata (.doc2gh.json)
    config_path = base_dir / ".doc2gh.json"
    existing_cfg: Dict[str, Any] = {}
    if config_path.exists():
        try:
            existing_cfg = json.loads(config_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            existing_cfg = {}

    config_data: Dict[str, Any] = {
        "owner": project_meta.get("owner") or existing_cfg.get("owner", ""),
        "repo": project_meta.get("repo") or existing_cfg.get("repo", ""),
        "project_title": project_meta.get("project_title") or existing_cfg.get("project_title", project_title),
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
        print(f"[dry-run] Would write configuration to {config_path.relative_to(base_dir)}")
    else:
        config_path.write_text(json.dumps(config_data, indent=2) + "\n", encoding="utf-8")
        print(f"Saved doc2gh project configuration to {config_path.relative_to(repo_root)}")

    return 0


CLOSED_DOCUMENT_STATUSES = {
    "done",
    "archived",
    "rejected",
    "superseded",
    "deprecated",
    "implemented",
}


def sync_document_to_github(base_dir: Path, doc_path: Path, explicit_repo: Optional[str] = None) -> int:
    """Synchronize a local document's status and metadata to its GitHub Issue and Project via `gh`."""
    if not shutil.which("gh"):
        print("Warning: 'gh' CLI not found; skipping GitHub Issue/Project synchronization.", file=sys.stderr)
        return 0

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
    cfg_data: Dict[str, Any] = {}
    if config_path.exists():
        try:
            cfg_data = json.loads(config_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            cfg_data = {}

    owner, repo_name = detect_github_repo(repo_root, explicit_repo or cfg_data.get("repo"))
    if not owner or not repo_name:
        print(
            "Warning: Could not determine GitHub repository (OWNER/REPO) for synchronization.",
            file=sys.stderr,
        )
        return 0

    full_repo = f"{owner}/{repo_name}"
    issue_title = f"[{doc_id}] {title}"
    type_label = doc_type.lower()
    status_label = f"status:{status}"
    rel_doc_path = str(doc_path.relative_to(repo_root))

    body_lines = [
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
        ]
    )
    body = "\n".join(body_lines)

    issue_num: Optional[str] = None
    m_issue = re.match(r"^#?(\d+)$", github_issue)
    if m_issue:
        issue_num = m_issue.group(1)
    else:
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
                "number,title",
            ],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=False,
        )
        if search_res.returncode == 0 and search_res.stdout.strip():
            try:
                found_issues = json.loads(search_res.stdout)
                for item in found_issues:
                    if (item.get("title") or "").startswith(f"[{doc_id}]"):
                        issue_num = str(item.get("number"))
                        break
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
                body,
                "--label",
                f"{type_label},{status_label}",
            ],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=False,
        )
        if create_res.returncode == 0:
            out_url = create_res.stdout.strip()
            m_url = re.search(r"/issues/(\d+)$", out_url)
            if m_url:
                issue_num = m_url.group(1)
                apply_document_updates(doc_path, issue=f"#{issue_num}", skip_if_unchanged=True)
                print(f"Created and linked GitHub Issue #{issue_num} for {doc_id}.")
    else:
        subprocess.run(
            [
                "gh",
                "issue",
                "edit",
                issue_num,
                "--repo",
                full_repo,
                "--title",
                issue_title,
                "--body",
                body,
                "--add-label",
                f"{type_label},{status_label}",
            ],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=False,
        )
        state_cmd = "close" if status in CLOSED_DOCUMENT_STATUSES else "reopen"
        subprocess.run(
            ["gh", "issue", state_cmd, issue_num, "--repo", full_repo],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=False,
        )
        apply_document_updates(doc_path, issue=f"#{issue_num}", skip_if_unchanged=True)
        print(f"Synchronized {doc_id} with GitHub Issue #{issue_num} ({status_label}).")

    if issue_num and cfg_data.get("project_number") and cfg_data.get("owner"):
        issue_url = f"https://github.com/{full_repo}/issues/{issue_num}"
        subprocess.run(
            [
                "gh",
                "project",
                "item-add",
                str(cfg_data["project_number"]),
                "--owner",
                str(cfg_data["owner"]),
                "--url",
                issue_url,
            ],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=False,
        )

    return 0


def cmd_sync(args: argparse.Namespace) -> int:
    base_dir = get_base_dir(args.root)
    if args.document:
        try:
            doc_path = resolve_doc_path(base_dir, args.document)
        except FileNotFoundError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        return sync_document_to_github(base_dir, doc_path, explicit_repo=args.repo)

    rc = 0
    for cfg in DOC_CONFIG.values():
        folder = base_dir / cfg["dir"]
        if not folder.exists():
            continue
        for md_file in sorted(folder.glob("*.md")):
            if md_file.name in ("README.md", "template.md"):
                continue
            if sync_document_to_github(base_dir, md_file, explicit_repo=args.repo) != 0:
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
    doc_ids = {m.upper() for m in re.findall(r"\b(?:ADR|RFC|SPEC)-\d{4}\b", combined_text, flags=re.IGNORECASE)}

    for doc_id in sorted(doc_ids):
        try:
            resolved = resolve_doc_path(base_dir, doc_id)
            if resolved not in seen:
                seen.add(resolved)
                matched_paths.append(resolved)
        except FileNotFoundError:
            pass

    if modified_files:
        repo_root = get_repo_root(base_dir)
        for rel_file in modified_files:
            candidate = (repo_root / rel_file).resolve()
            if (
                candidate.exists()
                and candidate.suffix == ".md"
                and candidate.name not in ("README.md", "template.md")
                and candidate.parent.name in DIR_TO_TYPE
            ):
                try:
                    candidate.relative_to(base_dir)
                except ValueError:
                    continue
                if candidate not in seen:
                    seen.add(candidate)
                    matched_paths.append(candidate)

    for cfg in DOC_CONFIG.values():
        folder = base_dir / cfg["dir"]
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
        help="Initialize doc2gh in the repository: create GitHub Project, provision labels, and symlink workflows into .github/workflows/.",
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
        help="GitHub user or organization login for the GitHub Project (auto-detected if omitted).",
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
        help="Overwrite existing workflow files or symlinks in .github/workflows/.",
    )
    p_init.add_argument(
        "--skip-github",
        dest="skip_github",
        action="store_true",
        help="Create workflow symbolic links and local config without executing GitHub CLI ('gh') commands.",
    )
    p_init.add_argument(
        "--skip-labels",
        dest="skip_labels",
        action="store_true",
        help="Skip creating/updating standard doc2gh labels on GitHub.",
    )
    p_init.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        help="Preview workflow symlinks and GitHub Project commands without applying changes.",
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


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

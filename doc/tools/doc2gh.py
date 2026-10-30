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
from pathlib import Path
import re
import sys
from typing import Dict, List, Optional, Tuple

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
    return 0


def apply_document_updates(
    doc_path: Path,
    new_status: Optional[str] = None,
    issue: Optional[str] = None,
    pr: Optional[str] = None,
    superseded_by: Optional[str] = None,
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
    updated_at = today
    github_issue = issue if issue is not None else fields.get("github_issue", "")
    github_pr = pr if pr is not None else fields.get("github_pr", "")
    sup_by = (
        superseded_by
        if superseded_by is not None
        else fields.get("superseded_by", "")
    )

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

    return apply_document_updates(
        doc_path=doc_path,
        new_status=args.status,
        issue=args.issue,
        pr=args.pr,
        superseded_by=args.superseded_by,
    )


def cmd_link(args: argparse.Namespace) -> int:
    base_dir = get_base_dir(args.root)
    try:
        doc_path = resolve_doc_path(base_dir, args.document)
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    return apply_document_updates(
        doc_path=doc_path,
        new_status=None,
        issue=args.issue,
        pr=args.pr,
        superseded_by=None,
    )


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

    # new
    p_new = subparsers.add_parser("new", help="Create a new ADR, RFC, or Spec from template.")
    p_new.add_argument("type", choices=["adr", "rfc", "spec"], help="Document type.")
    p_new.add_argument("title", help="Document title.")
    p_new.add_argument("--status", help="Initial status (defaults to type default).")
    p_new.add_argument("--issue", help="GitHub Issue reference (e.g. '#12').")
    p_new.add_argument("--pr", help="GitHub Pull Request reference (e.g. '#15').")
    p_new.add_argument("--number", type=int, help="Explicit sequence number (defaults to next available).")
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
    p_status.set_defaults(func=cmd_status)

    # link
    p_link = subparsers.add_parser(
        "link", help="Update GitHub Issue and/or Pull Request references in the managed section."
    )
    p_link.add_argument("document", help="Document path or ID (e.g. 'SPEC-0001').")
    p_link.add_argument("--issue", help="GitHub Issue reference (e.g. '#20').")
    p_link.add_argument("--pr", help="GitHub PR reference (e.g. '#25').")
    p_link.set_defaults(func=cmd_link)

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

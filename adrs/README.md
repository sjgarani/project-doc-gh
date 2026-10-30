# Architecture Decision Records (ADRs)

This directory contains the project's **Architecture Decision Records (ADRs)**. An ADR captures a significant architectural decision, the context and problem it addresses, the options evaluated, and the resulting consequences.

---

## Lifecycle & Statuses

All status changes **must** be executed using `python3 tools/doc2gh.py`. Do not edit the `status` field or the **Document Management** section manually.

| Status | Description |
| :--- | :--- |
| `proposed` | Decision is under review via a Pull Request. |
| `accepted` | Decision is approved and active. Developers and AI agents must follow its rules. |
| `deprecated` | Decision is no longer relevant because the underlying system or feature was retired. |
| `superseded` | Decision has been replaced by a newer ADR (requires `--superseded-by ADR-NNNN`). |

---

## Naming Convention

Files follow a 4-digit sequential number in `kebab-case`, generated automatically by `tools/doc2gh.py`:

```text
NNNN-short-decision-title.md
```

**Examples:**
- `0001-adopt-doc2gh-documentation-architecture.md`
- `0002-use-postgresql-as-primary-database.md`

---

## Creating and Updating ADRs

```bash
# 1. Create a new ADR from template
python3 tools/doc2gh.py new adr "Use PostgreSQL as Primary Database" --issue "#12"

# 2. Mark the ADR as accepted once the PR is approved
python3 tools/doc2gh.py status ADR-0001 accepted --pr "#15"

# 3. Supersede an older ADR when a new decision replaces it
python3 tools/doc2gh.py status ADR-0001 superseded --superseded-by ADR-0002
```

---

## GitHub & AI Agent Integration

1. **Pull Requests & Issues**:
   - Every ADR links to its originating GitHub Issue (`github_issue`) and review Pull Request (`github_pr`) inside the managed section.
   - When merged to the default branch, `doc-sync-issues.yml` automatically synchronizes the tracking GitHub Issue and its `status:*` label.
2. **Instructions for AI Agents**:
   - Query active decisions with `python3 tools/doc2gh.py list --type adr --status accepted`.
   - Enforce all rules listed under **Compliance & Validation (AI & Code Review)** when generating or reviewing code.
   - Never alter the core decision of an `accepted` ADR; instead, create a new ADR via `tools/doc2gh.py new adr` and mark the previous one as `superseded`.

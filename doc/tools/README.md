# doc2gh Python CLI (`tools/doc2gh.py`)

`doc2gh.py` is a zero-dependency **Python 3** command-line utility responsible for creating documents and managing the **Document Management** area (status, dates, and GitHub Issue/PR links) across all **ADRs**, **RFCs**, and **Specs**.

---

## Why Use This Tool?

Every document in **doc2gh** contains two synchronized, machine-managed regions that **must not be edited manually**:

1. **Managed YAML Frontmatter Fields**: `id`, `type`, `title`, `status`, `created_at`, `updated_at`, `github_issue`, `github_pr`, and `superseded_by`.
2. **Managed Markdown Section**: Delimited by `<!-- DOC2GH:MANAGEMENT:START ... -->` and `<!-- DOC2GH:MANAGEMENT:END -->`, rendering a read-only governance table directly inside the document.

If either region is edited by hand and falls out of sync, the CI validation workflow (`doc-lint.yml`) will reject the change. Always use `python3 tools/doc2gh.py` (or `python3 doc/tools/doc2gh.py` when imported via Git Subtree) to manipulate document status or GitHub links.

---

## Commands & Usage

### 1. Create a New Document (`new`)

Generates a new document from the corresponding `template.md`, assigns the next 4-digit sequence ID (`0001`, `0002`, ...), sets the initial status, and populates the managed areas:

```bash
# Create an ADR (default status: proposed)
python3 tools/doc2gh.py new adr "Adopt PostgreSQL as Primary Store" --issue "#12"

# Create an RFC (default status: draft)
python3 tools/doc2gh.py new rfc "Event-Driven Notification Pipeline" --issue "#18"

# Create a Spec (default status: draft)
python3 tools/doc2gh.py new spec "User Registration Endpoint" --issue "#22"
```

### 2. Transition Document Status (`status`)

Updates the document status (validating allowed statuses for its type), refreshes `updated_at`, and regenerates the managed block:

```bash
# Accept an ADR and link the approval PR
python3 tools/doc2gh.py status ADR-0001 accepted --pr "#15"

# Supersede an existing ADR with a newer one
python3 tools/doc2gh.py status ADR-0001 superseded --superseded-by ADR-0003

# Move an RFC to review or approved
python3 tools/doc2gh.py status RFC-0001 review --pr "#19"

# Move a Spec through its lifecycle (draft -> ready -> in-progress -> done)
python3 tools/doc2gh.py status SPEC-0001 in-progress --pr "#25"
```

> You can reference a document either by its ID (`ADR-0001`, `RFC-0001`, `SPEC-0001`) or by its file path (`adrs/0001-adopt-postgresql-as-primary-store.md`).

### 3. Link GitHub Issues and Pull Requests (`link`)

Updates the `github_issue` and/or `github_pr` references without changing the document status:

```bash
python3 tools/doc2gh.py link SPEC-0001 --issue "#22" --pr "#27"
```

### 4. Validate All Documents (`validate`)

Checks file naming conventions, valid statuses, YAML frontmatter completeness, and verifies that the `DOC2GH:MANAGEMENT` section matches the frontmatter byte-for-byte:

```bash
# Validate all created documents
python3 tools/doc2gh.py validate

# Also validate the template.md files
python3 tools/doc2gh.py validate --include-templates
```

### 5. List Documents (`list`)

Outputs a summary table or JSON array (used by GitHub Actions and AI agents):

```bash
# Human-readable table
python3 tools/doc2gh.py list

# Filter by type or status
python3 tools/doc2gh.py list --type spec --status ready

# JSON output for automation and AI agents
python3 tools/doc2gh.py list --format json
```

---

## Allowed Status Values by Document Type

| Document Type | Directory | Default Status | Allowed Statuses |
| :--- | :--- | :--- | :--- |
| **ADR** | `adrs/` | `proposed` | `proposed`, `accepted`, `deprecated`, `superseded` |
| **RFC** | `rfcs/` | `draft` | `draft`, `review`, `approved`, `rejected`, `implemented` |
| **Spec** | `specs/` | `draft` | `draft`, `ready`, `in-progress`, `done`, `archived` |


# doc2gh

Software documentation architecture designed for **AI-driven development** and seamless integration with **GitHub** (Issues, Projects, Pull Requests, and Actions), built to be embedded into target repositories via **Git Subtree**.

---

## Overview

**doc2gh** provides a structured, traceable, and enforceable documentation model for software engineering projects:

1. **Three Core Document Types**:
   - **RFCs (`rfcs/`)**: Technical proposals and design discussions reviewed through Pull Requests.
   - **ADRs (`adrs/`)**: Immutable Architecture Decision Records capturing key architectural choices and constraints.
   - **Specs (`specs/`)**: Executable functional and technical specifications with task breakdowns for developers and AI agents.
2. **CLI-Managed Governance (`tools/doc2gh.py`)**:
   - Every document contains a dedicated **Document Management** section (and synchronized YAML Frontmatter) that tracks status, timestamps, and GitHub Issue/PR links.
   - This management area **must not be edited manually**—all status transitions and GitHub metadata updates are performed through the included Python 3 CLI (`tools/doc2gh.py`).
3. **GitHub & AI Integration**:
   - `doc2gh.py init` validates local documentation, prepares or reuses the GitHub repository, activates GitHub Actions workflows via relative symlinks, provisions the GitHub Project and labels, and reconciles documents with tracking Issues and optional Pull Requests.
   - GitHub Actions workflows automatically validate document structure and management blocks, synchronize documents bidirectionally with GitHub Issues and PRs, and post traceability summaries on Pull Requests.
4. **Git Subtree Ready**:
   - The root of this project represents the exact directory tree to be mounted into a host project's documentation folder (e.g., `doc/` or `docs/`).

---

## Directory Structure

```text
.
├── README.md               # Architecture overview, AI guidelines, and Git Subtree usage
├── adrs/                   # Architecture Decision Records
│   ├── README.md           # ADR lifecycle, naming conventions, and AI rules
│   └── template.md         # Standard ADR template with managed governance block
├── rfcs/                   # Requests for Comments
│   ├── README.md           # RFC lifecycle, review workflow, and AI guidelines
│   └── template.md         # Standard RFC template with managed governance block
├── specs/                  # Technical & Functional Specifications
│   ├── README.md           # Spec lifecycle, task breakdown, and AI execution guide
│   └── template.md         # Standard Spec template with managed governance block
├── tools/                  # Python 3 CLI for managing document status and metadata
│   ├── README.md           # CLI reference, permissions, and recovery guide
│   └── doc2gh.py           # Zero-dependency Python 3 management utility
└── workflows/              # GitHub Actions workflows for validation and bidirectional Issue/PR sync
    ├── README.md           # Setup and permissions guide for host repositories
    ├── doc-lint.yml        # Validates frontmatter, naming, and managed sections on PRs
    ├── doc-sync-issues.yml # Syncs document changes to GitHub Issues and Projects
    ├── gh-to-doc-sync.yml  # Syncs GitHub Issue/PR/comment events back into documents via doc2gh.py
    └── pr-doc-link.yml     # Posts document traceability summaries on Pull Requests
```

---

## Documentation & GitHub Workflow

```mermaid
flowchart LR
    CLI["tools/doc2gh.py<br/>Python 3 CLI"] --> RFC["RFC (rfcs/)<br/>Proposal & Review"]
    CLI --> ADR["ADR (adrs/)<br/>Architectural Decision"]
    CLI --> SPEC["Spec (specs/)<br/>Executable Specification"]
    RFC --> ADR
    RFC --> SPEC
    ADR --> SPEC
    SPEC --> ISSUE["GitHub Issues & Project<br/>Tracking & Tasks"]
    ISSUE --> PR["GitHub Pull Request<br/>Implementation (Dev / AI)"]
```

---

## Managing Document Status (`tools/doc2gh.py`)

Each document has a dedicated management region delimited by `<!-- DOC2GH:MANAGEMENT:START ... -->` and `<!-- DOC2GH:MANAGEMENT:END -->`, paired with managed YAML frontmatter fields. **Do not edit these areas manually.**

Use the bundled Python 3 tool (`tools/doc2gh.py` or `doc/tools/doc2gh.py` when mounted in `doc/`):

```bash
# Preview or run repository bootstrap (validates docs, prepares repo/Project/labels, symlinks workflows, syncs Issues)
python3 tools/doc2gh.py init --dry-run
python3 tools/doc2gh.py init

# Create a new document (auto-increments ID and initializes the managed section)
python3 tools/doc2gh.py new rfc "Async Webhook Delivery" --issue "#10"
python3 tools/doc2gh.py new adr "Use PostgreSQL for Transactional Storage" --issue "#12"
python3 tools/doc2gh.py new spec "Webhook Retry Worker" --issue "#15"

# Update document status and link Pull Requests / Issues
python3 tools/doc2gh.py status ADR-0001 accepted --pr "#14"
python3 tools/doc2gh.py status SPEC-0001 in-progress --pr "#18"

# Link or update GitHub Issue / PR references without changing status
python3 tools/doc2gh.py link SPEC-0001 --issue "#15" --pr "#18"

# Synchronize local documents to GitHub Issues & Project
python3 tools/doc2gh.py sync

# Validate all documents and templates
python3 tools/doc2gh.py validate --include-templates
```

See [`tools/README.md`](./tools/README.md) for the complete CLI reference, confirmation options, and recovery steps.

---

## Using as a Git Subtree

### 1. Add `doc2gh` to a Host Repository

From the root of the target repository, mount `doc2gh` into `doc` (or `docs`):

```bash
git subtree add --prefix=doc https://github.com/<org>/doc2gh.git main --squash
```

### 2. Bootstrap Repository, Workflows & GitHub Tracking (`init`)

Authenticate the GitHub CLI (`gh auth login --scopes repo,project,read:org`) and run `init`:

```bash
# Preview planned changes without modifying files or remote resources
python3 doc/tools/doc2gh.py init --dry-run

# Run full bootstrap (or pass --repo OWNER/REPO --yes if creating a new remote repository)
python3 doc/tools/doc2gh.py init
```

`init` validates local documents and templates, verifies or creates the GitHub repository (after confirmation), creates or repairs relative workflow symlinks in `.github/workflows/` (preserving any conflicting regular files), provisions the GitHub Project and labels, and reconciles local documents with GitHub Issues. On a feature branch, pass `--create-pr` to create or reuse a linked Pull Request.

See [`workflows/README.md`](./workflows/README.md) for required repository permissions and workflow conflict recovery.

### 3. Pull Upstream Updates from `doc2gh`

```bash
git subtree pull --prefix=doc https://github.com/<org>/doc2gh.git main --squash
```

### 4. Contribute Improvements Back to `doc2gh` (Optional)

```bash
git subtree push --prefix=doc https://github.com/<org>/doc2gh.git feature/update-templates
```

---

## Guidelines for AI Agents

When operating inside a repository powered by **doc2gh**, AI agents must follow these rules:

1. **Never manually edit the managed section**: Always invoke `python3 tools/doc2gh.py` (or `python3 doc/tools/doc2gh.py`) to create documents, transition `status`, or update `github_issue` / `github_pr` fields.
2. **Before writing code**:
   - Run `python3 tools/doc2gh.py list --type adr --status accepted` and read the accepted **ADRs** to respect active architectural constraints.
   - Read the target **Spec** in `specs/` to understand functional requirements, technical design, acceptance criteria, and task checklists.
3. **During and after implementation**:
   - Check off completed task items (`- [ ]` -> `- [x]`) in the Spec body.
   - Use `python3 tools/doc2gh.py status <DOC-ID> <new-status>` to reflect progress (`in-progress`, `done`, `implemented`).
   - Run `python3 tools/doc2gh.py validate --include-templates` after documentation changes.
   - Reference the document ID (`SPEC-NNNN`, `ADR-NNNN`, `RFC-NNNN`) and GitHub Issue (`#123`) in commit messages and Pull Request descriptions.

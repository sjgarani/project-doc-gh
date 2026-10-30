# doc2gh Python CLI (`tools/doc2gh.py`)

`doc2gh.py` is a zero-dependency **Python 3** command-line utility responsible for bootstrapping repositories (`init`), creating documents (`new`), managing the **Document Management** area (`status`, `link`), validating documents (`validate`), and synchronizing local documents with GitHub Issues, Projects, labels, and Pull Requests (`sync`, `gh-event`).

---

## Why Use This Tool?

Every document in **doc2gh** contains two synchronized, machine-managed regions that **must not be edited manually**:

1. **Managed YAML Frontmatter Fields**: `id`, `type`, `title`, `status`, `created_at`, `updated_at`, `github_issue`, `github_pr`, and `superseded_by`.
2. **Managed Markdown Section**: Delimited by `<!-- DOC2GH:MANAGEMENT:START ... -->` and `<!-- DOC2GH:MANAGEMENT:END -->`, rendering a read-only governance table directly inside the document.

If either region is edited by hand and falls out of sync, the CI validation workflow (`doc-lint.yml`) will reject the change. Always use `python3 tools/doc2gh.py` (or `python3 doc/tools/doc2gh.py` when imported via Git Subtree) to manipulate document status or GitHub links.

---

## Commands & Usage

### 1. Bootstrap Repository, Workflows & GitHub Integrations (`init`)

`init` performs an end-to-end, idempotent bootstrap in ordered phases:

1. **Local Validation Gate**: Validates all local ADRs, RFCs, Specs, and `template.md` files before any local or remote mutations. Validation errors stop setup immediately.
2. **Git & GitHub Preflight**: Verifies `git`, GitHub CLI (`gh`), authentication (`gh auth status`), repository permissions, and resolves `OWNER/REPO` from `origin` or explicit `--repo` / `--owner` options (never guessing the owner when remotes are missing, non-GitHub, or ambiguous).
3. **Safe Remote Repository Setup & Push**: Reuses an existing GitHub repository without rewriting history. If the target repository does not exist on GitHub, verifies a clean worktree and supported branch, requests explicit confirmation (`--yes` or interactive `[y/N]`), creates the repository, configures `origin`, and pushes the current branch without force-pushing.
4. **Workflow Symlink Inspection & Repair**: Creates or repairs relative symbolic links in `<repo_root>/.github/workflows/` pointing to `workflows/*.yml` (or `doc/workflows/*.yml` when installed under `doc/`), verifies link targets, and preserves any conflicting regular files or directories without overwriting them.
5. **GitHub Project & Label Provisioning**: Creates or reuses the repository's GitHub Project, links it to `OWNER/REPO`, and provisions the 16 standard `doc2gh` labels (`adr`, `rfc`, `spec`, and `status:*`).
6. **Configuration Persistence**: Saves repository, Project, and workflow link metadata to `.doc2gh.json`.
7. **Issue & Project Item Reconciliation**: Synchronizes every eligible ADR, RFC, and Spec to a GitHub Issue and Project item keyed by stable document ID (`[ADR-NNNN]`, `[RFC-NNNN]`, `[SPEC-NNNN]`), preserving manual Issue descriptions and unrelated labels, and records `github_issue` links in the documents.
8. **Optional Pull Request Creation/Reuse (`--create-pr`)**: Does not create a PR by default. When `--create-pr` (`--pr`) is explicitly passed on a non-default feature branch, creates or reuses an open PR and links `github_pr` in the relevant documents and tracking Issues.

```bash
# Preview all intended Git, repository, workflow, Project, label, and Issue changes (no writes)
python3 doc/tools/doc2gh.py init --dry-run

# Full initialization from the packaged doc/ subtree (or python3 tools/doc2gh.py init from root)
python3 doc/tools/doc2gh.py init

# Explicit target repository, Project title, and non-interactive confirmation for new remote creation/push
python3 doc/tools/doc2gh.py init --repo my-org/my-repo --project-title "Architecture & Specs" --yes

# Bootstrap on a feature branch and create/reuse a linked Pull Request
python3 doc/tools/doc2gh.py init --create-pr --yes

# Symlink the entire .github/workflows directory instead of individual .yml files
python3 doc/tools/doc2gh.py init --link-mode dir

# Only validate documents and configure workflow symlinks locally without calling GitHub CLI
python3 doc/tools/doc2gh.py init --skip-github
```

#### Prerequisites, Permissions & Confirmations

- **GitHub CLI Authentication**: Authenticate `gh` with repository, Project, and organization scopes:
  ```bash
  gh auth login --scopes repo,project,read:org
  # Or refresh an existing session if Project creation fails with missing scope:
  gh auth refresh -s project
  ```
- **Confirmations & Push Safety**: `init` requires explicit confirmation (via interactive prompt or `--yes` / `-y` / `--confirm`) before creating a missing remote GitHub repository or pushing a branch (`--push` / `--create-pr`). It checks for a clean working tree, active branch, non-conflicting `origin` remote, and supported default branch (`main` or `master`), and never force-pushes.

#### Recovery & Safe Retry After Partial Failures

If a network, permission, or conflict error occurs mid-setup, `init` prints a summary of completed actions and the failed phase. Because every phase is idempotent (reusing existing Projects by title, labels by name, Issues by `[DOC-ID]`, PRs by branch, and valid relative workflow links), resolve the reported error and re-run `python3 doc/tools/doc2gh.py init` safely without creating duplicates.

---

### 2. Create a New Document (`new`)

Generates a new document from the corresponding `template.md`, assigns the next 4-digit sequence ID (`0001`, `0002`, ...), sets the initial status, and populates the managed areas:

```bash
# Create an ADR (default status: proposed)
python3 doc/tools/doc2gh.py new adr "Adopt PostgreSQL as Primary Store" --issue "#12"

# Create an RFC (default status: draft)
python3 doc/tools/doc2gh.py new rfc "Event-Driven Notification Pipeline" --issue "#18"

# Create a Spec (default status: draft) and immediately sync to GitHub Issues/Project
python3 doc/tools/doc2gh.py new spec "User Registration Endpoint" --sync-github
```

### 3. Transition Document Status (`status`)

Updates the document status (validating allowed statuses for its type), refreshes `updated_at`, and regenerates the managed block:

```bash
# Accept an ADR and link the approval PR
python3 doc/tools/doc2gh.py status ADR-0001 accepted --pr "#15"

# Supersede an existing ADR with a newer one
python3 doc/tools/doc2gh.py status ADR-0001 superseded --superseded-by ADR-0003

# Move an RFC to review or approved
python3 doc/tools/doc2gh.py status RFC-0001 review --pr "#19"

# Move a Spec through its lifecycle (draft -> ready -> in-progress -> done)
python3 doc/tools/doc2gh.py status SPEC-0001 in-progress --pr "#25" --sync-github
```

> You can reference a document either by its ID (`ADR-0001`, `RFC-0001`, `SPEC-0001`) or by its file path (`adrs/0001-adopt-postgresql-as-primary-store.md`).

### 4. Link GitHub Issues and Pull Requests (`link`)

Updates the `github_issue` and/or `github_pr` references without changing the document status:

```bash
python3 doc/tools/doc2gh.py link SPEC-0001 --issue "#22" --pr "#27"
```

### 5. Validate All Documents (`validate`)

Checks file naming conventions, valid statuses, duplicate IDs, YAML frontmatter completeness, and verifies that the `DOC2GH:MANAGEMENT` section matches the frontmatter byte-for-byte:

```bash
# Validate all created documents
python3 doc/tools/doc2gh.py validate

# Also validate the template.md files
python3 doc/tools/doc2gh.py validate --include-templates
```

### 6. List Documents (`list`)

Outputs a summary table or JSON array (used by GitHub Actions and AI agents):

```bash
# Human-readable table
python3 doc/tools/doc2gh.py list

# Filter by type or status
python3 doc/tools/doc2gh.py list --type spec --status ready

# JSON output for automation and AI agents
python3 doc/tools/doc2gh.py list --format json
```

### 7. Bidirectional GitHub Synchronization (`sync` & `gh-event`)

`doc2gh.py` guarantees the exact same validation and management block rules whether changes originate in the CLI or in GitHub Issues and Pull Requests:

```bash
# Push local document status/links directly to GitHub Issues & Project via 'gh'
python3 doc/tools/doc2gh.py sync
python3 doc/tools/doc2gh.py sync SPEC-0001

# Preview Issue synchronization without writing to GitHub
python3 doc/tools/doc2gh.py sync --dry-run

# Apply GitHub Issue, Pull Request, or Comment (/doc2gh) events back into documents
# (Invoked automatically by workflows/gh-to-doc-sync.yml)
python3 doc/tools/doc2gh.py gh-event
```

Supported GitHub-to-Document transitions via `gh-event` (and `workflows/gh-to-doc-sync.yml`):
- **Issue opened / edited / labeled `status:<value>`**: Links `github_issue: "#<N>"`, validates `<value>` against the document's allowed statuses, updates the document's frontmatter and `DOC2GH:MANAGEMENT` block, and validates the resulting file.
- **Issue closed / reopened**: Transitions the document to its closed state (`done` / `implemented` / `accepted`, or `archived` / `rejected` / `deprecated` if closed as *not planned*) or active state when reopened.
- **Pull Request opened / merged**: Automatically links `github_pr: "#<N>"`, moves `draft`/`ready` RFCs and Specs to `review`/`in-progress` when opened, and transitions ADRs (`accepted`), RFCs (`approved`), and Specs (`done`) when merged.
- **Slash commands in Issue/PR comments**: Commenting `/doc2gh status SPEC-0001 done` or `/doc2gh link ADR-0001 --issue #12` runs `doc2gh.py` directly on the document and validates it.

---

## Allowed Status Values by Document Type

| Document Type | Directory | Default Status | Allowed Statuses |
| :--- | :--- | :--- | :--- |
| **ADR** | `adrs/` | `proposed` | `proposed`, `accepted`, `deprecated`, `superseded` |
| **RFC** | `rfcs/` | `draft` | `draft`, `review`, `approved`, `rejected`, `implemented` |
| **Spec** | `specs/` | `draft` | `draft`, `ready`, `in-progress`, `done`, `archived` |

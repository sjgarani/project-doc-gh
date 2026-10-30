# GitHub Actions Workflows (doc2gh)

This directory contains the GitHub Actions workflows that connect **doc2gh** documents (`adrs/`, `rfcs/`, `specs/`) and the Python 3 management CLI (`tools/doc2gh.py`) with **GitHub Issues**, **Projects**, and **Pull Requests**.

---

## Included Workflows

| File | Trigger | Responsibility |
| :--- | :--- | :--- |
| [`doc-lint.yml`](./doc-lint.yml) | `pull_request` / `push` | Runs `python3 tools/doc2gh.py validate --include-templates` to verify YAML frontmatter, file naming, valid statuses, and the integrity of the managed `DOC2GH:MANAGEMENT` section. |
| [`doc-sync-issues.yml`](./doc-sync-issues.yml) | `push` to default branch / `workflow_dispatch` | Queries `tools/doc2gh.py list --format json` and automatically creates or updates corresponding GitHub Issues with `adr`, `rfc`, `spec`, and `status:*` labels while preserving manual Issue descriptions and unrelated labels. |
| [`gh-to-doc-sync.yml`](./gh-to-doc-sync.yml) | `issues` / `pull_request` / `issue_comment` | Executes `python3 tools/doc2gh.py gh-event` when Issues are labeled/closed/reopened, when PRs are opened/merged, or when `/doc2gh` slash commands are commented, validates the updated documents, and commits back. |
| [`pr-doc-link.yml`](./pr-doc-link.yml) | `pull_request` | Detects modified or referenced documents (`ADR-NNNN`, `RFC-NNNN`, `SPEC-NNNN`) in Pull Requests and posts an automated traceability comment for reviewers and AI agents. |

---

## Activating & Repairing Workflows in a Host Repository (`init`)

GitHub Actions only executes workflows located inside `.github/workflows/` at the root of the repository. Run `doc2gh.py init` to automatically inspect, create, or repair relative symbolic links in `.github/workflows/` (and set up the repository's GitHub Project, labels, and tracking Issues):

```bash
# Preview workflow symlinks and GitHub setup without applying changes
python3 doc/tools/doc2gh.py init --dry-run

# When doc2gh is added via Git Subtree under doc/
python3 doc/tools/doc2gh.py init

# When running at repository root
python3 tools/doc2gh.py init
```

### Link Repair & Conflict Handling

- **Relative Links**: `init` creates relative symlinks (for example, `.github/workflows/doc-lint.yml -> ../../doc/workflows/doc-lint.yml`) and verifies that each link resolves to the matching workflow source.
- **Automatic Repair**: Missing, broken, or misdirected symlinks at expected workflow paths are automatically repaired on subsequent `init` runs.
- **Conflict Preservation**: If a regular file or directory already exists at an expected workflow link path in `.github/workflows/`, `init` preserves it untouched, reports the conflict, and exits with a nonzero code so custom workflows are never overwritten silently. Remove or rename the conflicting file and re-run `init` to complete activation.
- **Directory Link Mode & Local-Only Mode**: You can symlink the entire `.github/workflows` directory with `--link-mode dir`, or create/repair only the workflow symlinks locally without calling `gh` using `--skip-github`.

> **Automatic Subtree Detection**: Every workflow automatically locates `tools/doc2gh.py` whether it lives at the repository root (`tools/doc2gh.py`) or inside a subtree directory (`doc/tools/doc2gh.py` or `docs/tools/doc2gh.py`).

---

## Required GitHub Repository & CLI Permissions

1. **GitHub Actions Workflow Permissions**:
   Each workflow declares least-required `permissions:` in its YAML header. Ensure **Read and write permissions** are enabled in your repository settings (**Settings > Actions > General > Workflow permissions**) so workflows can:
   - Validate and commit synchronized document metadata (`contents: write` in `gh-to-doc-sync.yml`, `contents: read` in read-only workflows)
   - Create and update tracking Issues and labels (`issues: write`)
   - Post and update traceability comments on Pull Requests (`pull-requests: write`)
2. **GitHub CLI (`gh`) Scopes for `init` and `sync`**:
   Authenticate `gh` with `repo`, `project`, and `read:org` scopes (`gh auth login --scopes repo,project,read:org`). Never hardcode or commit credentials or tokens.

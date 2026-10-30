# GitHub Actions Workflows (doc2gh)

This directory contains the GitHub Actions workflows that connect **doc2gh** documents (`adrs/`, `rfcs/`, `specs/`) and the Python 3 management CLI (`tools/doc2gh.py`) with **GitHub Issues** and **Pull Requests**.

---

## Included Workflows

| File | Trigger | Responsibility |
| :--- | :--- | :--- |
| [`doc-lint.yml`](./doc-lint.yml) | `pull_request` / `push` | Runs `python3 tools/doc2gh.py validate --include-templates` to verify YAML frontmatter, file naming, valid statuses, and the integrity of the managed `DOC2GH:MANAGEMENT` section. |
| [`doc-sync-issues.yml`](./doc-sync-issues.yml) | `push` to default branch / `workflow_dispatch` | Queries `tools/doc2gh.py list --format json` and automatically creates or updates corresponding GitHub Issues with `adr`, `rfc`, `spec`, and `status:*` labels. |
| [`pr-doc-link.yml`](./pr-doc-link.yml) | `pull_request` | Detects modified or referenced documents (`ADR-NNNN`, `RFC-NNNN`, `SPEC-NNNN`) in Pull Requests and posts an automated traceability comment for reviewers and AI agents. |

---

## Activating Workflows in a Host Repository (Git Subtree)

GitHub Actions only executes workflows located inside `.github/workflows/` at the root of the repository. When **doc2gh** is added via Git Subtree (for example, under `doc/`), copy the workflow files into `.github/workflows/`:

```bash
mkdir -p .github/workflows
cp doc/workflows/*.yml .github/workflows/
```

> **Automatic Subtree Detection**: Every workflow automatically locates `tools/doc2gh.py` whether it lives at the repository root (`tools/doc2gh.py`) or inside a subtree directory (`doc/tools/doc2gh.py` or `docs/tools/doc2gh.py`).

---

## Required GitHub Repository Permissions

Each workflow declares minimal `permissions:` in its YAML header. Ensure that **Read and write permissions** are enabled in your repository settings (**Settings > Actions > General > Workflow permissions**) so that the workflows can:
- Create and update tracking Issues and labels (`issues: write`)
- Post and update traceability comments on Pull Requests (`pull-requests: write`)

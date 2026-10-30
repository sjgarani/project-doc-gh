---
# ============================================================================
# MANAGED BY doc2gh CLI (tools/doc2gh.py) — DO NOT EDIT THIS BLOCK MANUALLY
# ============================================================================
id: SPEC-0001
type: spec
title: "Expand init to bootstrap GitHub repository and synchronize documentation"
status: done
created_at: 2026-10-30
updated_at: 2026-10-30
github_issue: ""
github_pr: ""
# ============================================================================
owners:
  - "@github-username"
related_rfcs: []
related_adrs: []
tags: []
---
# SPEC-0001: Expand init to bootstrap GitHub repository and synchronize documentation

<!-- DOC2GH:MANAGEMENT:START - DO NOT EDIT THIS SECTION MANUALLY. Use `python3 tools/doc2gh.py` to manage status and GitHub links. -->
## Document Management (Managed by doc2gh)

> [!WARNING]
> **Do not edit this section or the managed frontmatter fields manually.**
> All status transitions and GitHub tracking links must be updated via `python3 tools/doc2gh.py`.

| Field | Value |
| :--- | :--- |
| **Document ID** | `SPEC-0001` |
| **Type** | `SPEC` |
| **Status** | `done` |
| **Created At** | `2026-10-30` |
| **Updated At** | `2026-10-30` |
| **GitHub Issue** | _None_ |
| **GitHub PR** | _None_ |
<!-- DOC2GH:MANAGEMENT:END -->

## Overview and Objective

Expand `doc/tools/doc2gh.py init` into an end-to-end bootstrap for repositories using doc2gh. The current packaged CLI supports document creation, status/link management, and validation, but has no `init` command. Add `init` so it validates the local documentation, prepares the GitHub repository and integrations, activates the required workflows, and reconciles local documents with GitHub tracking tools.

Keep this specification and all other project documentation under `doc/`. Implement the CLI and workflow changes in the implementation directories outside `doc/` (such as `tools/` and `workflows/`), then update the corresponding user documentation under `doc/`.

## AI Agent Context

> Direct instructions to guide AI coding assistants when reading context and generating code for this specification.

- **Affected Modules / Directories**:
  - `tools/doc2gh.py` (implementation of `init` and reuse of document/sync operations)
  - `workflows/` (GitHub event and document synchronization workflows)
  - `doc/tools/README.md`, `doc/workflows/README.md`, and `doc/README.md` (usage documentation)
- **Applicable Mandatory ADRs**:
  - No accepted ADR is currently identified.
- **Verification / Test Commands**:
  - `python3 doc/tools/doc2gh.py validate --include-templates`
  - Unit and mocked integration tests for Git/GitHub command outcomes.

## Functional Requirements

- **FR-01**: `init` must resolve the project root when invoked from the root or through the packaged `doc/` subtree, and determine the GitHub owner/repository from a configured remote or explicit options.
- **FR-02**: Before remote writes, `init` must validate all local documents and templates; validation failure must stop setup and report actionable errors.
- **FR-03**: Check for Git, GitHub CLI availability, authentication, and repository access before operations that need them. Report missing prerequisites clearly.
- **FR-04**: If the target GitHub repository does not exist, offer to create it under the resolved owner, configure the remote, and push the current branch after explicit confirmation. Reuse an existing repository without replacing its content or history.
- **FR-05**: Create or update a corresponding GitHub Issue and Project item for each eligible ADR, RFC, and Spec, keyed by stable document ID; repeated runs must not create duplicates.
- **FR-06**: Provision or reuse the GitHub Project and required labels, then inspect every expected workflow link in the host repository's `.github/workflows/` and confirm it resolves to the matching workflow source.
- **FR-07**: Create or repair missing, broken, or incorrect workflow links as relative links. Preserve regular files/directories at expected link paths and report conflicts; do not overwrite them silently.
- **FR-08**: Synchronize local document metadata to GitHub through `init`/`sync`, and GitHub status/link events back to documents through supported `doc2gh.py` operations and workflows.
- **FR-09**: Do not create a Pull Request solely because `init` ran. When explicitly requested on a non-default branch, create or reuse an appropriate PR and link it to relevant tracking Issues/documents.
- **FR-10**: Provide dry-run/plan mode that reports intended Git, repository, Project, Issue, label, and workflow changes without applying them.

## Non-Functional Requirements & Constraints

- **NFR-01 (Idempotency)**: Repeated initialization converges without duplicating Projects, Issues, labels, or workflow links.
- **NFR-02 (Security / Input Validation)**: Use authenticated `gh` operations and least-required workflow permissions. Never print or persist credentials. Require explicit confirmation before creating a remote repository or pushing; never force-push, delete remote content, or rewrite existing history.
- **NFR-03 (Failure Handling)**: Perform validation and preflight checks before mutations where possible. Report partial completion and safe retry steps after failures.

## Technical Design

### 1. Data Models / Entities
No database is required. Use document IDs to identify GitHub Issues. Reuse `.doc2gh.json` when it exists and add only backward-compatible repository/Project metadata required for repeatable setup.

### 2. Interfaces / APIs / Contracts
Add an `init` subcommand to the CLI in `tools/doc2gh.py`, with documented owner/repository selection, dry-run, remote-creation/push confirmation, and optional PR behavior. Reuse `validate`, `sync`, `new`, `status`, and `link` logic instead of duplicating managed-document handling. Return nonzero exit codes for validation, authentication, permission, and Git failures.

### 3. Execution Flow & Edge Cases
- An ambiguous or non-GitHub remote requires an explicit repository target; never guess the owner.
- A dirty worktree, conflicting remote, missing branch/upstream, or unsupported default branch must be reported before pushing and must not trigger destructive changes.
- Resolve workflow targets correctly when installed under `doc/` or `docs/`; leave conflicting regular files untouched.
- Reuse Issues matched by document ID and preserve manual descriptions and unrelated labels.
- If setup partially succeeds, report completed actions and leave the next run safe to retry.

## Acceptance Criteria

- [x] **AC-01**: Given a valid doc2gh checkout and authenticated GitHub access, when `init` runs, then it validates before remote mutations and reports the selected repository and setup actions.
- [x] **AC-02**: Given the target remote does not exist, when the user confirms creation, then `init` creates it and pushes the current branch without force-pushing.
- [x] **AC-03**: Given an existing remote repository, when `init` runs, then it reuses it without replacing content or history.
- [x] **AC-04**: Given local documents without tracking Issues, when synchronization runs, then it creates/reuses Issues and Project items by document ID and records links through doc2gh.
- [x] **AC-05**: Given matching Issues, labels, Project, and correct workflow links, when `init` runs again, then no duplicates are created and correct links remain unchanged.
- [x] **AC-06**: Given an invalid document, missing authentication, or insufficient permission, when `init` runs, then it exits nonzero with an actionable error before the affected mutation.
- [x] **AC-07**: Given dry-run mode, when `init` runs, then it lists intended changes without Git or remote writes.
- [x] **AC-08**: Given a missing, broken, or misdirected workflow link, when `init` runs, then it creates or repairs the relative link and verifies its target.
- [x] **AC-09**: Given a regular file or directory at an expected workflow link path, when `init` runs, then it preserves the path and reports a conflict.
- [x] **AC-10**: Given a GitHub status/link event, when the configured workflow handles it, then it updates the matching document using doc2gh and the document remains valid.
- [x] **AC-11**: Given a feature branch and explicit PR option, when a PR is appropriate, then `init` creates or reuses a linked PR; without that option it creates no PR.

## Task Breakdown (GitHub Issues & AI Execution)

Incremental, verifiable implementation steps (can be linked to GitHub sub-issues or PRs):

- [x] **Task 1**: Define `init` phases, options, repository resolution, and dry-run output.
- [x] **Task 2**: Implement document validation, Git/GitHub preflight, safe remote creation, and push behavior in `tools/`.
- [x] **Task 3**: Implement idempotent Project, label, Issue, and workflow-link setup.
- [x] **Task 4**: Add mocked tests for repeat runs, dry-run, link repair/conflict, invalid documents, authentication, permissions, and partial failures.
- [x] **Task 5**: Update user guides under `doc/` with permissions, confirmations, recovery steps, and examples.

## Test & Verification Plan

- **Unit Tests**: Mock Git and `gh`; cover repository resolution, idempotency, validation gating, workflow-link repair, conflict preservation, and failures.
- **Integration / E2E Tests**: Use a disposable GitHub repository to verify Project/Issue setup and repeat initialization; isolate remote creation and push operations from production repositories.
- **Manual Verification**: Test invocation through the root implementation and `doc/` subtree, dry-run, new/existing remote, correct/missing/broken/conflicting workflow links, and optional PR flow. Run `python3 doc/tools/doc2gh.py validate --include-templates`.

# Technical & Functional Specifications (Specs)

This directory stores the project's **Specifications (Specs)**. A Spec is an executable blueprint that guides developers and **AI agents** through the implementation of features, modules, or refactorings, directly linked to **GitHub Issues** and **Pull Requests**.

---

## Lifecycle & Statuses

All status changes **must** be executed using `python3 tools/doc2gh.py`. Do not edit the `status` field or the **Document Management** section manually.

| Status | Description |
| :--- | :--- |
| `draft` | Specification is being authored; requirements or design are still incomplete. |
| `ready` | Specification is reviewed and ready to be implemented by a developer or AI agent. |
| `in-progress` | Implementation is actively underway across one or more GitHub Issues/PRs. |
| `done` | All acceptance criteria and tasks have been implemented, tested, and merged. |
| `archived` | Historical specification or superseded by a newer Spec. |

---

## Naming Convention

Files follow a 4-digit sequential number in `kebab-case`, generated automatically by `tools/doc2gh.py`:

```text
NNNN-feature-or-module-name.md
```

**Examples:**
- `0001-user-registration-endpoint.md`
- `0002-webhook-retry-worker.md`

---

## Creating and Updating Specs

```bash
# 1. Create a new Spec from template
python3 tools/doc2gh.py new spec "User Registration Endpoint" --issue "#20"

# 2. Mark the Spec as ready for implementation
python3 tools/doc2gh.py status SPEC-0001 ready --issue "#20"

# 3. Transition to in-progress when opening an implementation PR
python3 tools/doc2gh.py status SPEC-0001 in-progress --pr "#24"

# 4. Mark as done once merged and verified
python3 tools/doc2gh.py status SPEC-0001 done --pr "#24"
```

---

## GitHub & AI Agent Integration

1. **Single Source of Truth for AI Agents**:
   - The **AI Agent Context** section specifies affected directories/files, mandatory ADRs to follow, and test/verification commands.
   - The **Task Breakdown** uses GitHub tasklist syntax (`- [ ]`) so both GitHub Issues and AI agents can track incremental implementation progress.
2. **Traceability with Issues and Pull Requests**:
   - Every Spec in `ready` or `in-progress` status should be linked to a tracking GitHub Issue (`github_issue`) and implementation Pull Request (`github_pr`) via `tools/doc2gh.py`.
   - Pull Requests implementing a Spec must reference `SPEC-NNNN` in their description.

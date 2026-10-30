# Requests for Comments (RFCs)

This directory stores the project's **Requests for Comments (RFCs)**. An RFC is used to propose major architectural changes, complex new features, public API/contract modifications, or cross-cutting technical initiatives that benefit from collaborative review prior to implementation.

---

## Lifecycle & Statuses

All status changes **must** be executed using `python3 tools/doc2gh.py`. Do not edit the `status` field or the **Document Management** section manually.

| Status | Description |
| :--- | :--- |
| `draft` | Initial proposal being drafted by an author or AI agent. |
| `review` | Open for discussion and feedback via a GitHub Pull Request. |
| `approved` | Proposal accepted; ready to spawn ADRs and executable Specs. |
| `rejected` | Proposal declined (preserved in the repository for historical context). |
| `implemented` | All derived Specs and implementation tasks have been completed. |

---

## Naming Convention

Files follow a 4-digit sequential number in `kebab-case`, generated automatically by `tools/doc2gh.py`:

```text
NNNN-proposal-title.md
```

**Examples:**
- `0001-oauth2-authentication-flow.md`
- `0002-async-event-dispatch-pipeline.md`

---

## Creating and Updating RFCs

```bash
# 1. Create a new RFC from template
python3 tools/doc2gh.py new rfc "OAuth2 Authentication Flow" --issue "#10"

# 2. Move RFC to review when opening a Pull Request
python3 tools/doc2gh.py status RFC-0001 review --pr "#14"

# 3. Mark RFC as approved once consensus is reached
python3 tools/doc2gh.py status RFC-0001 approved --pr "#14"
```

---

## GitHub & AI Agent Integration

1. **Pull Request Reviews**:
   - Submit new RFCs in a dedicated branch (`rfc/NNNN-short-title`) and open a Pull Request.
   - Use PR review threads to resolve items listed under **Open Questions**.
2. **Spawning ADRs and Specs**:
   - Once an RFC transitions to `approved`, extract binding architectural decisions into **ADRs** (`adrs/`) and break down the implementation into **Specs** (`specs/`).
3. **Instructions for AI Agents**:
   - When asked to draft an RFC, inspect the existing codebase to identify affected components, compatibility risks, and viable alternatives.
   - When an RFC is `approved`, use its **Adoption Plan & Follow-up Artifacts** checklist to generate the corresponding ADRs and Specs via `python3 tools/doc2gh.py new`.

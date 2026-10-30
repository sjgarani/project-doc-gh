# Repository Guidelines

## Project Structure

`doc/` is the canonical home for project documentation. Put ADRs, RFCs, Specs, templates, guides, and documentation edits under the matching `doc/` paths; do not create their equivalents in top-level `adrs/`, `rfcs/`, `specs/`, or other documentation directories. The directories outside `doc/`, especially `tools/` and `workflows/`, contain implementation code. Implement behavior there and update its user documentation under `doc/`.

## Agent Rules for Document Management

Use the packaged CLI at `python3 doc/tools/doc2gh.py` to create managed documents (`new`), change their status (`status`), or update GitHub links (`link`). Never copy templates to create managed documents or directly edit managed frontmatter and the `DOC2GH:MANAGEMENT` block. Treat GitHub Issues, labels, Projects, and Pull Requests as tracking interfaces synchronized with the documents. GitHub event handlers must route updates through doc2gh operations. Validate after documentation changes.

## Development and Validation

- `python3 doc/tools/doc2gh.py validate --include-templates` validates the canonical packaged documentation and templates.
- `python3 doc/tools/doc2gh.py list` lists documents managed in `doc/`.
- `python3 tools/doc2gh.py --help` shows commands in the implementation CLI; commands available there may differ from the packaged CLI until changes are implemented and synchronized.

Keep Markdown focused and follow the corresponding README and template. Use four-digit sequence IDs and kebab-case filenames; let `doc2gh.py new` choose the next ID. Existing commit history uses short Conventional Commit subjects such as `docs: ...` or `feat: ...`. Pull Requests should describe behavior, link the relevant document ID, and report validation performed.

## GitHub Configuration

Follow `doc/workflows/README.md` for GitHub Actions permissions. Use authenticated `gh` operations and never commit credentials or tokens.

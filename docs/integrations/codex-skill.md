# Codex QA Platform Scanner

`integrations/codex/qa-platform-skill` is the canonical source of the QA Platform Codex Skill. It scans an arbitrary target project without modifying source code, deterministically converts OpenAPI/Swagger/AsyncAPI, reads project-configured flow documents, produces independently editable module JSON files, packages a versioned `qa-platform-import` ZIP, and may create a pending import preview. The Skill never approves an import.

The platform owns the ZIP parser, preview, approval, and application of assets. The Skill owns static/configured runtime API-document discovery, module construction, documented draft-flow preparation, ZIP construction, and preview submission. Keep the boundary versioned and verify it with the repository's cross-boundary test before changing either side.

The default scan bucket is `releases/<package_version>/`. Its `manifest.json`, `project.json`, `api_templates.json`, `assertion_definitions.json`, `inventory.json`, `flow_documents.json`, `api.json`, `flow.json`, and `plans.json` are authoritative; `qa-platform-import.json` is a compatibility snapshot. Validate and build the ZIP from the directory so AI/reviewer edits to an individual module are preserved.

## Install or update

Run the installer from a checkout of this repository:

```bash
./scripts/install-codex-skill.sh
```

For a pre-existing user-level installation, request a deliberate replacement. The installer first retains a timestamped backup:

```bash
./scripts/install-codex-skill.sh --force
```

The default target is `${CODEX_HOME:-$HOME/.codex}/skills/qa-platform-skill`. Use `--target <directory>` for an isolated test installation.

## Maintain the integration

Run the standalone Skill regressions and the real ZIP-to-platform compatibility test before releasing either component:

```bash
make test-skill
make test-skill-contract
```

The legacy `qa-platform-skill` repository remains a transition distribution channel for existing installations. Do not make independent behavioral changes there; port changes from this canonical source only after the compatibility checks pass.

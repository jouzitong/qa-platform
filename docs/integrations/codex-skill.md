# Codex QA Platform Scanner

`integrations/codex/qa-platform-skill` is the canonical source of the QA Platform Codex Skill. It scans an arbitrary target project without modifying it, produces a versioned `qa-platform-import` ZIP, and may create a pending import preview. The Skill never approves an import.

The platform owns the ZIP parser, preview, approval, and application of assets. The Skill owns static discovery, manifest construction, ZIP construction, and preview submission. Keep the boundary versioned and verify it with the repository's cross-boundary test before changing either side.

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

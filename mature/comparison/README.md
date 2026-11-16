# Pinned mature comparison implementation

Source: ctzlyj/jd-competitor-price-adjustment-skill, 1.0.0, commit
43bdf6790fe3c8a5b89c217edcaefabf670cbc2c. Copyright (c) 2026 ctzlyj.
See LICENSE (MIT) and provenance.json for exact upstream/file hashes.

The original deterministic comparison, evidence, image similarity, exact-spec
TOP10, price-plan and confirmation/readback algorithms are retained. No new
business dispatcher or state machine is provided. The parent verifies provenance
and launches these original scripts with a sanitized environment.

Only browser/executable/service and runtime-path boundaries are adapted.
Browser calls use external WebCLI directly. There are no aliases, installers,
private package downloads, personal skill roots or embedded company model keys.

Set an absolute HEIDENG_MERCHANT_HOME. Mutable comparison runtime files are under
its comparison/ subtree. Externally install WebCLI and its browser bridge; use
HEIDENG_WEBCLI_COMMAND_JSON for a host-provided JSON argv prefix when necessary.
Set JDO_CLI_PATH and a JDO_HOME inside HEIDENG_MERCHANT_HOME in the parent's sanitized environment for
future authorized official CLI operations. No live operations were performed.

The upstream image similarity algorithm is local Pillow, not a company model.
AI review remains explicitly supplied evidence; no AI provider is implemented or
claimed. Optional authorized image search is disabled unless an explicit merchant
HEIDENG_COMPARISON_IMAGE_SEARCH_ORIGIN is configured and passes upstream health
validation. This setting does not provide or validate a model service.

Upstream reference documents are retained as evidence/algorithm background, not
installation instructions. Follow docs/comparison-reuse-2026-11-16.md in the parent
repository for the merchant entrypoints, transport contract and known blockers.

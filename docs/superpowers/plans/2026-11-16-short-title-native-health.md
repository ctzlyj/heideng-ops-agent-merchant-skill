# Short-title native health source Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement task-by-task. TDD first; bounded fresh review at end.

**Goal:** Bind complete original-scope native health list/detail observations to C3 without substituting them for short-title moderation or portal completion.
**Architecture:** ProductService read helper + separate small source/projection module; current owning worker/browser witness; strict v1/v2 effect-log validator with no unknown-terminal shortcut.
**Tech Stack:** Existing Python standard library, official merchant jdo protocol and synthetic browser/client factories.
**Spec:** docs/short-title-native-health-design-2026-11-16.md

## Global Constraints
- Same full merchant goal and authorization boundaries; only synthetic business calls. Public signed-hash official documentation downloads permitted, not authenticated shop API calls.
- Internal repository/installed/global Skills/upstreams read-only. No credentials, signed URLs, raw bodies in argv/logs/Git/replies.
- v1 original effect records remain immutable and readable. C3 terminal/retry/update gate cannot become permissive from health-source evidence.
- Original complete sibling scope kept including offsale/missing rows; details validated against exact original SKU/product and native documented healthInfoId.

## Review Focus
- Cross-SKU/product/healthId or stale source cannot label a target healthy.
- Partial/malformed/changed detail/list sources never become no-issue; bounded source reads and no truncation.
- A sourceData signed URL is not returned, written or fetched.
- Guard/identity loss during detail reads refuses new trusted observation.
- v1 historical evidence cannot be overwritten or bypassed by v2 metadata; no downgrade to discard new proof.

## Task 1: Official native detail source helper
Files: heideng_merchant/products.py; heideng_merchant/short_title_health_sources.py; tests/test_short_title_health_sources.py.
- [x] RED: exact route/params/profile/product/SKU/healthId, malformed data, safe projection, no sourceData access.
- [x] Implement health_detail read helper and strict minimal projection; GREEN targeted tests.

## Task 2: Original scoped dual native source observation
Files: short_title_verification.py; short_title_health_sources.py; short_title_effect_state.py; tests/test_short_title_health_effects.py.
- [x] RED: before/end list+per-SKU detail, original missing/offsale scope, drift, identity/guard loss, whole list pagination incomplete; native health facts cannot assert formal or imported.
- [x] Implement owning-thread reads and explicit v2 health evidence. Semantic validator reconstructs flags/row claims. v1 remains strict; reject v2 removal from later observations.
- [x] GREEN new plus affected C3/worker/gates; no real endpoints.

## Task 3: Installed and bounded independent acceptance
Files: references/native-short-title-effects.md; docs/short-title-native-health-development-2026-11-16.md/.json; optional installed smoke helper.
- [x] Bounded fresh reviewer; Important/Critical fixes each real RED→GREEN.
- [x] Fresh managed install smoke with synthetic factories and owned-loopback only, package audit, source hashes; private development commit/push.
- [x] Preserve incomplete formal/portal/failure-repair and real merchant acceptance; unified full current C3/failure-worker/regression/fresh GitHub acceptance at next integrated checkpoint, not every projection function.

Checkpoint evidence: docs/short-title-native-health-development-2026-11-16.md/.json. Final 89 targeted +3 installed methods verified; current full766 explicitly not run. Formal C3/merchant goal remains active.

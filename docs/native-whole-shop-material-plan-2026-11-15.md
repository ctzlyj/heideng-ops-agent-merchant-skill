# Whole-shop native information-health and material census plan

**Goal:** A merchant can ask for the entire on-sale shop's information-health/material gaps. Collect all on-sale products, all sibling SKUs (including offline siblings), one complete native health dataset, and every supported material type/order; publish a durable, paginated audit rather than treating one page or scored SKUs as the shop.

**Architecture:** New `shop_material_audit.py` orchestrates existing ProductService and native material read contract. All requests GET and same explicit merchant Profile. Existing write, approval, uploader and model behavior unchanged. CLI returns compact capture summary; status pages expose rows plus complete-scope totals. Data and source hashes persist in independent merchant state, not repository.

**Constraints:** Synthetic data only; no real auth/business writes, company credentials/models or upstream modifications. Current documented native status 103 identifies on-sale products/SKUs. Use public official document/reference contracts and existing audited transport, not employee SDK/SSO. Native healthScore vs portal commodity-score equivalence remains unverified. Local budgets must refuse/incomplete explicitly, not truncate and claim complete.

## Required behavior
- Product, per-product sibling SKU, health pagination each requires complete stable reported total and unique actual IDs; parent linkage and duplicate SKUs across products verified.
- Read on-sale product set and sibling census at both ends; order changes accepted, identity/product/SKU/status drift invalidates complete. This is a bounded collection window, not a transaction snapshot.
- Read materials for all siblings in <=1000 local input segments / <=50 native query batches; share one observed GET card, recheck it at end. Native response completeness/structure guard reused.
- Score rows not used as inventory. Missing/invalid scores are not zero; 0–89/native threshold, >=90, absent, invalid and outside current catalog kept distinct. Raw improvementList retained; inconsistent health product linkage invalidates completeness.
- Missing slot differs from existing empty, pending, rejected or unrecognized status. Failed material groups yield unobserved/null gaps, not guessed missing slots. Full-score SKU material gaps remain visible.
- Partial availability reports useful bounded data with explicit per-source completeness and reasons; changed shop or sensitive result refuses rather than publishing misattributed/private data.
- Capture contains immutable fingerprint and full-source rows; summary/pagination never pretends its current page is the entire shop. No report, source or model claims platform audit approval/score recalculation or write authorization.

## TDD tasks
- [x] RED tests: full product/SKU/health/material join; offline siblings vs on-sale targets; missing/invalid/high scores; absent vs empty/pending/rejected; missing totals, repeated/foreign rows, budgets; end census/card drift and reorder; shop switch/private result; durable tampering/pagination; 8191 on-sale + offline sibling large scope.
- [x] Implement focused read-only orchestrator/capture and summary/page interfaces.
- [x] CLI, Skill/registry/Chinese workflow docs and agent-facing examples.
- [x] Fresh-HOME installed 8191-SKU flow, full isolated suite, previous eight regressions, archive audit.
- [ ] One bounded independent review, fix verified issues; private push, actual GitHub clone rebuild/install/full matrix and evidence. Full goal stays active.

Independent review findings reproduced and fixed: suppress foreign-parent advice; incomplete census cannot infer outside-catalog membership; full captured scope vs filtered pagination separated. Seven focused recheck tests passed. Main also corrected a swallowed-assertion test and verified an install lease throughout collection. Actual GitHub roundtrip remains to record after push.

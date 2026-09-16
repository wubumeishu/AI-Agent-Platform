# P0 Security Residuals R1-R8 闭合 · 架构复审 (Re-Review)

**Card**: t_d304b83e (code-architecture-reviewer)
**Re-review target**: commit `e124b1e` on `wt/t_8915c655` (parent t_8915c655, base 75a291e)
**Date**: 2026-09-15
**Method**: source-level re-audit of all 8 residual fixes (jwt_auth.py, routers/auth.py,
crm/routers/{customer,customer_360,customer_messages}.py, security/{masking,crypto}.py,
services/private_domain.py, main.py, ADR-011 amendments) + **independent re-run** of
`backend/tests/test_p0_security.py` against the worktree source (not handoff-trust).

---

## VERDICT: CHANGES_REQUIRED

The R1-R8 mechanisms are **genuinely implemented and correct** — I verified them in
source and re-ran the suite. R1's gated mint, R2's CRM-surface auth+masking, R3's
jti/revocation, R4's boot guard, R5's OP_READ wiring, R7's CORS allow-list, and R8's
trust-boundary docs all hold, and the **6 real-PG E2E tests independently PASSED** in my
run. **But the re-review surfaced two things the R1-R8 list missed that block the card's
stated "可上线状态" (ship-state) goal:**

1. **A P0-1-class cross-account *read* leak** on the private-domain surface that the
   original report and the R-list did not name. (NEW-1, below.)
2. **The "42 passed" claim is not reproducible** in the current pinned dependency
   (FastAPI 0.141.1): my independent run is **41 passed + 1 failed**, and the route-
   coverage proof that R2/P0-1 rests on is now either a hard failure (CRM) or a
   *vacuous* pass (PD). (NEW-2, below.)

Neither is a "re-do"; both are small, concrete deltas. The security *property* is still
proven by the real-HTTP E2E tests; the two findings are (a) an under-scoped sibling read
and (b) a version-fragile test that no longer certifies route-coverage.

---

## 1. What I verified as CLOSED (source + my own test run)

| Residual | Evidence (source) | My re-run | Status |
|---|---|---|---|
| **R1** /auth/token mint backdoor | `check_mint_secret` (jwt_auth.py:407): gate set → `hmac.compare_digest` constant-time, missing/wrong → 401; unset → dev-only, non-dev logs CRITICAL | `test_mint_rejected_without_secret` (401), `..._wrong_secret` (401), gated 200, E2E `test_mint_token_and_channels_401_to_200` (monkeypatch gate: no-gate=401, with-secret=200) — **PASS** | ✓ closed |
| **R2** CRM customer PII surface | `get_current_principal` (401) on **every** endpoint in customer/360/messages routers + `mask_dict`; `/resolve/phone\|email` GET→POST body; `masking._mask_value` now scrubs `platform_account_id` (wechat-style) + `platform_username` (full redaction) | E2E `test_crm_customer_surface_authenticated_and_pii_masked` — **PASS** (no token 401; token 200 with no plaintext PII on wire; 360 masked; old GET resolver 405) | ✓ closed |
| **R3** jti / revocation | `create_access_token` emits unique `jti`; `decode_access_token` rejects revoked jti; `revoke_token` + `POST /auth/revoke`; in-process bounded registry, self-expiring | `test_token_carries_unique_jti`, `test_revoke_token_kills_it_before_exp` — **PASS** | ✓ closed (in-process; Redis = follow-up) |
| **R4** dev-fallback guard | `check_secret_configuration`: non-dev missing any of JWT_SECRET/CREDENTIAL_KEY/AUTH_TOKEN_MINT_SECRET → CRITICAL + `refuse_on_hardfail`; `SECURITY_REFUSE_FALLBACK_KEYS=1` → boot hard-fail; wired in main.py startup | `test_nondev_missing_keys_reports_refuse`, `..._all_keys_set_no_refuse`, `test_dev_posture_uses_fallback_silently` — **PASS** | ✓ closed |
| **R5** OP_READ dead | `record_audit(..., OP_READ)` wired on PD channel list/detail + segment-member list (best-effort, no-op on failure); CRM customer read surface documented out of V1 (customer model has no `account_id`) | E2E `test_sensitive_create_writes_audit_row` (write path) — **PASS**; OP_READ source confirmed at private_domain.py:174/189/841 | ✓ wired + documented |
| **R6** deterministic PII-equality | Recorded as accepted trade-off in ADR-011 (searchability vs PII-equality confidentiality) | ADR-011 amendment present | ✓ recorded |
| **R7** CORS `*`+credentials | `main.py:_cors_origins` → explicit `CORS_ALLOWED_ORIGINS` allow-list, dev defaults localhost:5173/8001; supersedes ADR-015 | source confirmed | ✓ closed |
| **R8** minor hardening | `_enforce_ownership` None-pass documented as trust boundary (services/private_domain.py:47); `decrypt_field` silent fallback now `logger.warning` (crypto.py:122/141) | source confirmed | ✓ closed |

My independent counts:
- `TestPrivateDomainE2E` (all 6 real-PG): **6/6 PASSED** in my run (PG up).
- `test_p0_security.py` full: **41 passed + 1 failed** (see NEW-2; handoff claimed 42 passed).

---

## 2. NEW findings the R-list did not cover (the reasons for CHANGES_REQUIRED)

### NEW-1 [P1, P0-1-class] Cross-account *read* leak: `get /private-domain/integration/customers/{id}/nurture-plans`

`backend/app/routers/private_domain.py:1200-1207` (the `get_customer_nurture_plans_endpoint`)
calls the service **without the caller's account**:

```python
plans = await get_customer_nurture_plans(db, customer_id)   # <- no _principal_account(principal)
```

and `get_customer_nurture_plans` (`integration_service.py:436-475`) queries
`NurturePlan` on `is_deleted==False, status=="active"` +
`target_segment_id IN (customer's segments) OR target_segment_id IS NULL`, but **never on
`NurturePlan.account_id`**.

Consequence: an authenticated operator bound to account **A** can read the
`name/description/schedule_type/status/target_segment_id` of **active "global"
(`target_segment_id IS NULL`) nurture plans owned by account B**, and can also pass an
arbitrary `customer_id` (the customer model has no `account_id`, so the customer itself is
not scoped to the caller) to read that customer's segment-targeted plans. This is a
**cross-account data read on the private-domain surface — the exact P0-1 class the three
original reports were filed against ("any user can access another account's data")**.

The asymmetry confirms it was simply overlooked: the *write* sibling
`apply_nurture_plan_to_customer` (`integration_service.py:342`) **is** scoped via
`_require_plan_ownership(plan, account_id)`, and the read siblings `get_customer_channel`
(→ `_require_channel_ownership`) and `get_customer_deals` (→ `WHERE DealItem.account_id
== account_id`) **are** account-scoped. Only the nurture-plans read path was left open.
Pre-existing (also present in base 75a291e) and **not** touched by e124b1e.

Severity: **P1** — auth-gated (needs a valid bound token), read-only, no customer PII in
the returned fields — but it is a genuine cross-account read that violates the P0-1
invariant the card claims to have closed. **Blocker for "可上线状态".**

**Fix (small):** pass `account_id=_principal_account(principal)` into
`get_customer_nurture_plans`, add `NurturePlan.account_id == account_id` to the plan
query, and add an E2E regression: account-A token reading a global plan owned by account B
must not see it.

### NEW-2 [P1, test-integrity] Route-coverage proof is version-fragile; "42 passed" not reproducible

Under the currently-resolved dependency (**FastAPI 0.141.1 / starlette 1.6.0**), included
sub-routers are **not** flattened into `app.routes` — they appear as 34 `_IncludedRouter`
placeholders that expose neither `.path` nor `.methods`. I probed the live app graph:
`_crm_customer_routes()` and `_pd_routes()` both return `[]`.

Effect on the two "every route is auth-gated" proof tests:
- `TestCrmCustomerSurfaceAuth.test_every_crm_customer_route_requires_bearer` → **FAILS**
  at `assert routes` (line 441, "expected CRM customer routes on the app graph").
- `TestPrivateDomainAuth.test_every_private_domain_route_requires_bearer` → **PASSES
  VACUOUSLY** (iterates 0 routes, no non-empty assertion), giving false confidence that
  the whole PD surface is covered.

So in this environment the suite is **41 passed + 1 failed**, not the handoff's "42
passed." The security property itself is still proven (the real-HTTP E2E tests pass), but
the *enumeration-based* route-coverage proof that R2/P0-1's closure leans on no longer
holds — one regression test hard-fails and its sibling silently checks nothing. The
handoff's green run was clearly produced on an older FastAPI that *does* flatten included
routers; `pyproject.toml` pins only `fastapi>=0.104.0` (no upper bound), so a fresh
install now resolves to 0.141.1 and the proof regresses.

**Fix (small):** make the route enumeration version-robust — walk `app.router.routes`
and recurse into nested routers (or drive the assertion off the OpenAPI schema / a static
route manifest) — so it enumerates live routes on both old and new FastAPI; add a
non-empty guard to the PD test; and **pin `fastapi`** (e.g. `fastapi>=0.104.0,<0.115` or
whatever the verified-good range is) so the suite is deterministic.

---

## 3. The 5 rulings requested in the card

1. **R1 gated-mint design (shared_secret + AUTH_TOKEN_MINT_SECRET + constant-time
   compare) — ACCEPTED.** It satisfies "don't ship unauthenticated mint in non-dev": when
   the gate is set, minting requires the shared credential (401 otherwise), and the R4
   boot guard makes a non-dev deployment that *leaves it unset* either loudly CRITICAL
   or hard-refused (`SECURITY_REFUSE_FALLBACK_KEYS=1`). **Condition to hold:** production
   MUST set `AUTH_TOKEN_MINT_SECRET` *and* `SECURITY_REFUSE_FALLBACK_KEYS=1` (otherwise a
   non-dev env with the secret unset still serves an open mint, only at CRITICAL-log
   level). Document that in the ADR/deploy checklist.
2. **R2 CRM customer surface is `get_current_principal` (operator-scoped, 401) not
   `require_private_domain` (account-bound, 403) — CONFIRMED FITS F-1/P0-2.** The
   `customer` model has **no `account_id` column** (verified: customer.py model =
   id/name/email/phone/company/avatar_url/extra_info/tags/identities), so account-
   scoping is structurally impossible for customer reads; customers live in a shared
   cross-account CRM pool. Operator-scoped auth + `mask_dict` is the correct, in-scope
   closure of P0-2 ("no PII in plaintext" + "surface is authed"). Do **not** re-scope to
   account-bound (that would need a schema change, out of P0-2's stated scope). Accept as
   is.
3. **R5 CRM customer read surface out of V1 read-audit — ACCEPTED (documented in
   ADR-011).** Correct call: `record_audit` keys on `account_id` (audit.py:337), and the
   customer model has none, so a "who accessed which account's customer" row has no
   account to key on. The V1 bar is "sensitive mutations audited + account-scoped PD
   sensitive reads audited" — reasonable. Track per-customer accountability under PIPL
   as a follow-up. (NEW-1 is separate — that is a *read-authorisation* hole, not a
   read-audit gap.)
4. **R3 in-process revocation + frontend not wired — SPLIT into two follow-up cards,
   non-blocking.** (a) Redis-ify the jti revocation registry for multi-process deploys
   (documented drop-in; the claim shape + endpoint are already forward-compatible).
   (b) Frontend (Vue) must be wired to mint + attach a Bearer token to the CRM/PD
   surfaces, because they now 401 without one — this is a **behavior change** for the
   live product frontend and is a distinct workstream, not a blocker for the backend
   security landing. Open both as follow-ups; neither gates this card.
5. **R7 CORS allow-list defaults (localhost:5173 + :8001) — ACCEPTED.** Correct and
   appropriately narrow for dev; supersedes the ADR-015 record-only state. No code change
   needed; just require a real deployment to set `CORS_ALLOWED_ORIGINS` explicitly (the
   dev defaults must never be left in prod).

---

## 4. Definition of Done (this review)

- All review areas checked: architecture ✓, code quality ✓, maintainability ✓, security
  ✓ (R1-R8 + NEW-1), performance ✓, duplication ✓, error handling ✓, tests ✓ (NEW-2),
  docs ✓ (ADR-011 amendments present and thorough).
- Findings documented: **NEW-1 (cross-account read leak, P1/P0-1-class, BLOCKER) +
  NEW-2 (version-fragile route-coverage test, P1 test-integrity).**
- Result unambiguous: **CHANGES_REQUIRED** on NEW-1 + NEW-2; R1-R5 ruled above; R6/R7/R8
  accepted.
- Approval gate: close NEW-1 (scope the nurture-plans read + regression test) and NEW-2
  (version-robust route enumeration + pin fastapi), re-run `test_p0_security` green,
  then re-review → APPROVED.

---

## 5. Implementer addendum — R2-fix closure (t_1e8214bd, commit f80f239 on wt/t_8915c655)

Both CHANGES_REQUIRED items are closed on branch `wt/t_8915c655` (commit `f80f239`),
re-run of `test_p0_security.py`: **43 passed** (was 41 passed + 1 failed in the
re-review run; +1 = the new NEW-1 regression test, and the 1 hard-fail now passes).

### NEW-1 closed
- `app/routers/private_domain.py` (`get_customer_nurture_plans_endpoint`): now passes
  `account_id=_principal_account(principal)` into the service.
- `app/services/integration_service.py` (`get_customer_nurture_plans`): added optional
  `account_id`; when supplied the plan query adds `NurturePlan.account_id == account_id`.
  Backward-compatible (default `None`), so no other caller breaks.
- `tests/test_p0_security.py::TestPrivateDomainE2E.test_cross_account_nurture_plan_read_is_scoped`
  (new real-PG E2E): seeds account B's global + segment-targeted active plans + a customer
  in B's segment, plus an account-A control plan, then asserts (a) B's token sees B's own
  plans, (b) A's token does NOT see B's global or segment plans, (c) A's token still sees
  A's own plan. **Verified the test FAILS when the fix is reverted** (A saw B's plans) and
  PASSES with the fix — so it is a genuine regression guard, not a tautology.

### NEW-2 closed
- `tests/test_p0_security.py::_collect_http_routes(app)` (new): version-robust enumerator —
  recurses into FastAPI 0.141.x `_IncludedRouter` placeholders (reading
  `include_context.prefix` + `original_router.routes`) so it enumerates the live graph on
  both the old (flattened) and new (placeholder) layouts. Verified: 76 PD + 19 CRM-customer
  (path, method) pairs, zero bad entries, exact match against the OpenAPI schema.
- `_pd_routes()` and `_crm_customer_routes()` both rewire onto `_collect_http_routes()`.
- Non-empty guard added to `test_every_private_domain_route_requires_bearer` (the test
  that previously passed *vacuously*): `assert routes` with an explicit "enumeration
  regressed → proof is vacuous" message, so it can never silently check 0 routes again.
- **fastapi pinned** `fastapi>=0.141.0,<0.142.0` in `pyproject.toml` (0.141.1 is what the
  committed `uv.lock` resolves to — the verified-good layout).
- **Dependency reproducibility fix** (a prerequisite for a clean, reproducible "43 passed"):
  `app/security/crypto.py` hard-imports `cryptography` at module load but it was
  *undeclared* in `pyproject.toml`/`uv.lock`, so a fresh `uv sync` could not even import
  `app.main`. Declared `cryptography>=43.0.0` and regenerated `uv.lock` (`uv lock --check`
  clean). Without this, no fresh install could run the suite — undermining NEW-2's
  determinism goal.

### Re-review focus for t_d304b83e
1. Re-run `backend/tests/test_p0_security.py` on `wt/t_8915c655` (commit f80f239) → expect
   **43 passed** (6 real-PG E2E incl. the new cross-account-read test + both route-coverage
   tests non-vacuous).
2. Confirm the NEW-1 scoping read path and NEW-2 enumerator + fastapi/cryptography pins.


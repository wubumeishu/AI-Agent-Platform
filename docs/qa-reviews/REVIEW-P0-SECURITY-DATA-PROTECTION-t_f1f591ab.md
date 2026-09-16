# P0 安全/数据保护 落地架构复审 (Review Closure)

**Card**: t_f1f591ab (code-architecture-reviewer)
**Review date**: 2026-09-15
**Target**: commit `ce06e91` on `p6an-10-analytics-dashboard` (6 files: migration 029,
`routers/private_domain.py`, `schemas/private_domain.py`, `security/audit.py` +
`security/masking.py`, `tests/test_p0_security.py` 30 tests)
**Supersedes verification of**: t_dcc56882 (data privacy), t_a0195813 (architecture),
t_e30eeacb (re-verify, F-3/4/5/6/10)
**Method**: source-level audit of all 6 files + security package (`jwt_auth`, `crypto`,
`masking`, `audit`) + mount wiring (`main.py`), independent re-run of
`tests/test_p0_security.py` (30/30 passed in 117s), acceptance-criteria mapping below.

---

## VERDICT: CHANGES_REQUIRED

The P0 security *machinery* genuinely landed and is correct — JWT dependency on all 24
private-domain routes, 401/403, response masking on the private-domain + integration
surface, AES-SIV at-rest encryption + migration-029 backfill, PBKDF2 credential hashing,
audit_log, and F-4/F-5/F-6/F-10 are all real (verified in source, not by handoff trust).
**But two P0 acceptance criteria are not actually closed, so this cannot be approved.**
The two P0 residuals plus a P1/P2 batch are listed below (§3). None requires a re-do;
each is a small, concrete delta.

---

## 1. What was CLOSED (verified in source + test run)

| Item | Evidence | Status |
|------|----------|--------|
| P0-1 JWT on 24 PD routes (401 no/bad token, 403 unbound/cross-account) | `jwt_auth.require_private_domain`; 76 endpoints carry `principal_dep`; `main.py` maps `AccountOwnershipError`→403; `test_every_private_domain_route_requires_bearer` | router-layer ✓ |
| P0-2 masking on private-domain + integration convert | `mask_dict` on all PD router returns; `integration_service._get_conversion_result` masks email/phone | this surface ✓ |
| P0-3 AES-SIV at-rest (customer.phone/email, customer_identity.*, private_channel.contact_info) | `crypto.EncryptedString/EncryptedJSON`; model columns switched; migration 029 widens to TEXT + `A1$` backfill + idempotency guard | ✓ |
| F-3 credentials hashed (account/proxy) | `account_service` L121/149, `proxy_service` L78/102 use `hash_password`/`verify_password`; migration 029 hashes legacy plaintext rows; legacy rows still verify | ✓ |
| P1-1 audit_log + record_audit | `audit_log` table in migration 029; `record_audit` best-effort (flush + commit-in-tx, swallows failures); wired on create/update/delete/transition (32 PD calls) | writes ✓ |
| F-4 ownership on update/delete + account-scoped reads | `_enforce_ownership` on nurture/content/followup/segment/deal update/delete; `get_segment_members`/`get_deal_stages`/`get_deal_pipeline_stats` gate on parent ownership | ✓ |
| F-5 added_by binds principal | `audit_added_by = added_by if added_by else principal.principal` on add/bulk-add | ✓ |
| F-6 transition 500 no longer leaks str(e) | `transition_deal_endpoint` catches → generic 500 + `logger.exception` | ✓ |
| F-10 email/phone moved to body | `convert_lead_endpoint` takes `LeadConversionRequest` body; email/phone in `data`, not URL | ✓ |
| Test integrity | re-ran `test_p0_security.py` → **30/30 passed** (incl. 5 real-PG E2E); 87/87 target + 1744/7 full-suite accepted as HEAD-baseline (0 P0-attributed) | ✓ |

---

## 2. Per-item gap-closure judgement (both source reports + 5 re-verify gaps)

- **P0-1 (no auth / client-supplied account_id)**: CLOSED at the private-domain router
  layer — but see **R1**: the unauthenticated token-mint backdoor defeats it.
- **P0-2 (PII returned plaintext)**: CLOSED for private-domain + integration convert —
  but **not** for the CRM customer surface, which the original reports explicitly listed. See **R2**.
- **P0-3 (PII stored plaintext)**: CLOSED (AES-SIV + migration 029).
- **P1-1 (no audit)**: CLOSED for writes; reads not covered (see **R5**).
- **F-3 (credential "encrypted" = plaintext)**: CLOSED (PBKDF2 wired + migration hash).
- **F-4 (cross-account id-only write/delete)**: CLOSED (ownership enforced + account-scoped reads).
- **F-5 (forgeable added_by)**: CLOSED (binds principal).
- **F-6 (500 leaks str(e))**: CLOSED (generic + server log).
- **F-10 (PII in URL)**: CLOSED (moved to body).

---

## 3. Residuals (blockers + P1/P2)

### P0 residuals — must fix before APPROVED

**R1 [P0] Unauthenticated `/api/v1/auth/token` mints account-bound operator JWTs for any account.**
`routers/auth.py:43` `mint_token` issues a valid, account-bound HS256 token from just
`{"principal","account_id"}` — **no credential, no passphrase, no auth dependency**. The
module docstring promises "an optionally shared signing passphrase," but `TokenRequest`
has **no passphrase field** — the gate is aspirational prose, not code. The test
`test_auth_token_endpoint_issues_bound_token` asserts exactly this open behavior (POST
principal+account → 200 → minted token passes the auth wall).
*Consequence*: any caller (script or browser) can mint a bound token for **any**
`account_id` and then read/write that account's entire private-domain surface. Combined
with the still-broken CORS posture (**R7**) this **re-opens P0-1** (the exact class the
three original reports were filed against: "any user can access another account's data").
The JWT wall is only as strong as its mint endpoint; that endpoint is wide open.
*Fix*: gate `/auth/token` — require a shared secret/passphrase in the body (the schema
field the docstring already advertises) and/or an auth dependency; add a test that
minting WITHOUT the gate is rejected (401). Do not ship the mint endpoint unauthenticated in any non-dev posture.

**R2 [P0] F-1/P0-2 not closed on the CRM customer surface.**
The original reports' P0-2/F-1 PII-leak scope named "private-domain + integration **+
CRM customer payloads**." The commit masked only the private-domain router + the
private-domain convert-lead path. The standalone CRM surface is **unmasked and
unauthenticated**:
- `crm/services/customer.py` returns raw `customer.email/phone` and identity PII — L63-79
  (get_customer), L176-177, L322-323/351-352, L442/476 (360/identity payloads).
- `crm/routers/customer.py` (list/get/create/update/delete + identities +
  `/resolve/phone|/resolve/email`) and `customer_360.py` / `customer_messages.py` are
  mounted in `main.py` with **no `principal_dep`, no JWT, no `mask_dict`**.
  `/resolve/phone?phone=...` even takes PII in the URL (the F-10 class the card closed
  elsewhere, but not here).
*Consequence*: P0-2's "no PII returned in plaintext" is false for this surface; it is a
live PIPL leak with no auth.
*Fix*: apply the same `mask_dict` (email/phone/identity PII + `platform_account_id`,
already in `PII_KEYS`) to the CRM customer list/get/360/identity/resolve payloads, and
put the CRM customer read surface behind the same auth dependency (or explicitly scope
it out of the P0-2 card and open a follow-up — but then this card's P0-2 claim is
overstated and must not be marked closed).

### P1 — fix in same pass (recorded as open risk by the implementer)

**R3 [P1] No JWT `jti` / revocation / token store.** Stateless HS256 with `exp` only; no
way to invalidate a leaked/minted token or to force rotation. Default TTL 8h, max 30d.
With R1 the exposure window = full token lifetime. Add `jti` + a short-lived revocation
list (or a token-issuance store) and a rotation path.

**R4 [P1] Silent dev fallback keys.** `_secret()` → `ai-agent-platform-dev-jwt-secret`
and `_pii_key()` → `ai-agent-platform-dev-credential-key` are used when the env vars are
unset, with **no startup guard or loud warning**. A deployment that forgets
`JWT_SECRET`/`CREDENTIAL_KEY` silently runs with forgeable JWTs and a publicly known
(source-visible) PII key. Add a startup check that refuses to boot (or logs CRITICAL)
when these are unset in a non-dev environment.

**R5 [P1] Audit is write-only; `OP_READ` is dead.** `OP_READ` is defined
(`security/audit.py:28`) but used **nowhere** — no sensitive *read* is audited. For
PIPL "who accessed sensitive data" you need at least audit on sensitive-resource reads
(listing channels, segment members, customer detail/360). Decide: either wire `OP_READ`
for sensitive reads, or document that read-audit is out of the V1 compliance bar and
track it. As-is, the "audit log" claim only covers mutations.

### P2 — record / monitor (acceptable with the caveat, not blocking)

**R6 [P2] Deterministic ciphertext leaks PII equality.** AES-SIV is deterministic by
design so `==` lookups work — meaning equal plaintext ⇒ equal ciphertext, which lets an
attacker holding the key correlate which records share the same phone/email and
enumerate/match members. This is the documented, accepted trade-off (randomized Fernet
can't do equality lookups). **Record it as a known weakening** in the ADR and, for fields
that do **not** need `==` search, prefer per-record salted (non-deterministic) encryption
so equality isn't leaked. At minimum: note in ADR-011 that searchability was bought at
the cost of PII-equality confidentiality.

**R7 [P2] CORS `*` + `allow_credentials=True` is an invalid/inconsistent combo**
(`main.py:51-52`): browsers reject credentialed cross-origin requests when origins is
`*`, and it is far broader than needed. Replace with an explicit origin allow-list.

**R8 [P2] Minor hardening.** (a) `_enforce_ownership` is a no-op when `account_id is
None` (legacy/internal callers); that's correct for tests but means any account-less
internal/scheduler caller is fully trusted — assert non-None on the API path or document
the trust boundary. (b) `decrypt_field` swallows decryption failures and returns the raw
stored blob (a tampered/corrupt ciphertext is returned as data; wrong key degrades to
exposing the ciphertext) — acceptable degradation but should `logger.warning`.

---

## 4. Test-integrity judgement

- `test_p0_security.py` **30/30 re-confirmed green** (independent run, 117s, 5 real-PG
  E2E). 87/87 target + 1744/7 full-suite accepted as HEAD-baseline with 0 P0-attributed
  failures — reasonable and I did not re-run the 1744-full suite (baseline-isolation
  evidence is on record).
- **Caveat**: `test_auth_token_endpoint_issues_bound_token` encodes the R1 backdoor as
  *expected* behavior (200 with no credentials). It is not a "pass = safe" test; the P0
  acceptance criteria it should assert (unauthenticated mint is rejected) are absent.
  Do not let the green suite mask R1/R2.

---

## 5. Definition of Done

- All review areas checked: architecture ✓, code quality ✓, maintainability ✓, security
  ✓ (R1–R5), performance ✓, duplication ✓ (single crypto util, no dup), error handling ✓
  (R8b), tests ✓ (§4), docs ✓ (ADR-011 needs R4/R6 notes).
- Result is unambiguous: **CHANGES_REQUIRED** on R1 + R2 (P0); R3–R5 (P1) in the same
  pass; R6–R8 recorded.
- No P0 residual may be silently left; if R2's CRM surface is deliberately scoped out of
  this card, it must be recorded as a tracked follow-up and P0-2 re-marked *not* closed.

**APPROVAL GATE**: R1 + R2 closed (and re-verified), R3–R5 addressed, ADR-011 updated with
the R4/R6 notes → re-review → APPROVED.

# QA Report — SSE provider test infra fix (P1-003 QA shim, `ai_config` gap)

Task: t_fbc8d986 · Parent: t_85fb6e58 (Phase 2 regression acceptance, PASS) · Verdict: PASS

## 1. Symptom (as handed off)

2 of 5 `TestP003ProviderSSE` cases in `tests/test_conversation_sse.py` failed in
setup (monkeypatch phase) with:

    AttributeError: module 'app.services.ai.agent_service' has no attribute 'ai_config'
    (tests/test_conversation_sse.py:168  monkeypatch.setattr(ai_agent.ai_config, ...))

Both failing cases:
- `TestP003ProviderSSE::test_stream_event_sequence_matches_contract`
- `TestP003ProviderSSE::test_stream_failure_emits_error_event`

Baseline reproduced verbatim before any change: `2 failed, 9 passed` in that file.

## 2. Root cause

- `app/services/ai/agent_service.py` is a P1-003 QA shim (marker `QA_AGENT_SHIM`,
  from p5msg09-t_bda104f0): it exposes only `TokenUsage` / `AIAgentService` and
  deliberately does NOT expose an `ai_config` module reference. Its
  `AIAgentService.generate_stream` is inert (yields a single shelved-error
  `result`); the router's documented 502/502-degrade path is what runs.
- `test_conversation_sse.py` was written before the shim (mtime 18:18 < 20:22)
  and still patches the removed `agent_service.ai_config` surface.
- `ai_config` is referenced **nowhere in production code** (grep: test file only).
- P1-003 is still shelved: `app/services/ai/__init__.py` states the config and
  agent-service layers are "intentionally absent while P1-003 is shelved."
  → **Option A applies** (repoint the test's patch face; no production change,
  and no P1-003 landing plan to align with the AI agent engineer).

## 3. Fix (test-only, no product code touched)

`tests/test_conversation_sse.py` (untracked file — the only file modified):

- Added `_FakeAgentService` — a service test-double that drives a P1-003 fake
  provider and yields the router's **real** SSE event protocol
  (`chunk` pieces, then a terminal `result` with `usage`/`error`).
- Added `_P003FailProvider` — a provider that raises on every call, so the
  router's error branch (terminal `result` with `error`) executes.
- Rewrote `_patched_service_for(monkeypatch, fail=...)` to install the
  `_FakeAgentService` through the router's **real service seam**
  (`conversations._new_agent_service`), via `monkeypatch.setattr` so it
  auto-restores after each test.
- Removed the three `monkeypatch.setattr(ai_agent.ai_config, ...)` lines that
  referenced the attribute the shim no longer exposes.

Why the router seam and not a literal `config.py` repoint: the shim's inert
`AIAgentService.generate_stream` never calls `get_provider`/`get_default_provider`/
`configured_provider_names` and yields no `chunk` events, so patching those
resolver symbols would leave the success assertion `"chunk" in types` failing.
Injecting the service double through `conversations._new_agent_service` keeps both
cases meaningful and exercises the router's actual chunk / error / result /
message-persistence logic — which is the contract the test is meant to verify.
This is the task's second Option A branch: "the interfaces the current shim
actually exposes" (the router's service seam).

## 4. Evidence (real runs, venv Python 3.11.16)

- `pytest tests/test_conversation_sse.py -v` → **11 passed, 0 failed**
  (all 5 `TestP003ProviderSSE` green, incl. the 2 previously-failing cases).
  Clean exit code = 0.
- Parent's 6-glob P1-003/Phase-2 sweep
  (`test_decision* test_intent* test_memory* test_conversation* test_prompt*
  test_persona*`) → **278 passed, 0 failed**. No new Phase-2/5 failures.

## 5. Out-of-scope pre-existing finding (NOT introduced by this task)

While running the broader Phase-2/5 files, `tests/test_crm_conversation_integration.py`
showed 2 failures:

- `TestManualTriggerEndpoint::test_route_registered_with_dedup_customer_param`
- `TestManualTriggerEndpoint::test_customer_dedup_route_registered`

They assert two CRM lead routes
(`/api/v1/crm/leads/from-conversation/{conversation_id}` and
`/api/v1/crm/leads/customer/{customer_id}/duplicate-check`) are registered on
the real `app.main` route table. Proven pre-existing and unrelated:

- The file is NOT in this task's 6-glob sweep (not in scope for acceptance).
- My change touches only `tests/test_conversation_sse.py`, which does not
  import or reference any CRM / lead / `app.main` symbol.
- Removing my SSE file entirely and re-running those 2 tests still yields the
  same `2 failed` — the failures are a separate CRM route-registration
  condition, not a regression from this fix.

Severity: P2 (route-registration / integration test-infra), module:
`app.crm.routers.lead` / `app.main` route table. Recommendation: route to a
separate card for whoever owns the CRM manual-trigger lead endpoint; do not
block this task on it.

## 6. Changed files

- `tests/test_conversation_sse.py` (untracked; the only file modified).
- No production code, no router, no shim, no config.py changes.

## 7. Acceptance status

- [x] `pytest tests/test_conversation_sse.py` all green (5 TestP003ProviderSSE).
- [x] No new Phase-2/5 failures (278/0 in the parent's 6-glob sweep).
- [x] Test-only change; product behaviour of the SSE contract preserved.

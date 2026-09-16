# Workflow Configuration API (t_wf_002)

Hierarchical CRUD for the workflow configuration model:
`Workflow → Trigger → Condition → Action`.

This is the **nested, hierarchy-preserving** API (t_wf_002). It sits alongside
the flat per-entity `workflow_framework` API (t_wf_001). Both target the same
four config tables; the nested form is the one the frontend trigger UI
(t_wf_010) and execution engine build on. See "Route coexistence" at the end.

Base path: `/api/v1/workflows`

## Vocabulary

| Constant            | Values |
|---------------------|--------|
| `WORKFLOW_TYPES`    | `auto`, `manual` |
| `WORKFLOW_STATUSES` | `draft`, `active`, `paused`, `archived` |
| `TRIGGER_TYPES`     | `manual`, `scheduled`, `event`, `cron` |
| `ACTION_TYPES`      | `conversation`, `message`, `tag`, `status_change`, `notification`, `custom` |
| `CONDITION_OPERATORS` | `eq`,`neq`,`gt`,`gte`,`lt`,`lte`,`in`,`not_in`,`contains`,`regex` |

## Workflow

| Method | Path | 2xx | Notes |
|--------|------|-----|-------|
| POST   | `/workflows` | 201 | create |
| GET    | `/workflows` | 200 | list; query: `status`,`workflow_type`,`search`,`page`,`page_size` |
| GET    | `/workflows/{id}` | 200 | flat record |
| GET    | `/workflows/{id}/detail` | 200 | full nested tree |
| PUT    | `/workflows/{id}` | 200 | partial update; bumps `version` |
| DELETE | `/workflows/{id}` | 204 | soft-delete cascades to all children |

Create body:
```json
{ "name": "Auto follow-up", "description": "...",
  "workflow_type": "auto", "status": "draft",
  "config": { "platform": "x" },
  "execution_policy": { "max_retries": 3 } }
```

## Triggers (nested under workflow)

| Method | Path | 2xx |
|--------|------|-----|
| POST   | `/workflows/{id}/triggers` | 201 |
| GET    | `/workflows/{id}/triggers` | 200 |
| PUT    | `/workflows/{id}/triggers/{tid}` | 200 |
| DELETE | `/workflows/{id}/triggers/{tid}` | 204 |

Create body (`spec` is type-specific):
```json
{ "name": "every 5 min", "trigger_type": "cron",
  "spec": { "cron": "*/5 * * * *", "timezone": "Asia/Tokyo" } }
```
- `scheduled` requires `spec.run_at`
- `cron` requires `spec.cron`
- `event` requires `spec.event`
- `manual` → `spec` may be `{}`

Missing a required spec key → `422`.

## Conditions (nested under trigger)

| Method | Path | 2xx |
|--------|------|-----|
| POST   | `/workflows/{id}/triggers/{tid}/conditions` | 201 |
| GET    | `/workflows/{id}/triggers/{tid}/conditions` | 200 |
| PUT    | `/workflows/{id}/triggers/{tid}/conditions/{cid}` | 200 |
| DELETE | `/workflows/{id}/triggers/{tid}/conditions/{cid}` | 204 |

Create body (`expression` is a JSON structure; `operator`, when present, must
be a known operator):
```json
{ "name": "high value", "logic": "and", "priority": 0,
  "expression": { "field": "customer.total_orders", "operator": "gte", "value": 3 } }
```
Unknown `operator` → `422`.

## Actions (nested under condition)

| Method | Path | 2xx |
|--------|------|-----|
| POST   | `/workflows/{id}/triggers/{tid}/conditions/{cid}/actions` | 201 |
| GET    | `/workflows/{id}/triggers/{tid}/conditions/{cid}/actions` | 200 |
| PUT    | `/workflows/{id}/triggers/{tid}/conditions/{cid}/actions/{aid}` | 200 |
| DELETE | `/workflows/{id}/triggers/{tid}/conditions/{cid}/actions/{aid}` | 204 |

Create body:
```json
{ "name": "tag VIP", "action_type": "tag",
  "params": { "tag_ids": ["vip"] }, "priority": 1 }
```
`action_type` outside `ACTION_TYPES` → `422`.

## Errors

- Unknown parent (e.g. trigger on a non-existent workflow) → `404`
- Validation (unknown type / missing spec key / bad operator) → `422`
- Parent path segment mismatch on PUT/DELETE (child id not under the given
  parent) → `404`

## Hierarchy semantics

- Deleting a parent **soft-deletes** the whole subtree (children become
  invisible to all reads/lists/detail).
- `GET /detail` returns only live (non-deleted) rows, ordered by `priority`.
- Hard `ON DELETE CASCADE` FKs also back the model, so a true row delete of a
  parent removes descendants at the DB layer.

## Route convergence (P1-1 / t_c94bba06)

The flat `workflow_framework` router (t_wf_001) **previously** re-declared the
four configuration entities (Workflow / Trigger / Condition / Action) under the
same `/api/v1/workflows` base path as this nested `workflow_config` router.
Because `workflow_config` is registered first in `app/main.py`, the framework
router's copies were silently shadowed and produced duplicate OpenAPI
operation ids.

Per the architecture review (t_c81d72fe P1-1), the two surfaces have been
**converged into a single canonical `/workflows` API — this nested
`workflow_config` router**. The framework router no longer declares any
`/workflows` (or `/workflow-triggers`, `-conditions`, `-actions`) route; it now
exposes ONLY the runtime-entity CRUD for `/workflow-delays`,
`/workflow-branches`, `/workflow-schedulers`, `/workflow-queues`, and
`/workflow-workers`. OpenAPI builds with **zero duplicate operation ids**
(verified: 326/326 distinct). The nested surface described above is therefore
the single source of truth for the `/workflows` resource.

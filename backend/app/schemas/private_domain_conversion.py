"""Pydantic schemas for the Private-Domain Conversion analytics endpoint
(Phase 6 / P6AN-06).

The endpoint is a single GET with query params
(``/api/v1/analytics/private-domain/conversion``). :class:`ConversionFilters`
models those query params so the service layer and the tests share one
source of truth for the filter shape; the router maps raw query params onto
it. The ``PDC*`` models are the response envelope.

Design notes
------------
- This is a *read-only aggregation* endpoint: it computes funnel + LTV-proxy
  + completion-rate metrics from existing Phase-5 private-domain source tables
  (``messages`` / ``conversation`` / ``deal_item`` / ``nurture_step_execution``
  / ``follow_up_task`` / ``agent_customer_binding``). It writes nothing, so it
  needs no new migration — it rides on the P6AN-01 analytics router prefix.
- Rates are **percentages** (0.0 - 100.0), rounded to 2 decimals, matching the
  P5MSG / lifecycle stats conventions. A zero denominator yields 0.0 (never a
  division error) — the funnel is safe on an empty database.
- The LTV proxy is documented in ``docs/P6AN-06-private-domain-conversion-api.md``;
  the response carries the raw counts so P6AN-09 (ROI) can recompute without a
  second trip through this endpoint.
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class ConversionFilters(BaseModel):
    """Query-param shape for GET /api/v1/analytics/private-domain/conversion.

    The router populates this from the request; the service consumes it.

    - ``agent_id`` scopes the customer funnel (reach / interact / convert /
      LTV / follow-up) to the customers **bound to that agent** (via
      ``agent_customer_binding``). ``None`` = all customers.
    - ``account_id`` scopes account-owned sources (messages / deals /
      follow-ups / nurture executions) to one account. ``None`` = all
      accounts.
    - ``since`` / ``until`` are the UTC time window (``since`` inclusive,
      ``until`` exclusive). If omitted the endpoint defaults to the last 30
      days.
    """

    agent_id: Optional[UUID] = None
    account_id: Optional[UUID] = None
    since: Optional[datetime] = None
    until: Optional[datetime] = None


class PDCWindow(BaseModel):
    """The effective time window actually queried (after defaults applied)."""

    since: datetime
    until: datetime
    default_applied: bool = Field(
        False,
        description="True when the caller supplied no since/until and the "
                    "30-day default window was used.",
    )


class PDCFunnel(BaseModel):
    """Private-domain customer funnel: base -> reached -> interacted -> converted.

    Counts are *distinct customers*. ``*_rate_percent`` are step-conversion
    rates (relative to the previous funnel stage); ``*_overall_percent`` are
    relative to the base population (denominator of the whole funnel).
    """

    base_customers: int = Field(0, description="Denominator population: distinct live private-domain customers in scope.")
    reached_customers: int = Field(0, description="Customers with >=1 successful outbound private-channel message in window.")
    interacted_customers: int = Field(0, description="Customers with >=1 inbound message (customer replied) in window.")
    converted_customers: int = Field(0, description="Customers with >=1 won deal in window.")

    reach_rate_percent: float = Field(0.0, description="reached / base * 100 (触达率).")
    interaction_rate_percent: float = Field(0.0, description="interacted / reached * 100 (互动率, step).")
    conversion_rate_percent: float = Field(0.0, description="converted / interacted * 100 (成交率, step).")

    reach_rate_overall_percent: float = Field(0.0, description="reached / base * 100.")
    interaction_rate_overall_percent: float = Field(0.0, description="interacted / base * 100.")
    conversion_rate_overall_percent: float = Field(0.0, description="converted / base * 100.")


class PCTLV(BaseModel):
    """LTV proxy (成交金额 / 次数). See docs for the exact口径.

    ``total_won_value_cents`` is the sum of ``deal_item.value`` (stored in
    cents) for won deals in the window. ``avg_won_deal_value_cents`` is the
    *per-transaction* amount (金额/次数). ``ltv_proxy_cents_per_reached`` is
    value-per-reached-customer over the window — the standing LTV proxy.
    """

    won_deal_count: int = 0
    total_won_value_cents: int = 0
    avg_won_deal_value_cents: float = Field(
        0.0, description="total_won_value / won_deal_count (单次成交金额, the 金额/次数 proxy)."
    )
    ltv_proxy_cents_per_reached: float = Field(
        0.0, description="total_won_value / reached_customers (value generated per reached customer in window)."
    )
    # Which currencies contributed to total_won_value (deal_item.currency).
    # The total is a plain integer sum; P6AN-09 decides FX handling.
    currencies: List[str] = Field(default_factory=list)


class PDCNurtureExecution(BaseModel):
    """NurturePlan execution completion (from ``nurture_step_execution``).

    ``executed_attempts`` counts attempts that actually ran
    (status != pending/running); ``success_attempts`` are status == success.
    Scoped by ``account_id`` only — nurture step rows carry no customer/agent
    link, so the agent filter does not apply to this metric.
    """

    success_attempts: int = 0
    executed_attempts: int = 0
    execution_rate_percent: float = Field(
        0.0, description="success / executed * 100 (NurturePlan 执行完成率)."
    )


class PDCFollowUp(BaseModel):
    """FollowUpTask completion (from ``follow_up_task``)."""

    completed: int = Field(0, description="Tasks with status == completed (created in window).")
    total: int = Field(0, description="All live tasks created in window.")
    completion_rate_percent: float = Field(
        0.0, description="completed / total * 100 (FollowUpTask 完成率)."
    )


class PDCROIInputs(BaseModel):
    """Raw inputs P6AN-09 (ROI) consumes.

    P6AN-09 combines ``total_won_value_cents`` (revenue) with its own
    cost-acquisition data to derive ROI. This card only exposes the revenue
    side; it does NOT compute ROI (that is P6AN-09's job).
    """

    total_won_value_cents: int = 0
    won_deal_count: int = 0
    reached_customers: int = 0
    base_customers: int = 0
    ltv_proxy_cents_per_reached: float = 0.0


class PDCResponse(BaseModel):
    """Response envelope for GET /api/v1/analytics/private-domain/conversion."""

    window: PDCWindow
    agent_id: Optional[UUID] = None
    account_id: Optional[UUID] = None
    funnel: PDCFunnel
    ltv: PCTLV
    nurture_execution: PDCNurtureExecution
    follow_up: PDCFollowUp
    roi_inputs: PDCROIInputs

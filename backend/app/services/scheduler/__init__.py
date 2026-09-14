"""Scheduler package (t_wf_003) - time-based task scheduling.

    app/services/scheduler/
    ├── __init__.py        package exports
    ├── cron_parser.py    pure cron parsing + next-fire math (5/6 field)
    ├── schedule_calc.py  per-entity next-fire computation (tz-aware)
    ├── service.py        SchedulerService: CRUD + execution state tracking
    └── engine.py         SchedulerEngine: heap queue + tick loop + dispatcher
"""
from app.services.scheduler.cron_parser import (
    CronParseError,
    CronSpec,
    compute_next_cron_time,
    next_cron_time,
    parse_cron,
)
from app.services.scheduler.schedule_calc import ScheduleConfigError, compute_next_fire
from app.services.scheduler.engine import (
    JobDispatcher,
    NoopDispatcher,
    SchedulerEngine,
    get_scheduler_engine,
    reset_scheduler_engine,
)
from app.services.scheduler.service import (
    SchedulerConfigError,
    SchedulerNotFound,
    SchedulerService,
)

__all__ = [
    "CronParseError",
    "CronSpec",
    "parse_cron",
    "compute_next_cron_time",
    "next_cron_time",
    "ScheduleConfigError",
    "compute_next_fire",
    "SchedulerEngine",
    "JobDispatcher",
    "NoopDispatcher",
    "get_scheduler_engine",
    "reset_scheduler_engine",
    "SchedulerService",
    "SchedulerNotFound",
]

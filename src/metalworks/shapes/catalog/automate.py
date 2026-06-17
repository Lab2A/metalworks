"""Automate base stack — automate a recurring task across tools.

Consolidates the integration / automation archetypes: the product's job is to
move and reshape data on a trigger or a schedule, not to hold a record. The
backend is connectors + a job queue + a transform step + run logs, so a generated
product can authenticate to a few apps and run reliably and observably.
"""

from __future__ import annotations

from metalworks.contract.research import SignalStrength
from metalworks.contract.shape import BaseStack, MatchSignature, ProductShape
from metalworks.shapes import register_base_stack, register_shape

AUTOMATE = BaseStack(
    id="automate",
    verb="automate",
    backend_capabilities=[
        "oauth connectors",
        "job queue / scheduler",
        "transform pipeline",
        "run logs / retries",
    ],
    default_modules=[],
    scaffold_target="starter:automate-integration",
)

INTEGRATION_SYNC = ProductShape(
    name="integration-sync",
    base_stack="automate",
    modules=[],
    domain_skin="Two apps that don't talk; the product keeps a slice of their data in sync.",
    match_signature=MatchSignature(
        cluster_keywords=[
            "manually copy data between two tools",
            "no integration between these apps",
            "keep two systems in sync",
            "data gets out of sync",
            "two way sync between apps",
        ],
        surface="web",
        build_signals=["connector", "sync", "oauth", "mapping", "integration"],
        min_signal=SignalStrength.MEDIUM,
    ),
)

WORKFLOW_AUTOMATION = ProductShape(
    name="workflow-automation",
    base_stack="automate",
    modules=[],
    domain_skin="A repetitive multi-step chore fires automatically when a trigger happens.",
    match_signature=MatchSignature(
        cluster_keywords=[
            "automate this repetitive task",
            "tired of doing the same steps manually",
            "trigger an action when something happens",
            "automate a multi step workflow",
            "no code automation between apps",
        ],
        surface="web",
        build_signals=["trigger", "action", "workflow", "automation", "step"],
        min_signal=SignalStrength.MEDIUM,
    ),
)

ETL_PIPELINE = ProductShape(
    name="etl-pipeline",
    base_stack="automate",
    modules=[],
    domain_skin="Pull data on a schedule, reshape it, and load it where it's needed.",
    match_signature=MatchSignature(
        cluster_keywords=[
            "scheduled data pipeline keeps breaking",
            "extract transform load data",
            "clean and reshape data before loading",
            "pull data on a schedule into the warehouse",
            "transform messy csv into a database",
        ],
        surface="web",
        build_signals=["extract", "transform", "load", "pipeline", "schedule"],
        min_signal=SignalStrength.MEDIUM,
    ),
)

OPS_BOT = ProductShape(
    name="ops-bot",
    base_stack="automate",
    modules=[],
    domain_skin="A bot runs routine operational chores on a schedule and alerts on failure.",
    match_signature=MatchSignature(
        cluster_keywords=[
            "bot to run routine ops tasks",
            "alert me when a job fails",
            "automate on call operational chores",
            "scheduled health checks and retries",
            "kick off jobs and retry on failure",
        ],
        surface="web",
        build_signals=["job", "schedule", "retry", "alert", "bot"],
        min_signal=SignalStrength.MEDIUM,
    ),
)

register_base_stack(AUTOMATE)
register_shape(INTEGRATION_SYNC)
register_shape(WORKFLOW_AUTOMATION)
register_shape(ETL_PIPELINE)
register_shape(OPS_BOT)

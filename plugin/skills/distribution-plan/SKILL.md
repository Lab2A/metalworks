---
name: distribution-plan
description: Sequence a finished demand report's distribution channels into a campaign — pushes (the spike channels placed into concentrated launch moments) and streams (the compounding channels that run continuously). Timing comes from a DETERMINISTIC playbook table (Product Hunt 12:01am PT Tue/Wed; Show HN Tue-Thu 8-10am PT; an X thread its window), never invented hours. The sequencer enforces the playbook's rules — one all-day-attention channel per day, never Product Hunt and a big HN push the same day — and frames the run as a campaign: pre-launch warming before Day 1, the staggered push week, a 30-day post step after. Each push is a channel test (test→focus), and a spark-requiring channel carries its spark→flywheel pairing. Use after a demand report exists and the user asks "when do I launch what", "sequence my launch", "give me a launch schedule", "what's the distribution plan", "what order do the channels go in", or wants the pushes-and-streams plan rather than a flat channel list. DRAFTING + PLANNING ONLY — it never posts.
---

## Preamble (run first)

Before any other tool, run the `preflight` MCP tool (or `metalworks preflight` on
the CLI). If it reports setup issues or that an update is available, surface that
to the user in one line and help them resolve it (install the missing extra/key,
or `pip install -U metalworks`) before continuing. Skip only if the user has
already passed preflight this session.

You are sequencing one demand report's distribution channels into a CAMPAIGN.
Distribution is not a flat list of channels with arbitrary T+2h spacing — it is
pushes (concentrated spike moments) and streams (compounding channels run
continuously), and the timing of every push comes from a deterministic playbook
table sourced from the research, never from an invented hour. You are NOT making
up a schedule.

## Steps

1. Get the `report_id`. If the user hasn't run a report yet, point them at
   `/demand-report` first — the plan sequences the report's channel strategy (D2),
   which needs a finished report to ground on.

2. Call the `distribution_plan` MCP tool with the `report_id` (or, on the CLI, run
   `metalworks distribution plan <report_id>`). It routes the report into its
   channel strategy, then returns a `DistributionPlan` with two lists: `pushes`
   (the spike channels sequenced into moments) and `streams` (the compounding
   channels run continuously).

3. Read the plan honestly, in two parts:
   - **Pushes** — for each `Push`: the `timing` (READ from the playbook table —
     e.g. "Day 1, 12:01am PT (Tue/Wed)" for Product Hunt), the `channel_name`, the
     `action` (the concrete human step), the `spark_channel` it ignites (if any),
     and the `rationale`. The campaign opens with a pre-launch warming push and
     closes with a 30-day post step — present them as the frame around the launch
     week, not as channels.
   - **Streams** — for each `Stream`: the `channel_name`, the `cadence_note` (how it
     runs continuously), and the `rationale`. Streams have no timing — they run all
     the time, not as a moment.

4. Call out the sequencing discipline the plan enforces: at most one
   all-day-attention channel per launch day, and never Product Hunt and a big Show
   HN / Launch HN push on the same day — they are staggered across days. Each early
   push is a channel TEST (test→focus); the 30-day step is where the tests resolve
   into a single channel to concentrate on, and a winning push becomes a repeatable
   one.

## Rules

- The timing is DETERMINISTIC — read from a fixed playbook table, not an LLM guess.
  Present the timings the tool returned; never invent or "improve" an hour.
- Never present two all-day-attention channels on the same day. If the report
  selected both Product Hunt and a big HN push, the plan already staggered them —
  surface that staggering, don't collapse it.
- A spark-requiring channel always carries its `spark_channel` (the spark→flywheel
  edge): the push that ignites the amplifier. Keep that pairing visible.
- This skill PLANS + DRAFTS the sequence; it never posts. Every push is
  `requires_human=True` and `posting_gated=True` — a human executes each moment.
- Hand the plan to the user to execute, or feed the channels' drafted assets
  (`/distribution-assets`) into each push moment.

---
title: "metalworks"
description: "Open-source marketing research and Reddit engagement as a Python library, CLI, MCP server, and Claude Code plugin."
---

metalworks turns real Reddit conversations into demand reports, and gives you the
OAuth, search, and compliance primitives to act on them. It is MIT licensed and
built by the team behind [Clique](https://clique.so), extracted from the
production pipeline that runs it.

<Note>
Pre-release (0.0.1). APIs below 1.0 are unstable except the
`metalworks.contract` models and the MCP tool contracts. Some surfaces are
marked "planned for 0.1" where they are not wired yet.
</Note>

## What you can do

- **Demand reports**: a research brief becomes a clustered report whose quotes
  are exact-matched to real Reddit comments and whose web findings carry source
  URLs from grounding metadata, never model prose.
- **Reddit engagement**: search, subreddit intel, inbox, rate-limited OAuth and
  posting, and a deterministic compliance gate.
- **Four form factors**: a Python library, a CLI, an MCP server, and a Claude
  Code plugin that share one typed contract.

## Where to start

<CardGroup cols={2}>
  <Card title="Your first demand report" href="/docs/tutorial-first-demand-report">
    From the zero-key offline demo to a real, grounded report.
  </Card>
  <Card title="Quickstart" href="/docs/quickstart">
    Install, run the offline demo, then plug in a provider key.
  </Card>
  <Card title="Protocols reference" href="/docs/reference-protocols">
    The ChatModel, search, embedding, and storage protocols.
  </Card>
  <Card title="Why open-core" href="/docs/explanation-open-core">
    The boundary with Clique and the provenance principle.
  </Card>
</CardGroup>

## Usage policy

For authentic, disclosed engagement only. No fake personas, no invented account
backstories, no vote manipulation, no coordinated inauthentic behavior. See the
[usage policy](https://github.com/Lab2A/metalworks/blob/main/USAGE_POLICY.md).

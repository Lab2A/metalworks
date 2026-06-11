---
title: "Bring your own store"
description: "Storage is a protocol. In-memory and SQLite ship; back the typed repos with anything you like."
---

metalworks does not prescribe a database. Storage is a set of typed repository
protocols (`CorpusRepo`, `BriefRepo`, `RunRepo`, `AccountRepo`, `OpportunityRepo`,
`InboxRepo`). One backend object implements as many as it supports.

Two backends ship in core, with zero infrastructure:

```python
from metalworks.stores import MemoryStores, SqliteStores

mw = Metalworks(store=MemoryStores())                         # ephemeral, the default
mw = Metalworks(store=SqliteStores("~/.metalworks/store.db")) # persistent, WAL-mode
```

`MemoryStores` and `SqliteStores` each satisfy every repo, so either drops into
`Metalworks(store=...)`, `ResearchDeps`, or the Reddit OAuth account store.

## Your own backend

Implement the repo methods you need on your own class and pass it as `store`.
Verify it against the same conformance suite the built-ins pass — including the
>1000-rows-behind-one-filter pagination case that catches silent truncation:

```python
from metalworks.testing import check_all_repos

check_all_repos(MyStore(), corpus_rows=1500)
```

Anything that exposes the repo methods works: Postgres, DynamoDB, a REST service,
an in-process dict. There is no generic document store to bind — the repos are
typed because real production tables are columnar.

## Supabase / PostgREST

A Supabase backend is one such custom store. If you want one, implement the repos
over the Supabase client (paginating reads with `.range()` to exhaustion, since
PostgREST silently caps result sets at its `max-rows` setting and returns HTTP
200). Bind it to pre-existing columnar tables by mapping logical collections to
your physical table names in the constructor. This is a backend you write for your
own infrastructure, not something metalworks configures for you.

## Pick the right one

| Backend | Use it for | Infra |
| --- | --- | --- |
| `MemoryStores` | tests, one-shot runs, the offline demo | none |
| `SqliteStores` | a single machine, persistence across runs | none |
| your own | a service, a shared DB, multi-tenant | yours |

# How-to: bind a Supabase store

The typed repos are the storage protocol. `MemoryStores` and `SqliteStores`
ship in core; `SupabaseStores` (behind the `[supabase]` extra) binds the same
repos to a Supabase / PostgREST project.

```bash
pip install "metalworks[supabase]"
```

## Bootstrap the tables

`SupabaseStores` ships a schema you apply once. Run `SCHEMA_SQL` against your
project (SQL editor or migration):

```python
from metalworks.stores.supabase import SCHEMA_SQL
print(SCHEMA_SQL)  # metalworks_briefs, metalworks_runs, metalworks_posts, ...
```

## Use it

```python
from metalworks.stores.supabase import SupabaseStores

store = SupabaseStores(url="https://xyz.supabase.co", key="<service-role-key>")
# or pass an existing supabase-py client: SupabaseStores(client=my_client)
```

`SupabaseStores` satisfies every repo protocol, so it drops into `ResearchDeps`
or the Reddit OAuth account store exactly like `MemoryStores`.

## Binding to pre-existing tables

If you already have columnar tables (this is how Clique migrates onto
metalworks), pass a `table_map` to point the logical collections at your
physical table names:

```python
store = SupabaseStores(
    url=..., key=...,
    table_map={
        "briefs": "research_briefs",
        "posts": "reddit_posts_research",
        "comments": "reddit_comments_research",
    },
)
```

## The pagination guarantee

Every read paginates with `.range()` until exhaustion. PostgREST silently caps
result sets at its `max-rows` setting (default 1000) and returns HTTP 200, which
would otherwise truncate corpus reads and corrupt every downstream count. The
conformance suite's `>1000 rows behind one filter` case exists to catch any
regression of this:

```python
from metalworks.testing import check_all_repos
check_all_repos(store, corpus_rows=1500)  # against a scratch project
```

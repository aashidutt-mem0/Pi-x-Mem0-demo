# Pi x Mem0 - Schema Extension Memory Demo

A live demo of the coding pain every backend developer knows: **a fresh agent
session does not know your schema conventions, so it writes a migration that
breaks the house style.** This wires the real [Pi coding agent](https://pi.dev)
to the real [`@mem0/pi-agent-plugin`](https://pi.dev/packages/@mem0/pi-agent-plugin)
and proves the difference shows up as broken vs correct SQL.

Nothing is mocked. The demo runs the actual `pi` binary against a real
git-backed repo with a seeded schema, and stores conventions to your live Mem0
account.

## The scenario

The `Acme Checkout` service ships an existing schema (`migrations/`) with an
opinionated house style that you cannot guess from nothing:

- primary keys named `<entity>_id`, never a bare `id`
- money as integer cents in a `BIGINT <thing>_cents` column, never `DECIMAL`
- every table has `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`
- soft deletes via a nullable `deleted_at`, never hard `DELETE`
- foreign keys `<entity>_id ... ON DELETE RESTRICT`
- migrations are numbered SQL files with a paired `-- +migrate Down` section

**Session 1:** you state these conventions once. The plugin captures them.
**Session 2 (fresh process):** "add a `refunds` table." The demo runs this
**twice** - once with the plugin inert (no memory) and once with it loading the
conventions from Mem0 - and shows the two migrations side by side with a diff
and a pass/fail convention checker.

The no-memory run reliably produces sensible-but-wrong defaults (`SERIAL id`,
`DECIMAL` money, `ON DELETE CASCADE`, no down migration). The with-memory run
matches the existing tables. That gap is the demo.

## Quickstart

```bash
bash setup.sh                              # installs pi, the plugin, python deps
export MEM0_API_KEY="m0-your-key-here"     # https://app.mem0.ai/dashboard/api-keys

# Azure OpenAI example, if using Azure
export AZURE_OPENAI_API_KEY="..."
export AZURE_OPENAI_ENDPOINT="https://your-resource.openai.azure.com"
export AZURE_OPENAI_DEPLOYMENT="gpt-5-mini"
export AZURE_OPENAI_API_VERSION="2024-10-21"  # demo normalizes this to v1 for Pi

streamlit run app.py
```

If `pi` isn't installed the UI still renders and explains the flow; the run
button stays disabled until the binary and key are present.

If your Azure endpoint includes an extra path such as `/export` or a full
`/openai/deployments/...` URL, the demo strips it down to the resource root
before launching Pi. If your deployment has a custom name, set:

```bash
export AZURE_OPENAI_DEPLOYMENT_NAME_MAP="gpt-5-mini=your-actual-deployment-name"
```

## How the pieces fit

```
app.py        Streamlit UI: the scenario, the side-by-side diff, the verdict.
  checker.py    Scores generated SQL against each convention (pass/fail table).
  pi_bridge.py  Drives the real pi binary and the live Mem0 API. The no-memory
                baseline strips MEM0_API_KEY from the child env so the plugin
                goes inert - an honest amnesiac control, no uninstall needed.
  sandbox.py    Seeds the git repo + existing schema and defines the conventions
                and their machine-checkable rules in one place.
```

Two correctness details worth knowing:

- The plugin scopes project memory by `git rev-parse --show-toplevel`, so the
  demo runs `pi` inside a real git repo. The scoping is genuine, not faked.
- In the Mem0 SDK, `add()` takes `user_id=` as a direct argument while
  `search()` / `get_all()` scope via `filters=`. The bridge follows that exactly.

## Reset between runs

Sidebar "Reset project memory" wipes the project scope for a clean cold start.

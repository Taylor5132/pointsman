# Pointsman

Pointsman routes new [`flutter/flutter`](https://github.com/flutter/flutter) GitHub issues to the Flutter **Team** that should own them. It also decides whether each prediction is trustworthy enough to apply without a person checking it.

A pointsman sets the railway points so every train lands on the right track. Here, every issue lands with the right team, and the points are reset when Flutter reorganizes its teams.

It is also its owner's first machine learning project, built in the open and learned top-down: the code comes first, the theory when the code needs it.

## Status

| Milestone | State |
|---|---|
| 0. Environment | ✅ done |
| 1. Data pipeline | ✅ done: snapshot `2026-10-22-v3`, 14,660 Issues split 70 / 15 / 15 by time |
| 2. Live collection & Live Evaluation | 🟢 collecting since 2026-10-22; scoring rule still to be written |
| 3. Exploratory analysis | ✅ done: [`notebooks/01_eda.ipynb`](notebooks/01_eda.ipynb) |
| 4–10. Baselines → fine-tuning → calibration → serving → final evaluation | not started |

No model results exist yet. The full plan, with each milestone's tasks and checkpoints, is in [PROJECT_PLAN.md](PROJECT_PLAN.md).

## Read first

- [CONTEXT.md](CONTEXT.md): the glossary. Capitalized terms (Team, Routed Issue, Self-labeled Issue, Weak Label, …) mean exactly what it says.
- [PROJECT_PLAN.md](PROJECT_PLAN.md): milestones in dependency order, the evaluation protocol, and the status of each milestone.
- [docs/adr/](docs/adr/): decisions that are hard to reverse. Start with [ADR 0001: Team identity](docs/adr/0001-team-identity.md).

## Setup

Requires [uv](https://docs.astral.sh/uv/) and the [GitHub CLI](https://cli.github.com/) (`gh auth login`). The code uses `$GITHUB_TOKEN` if set, otherwise the token `gh` is logged in with.

```bash
uv sync           # creates .venv with Python 3.12 and all dependencies
uv run pytest     # runs the tests
```

## Data pipeline

Each download becomes a **snapshot** in `data/snapshots/<name>/` (git-ignored): the raw GitHub answers, the cleaned rows, the train / validation / test split, and a `manifest.json` that fingerprints every file. A frozen snapshot never changes. A fix makes a new snapshot.

```bash
uv run python -m pointsman.pipeline.ingest                       # download Issues (add --limit N for a sample)
uv run python -m pointsman.pipeline.clean    --snapshot <name>   # validate and clean
uv run python -m pointsman.pipeline.split    --snapshot <name>   # temporal split
uv run python -m pointsman.pipeline.snapshot freeze --snapshot <name>
uv run python -m pointsman.pipeline.snapshot verify --snapshot <name>   # prove nothing changed
uv run python -m pointsman.pipeline.change_log                   # refresh taxonomy/team_change_log.csv
```

The test split stays locked until the final evaluation (Milestone 10). Analysis and tuning use train and validation only.

## Live collection

A GitHub Actions workflow ([`collect.yml`](.github/workflows/collect.yml)) polls `flutter/flutter`. Each run saves new Issues that have no Team label yet, with their text frozen as first seen. It commits them to the `live-data` branch. Their labels are fetched only on the scoring day, so these Issues give an evaluation that cannot leak. The same poller watches for new `team-*` labels and Triage Rulebook edits, and opens an alert Issue in this repo.

To read the collected data locally, check out the branch as a worktree:

```bash
git worktree add data/live live-data   # once
git -C data/live pull                  # latest data
gh run list --workflow collect.yml --limit 5
```

Do not run the collector locally as well: two copies of its bookmark would drift apart.

## Repository layout

```text
src/pointsman/
├── teams.py          # the In-scope and Out-of-scope Team lists
├── pipeline/         # ingest, schemas, clean, split, snapshot, change_log, github_client
├── events/           # event source (GitHub poller) and Team Split detector
└── live/             # live collector
notebooks/            # analysis notebooks (01_eda.ipynb)
taxonomy/             # Team Change Log (committed, so its diffs get reviewed)
docs/adr/             # architecture decision records
tests/
data/                 # git-ignored: snapshots/, live/ (worktree of live-data)
```

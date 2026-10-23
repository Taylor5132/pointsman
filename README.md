# live-data

Written by the "Collect live Issues" GitHub Actions workflow on `main`, every ~15 minutes.
Do not edit by hand.

- `issues.jsonl`: new Issues with no Team label yet, text frozen when first seen
- `collect_log.jsonl`: one line per poll
- `alerts.jsonl`: new team-* labels and Triage Rulebook edits
- `poller_state.json`: the poller's bookmark

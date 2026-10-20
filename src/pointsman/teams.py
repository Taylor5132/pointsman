"""Which Flutter Teams the project knows about. The single source of truth for Team lists."""

from datetime import datetime, timezone

# The eight user-facing Teams the model predicts.
IN_SCOPE_TEAMS = [
    "team-android",
    "team-design",
    "team-ecosystem",
    "team-engine",
    "team-framework",
    "team-ios",
    "team-tool",
    "team-web",
]

# Real Teams the model never trains on. Their Issues test whether
# unfamiliar work is sent to Human review.
OUT_OF_SCOPE_TEAMS = [
    "team-accessibility",
    "team-devexp",
    "team-fluttergpu",
    "team-linux",
    "team-macos",
    "team-text-input",
    "team-windows",
]

# team-infra is left out entirely: its Issues are internal CI reports.

# The day the In-scope Team labels were created (see ADR 0001).
DATA_START = datetime(2023, 7, 6, tzinfo=timezone.utc)

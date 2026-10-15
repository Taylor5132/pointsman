# Pointsman

Predicts which Flutter team should own a newly filed GitHub issue, and decides whether that prediction is trustworthy enough to act on without a person checking it.

## Language

### Routing

**Issue**:
A GitHub issue on `flutter/flutter` written by a person, not a bot. Open and closed Issues both count.
_Avoid_: Ticket, bug (not every Issue is a bug)

**Team**:
A Flutter engineering group, identified by the permanent ID of its `team-*` label on `flutter/flutter` (so a renamed label is still the same Team). In ML terms, each In-scope Team is one class.
_Avoid_: Component, area, category, engineering team

**In-scope Team**:
One of the eight user-facing Teams the model can predict: engine, tool, design, framework, web, android, ios, ecosystem.

**Out-of-scope Team**:
Any other Team. Its Issues are never trained on, and a good model should send them to Human review. `team-infra` is excluded entirely because its Issues are internal CI reports, not user reports.

**Routing**:
Choosing the single Team that should own an Issue.
_Avoid_: Classification (when talking about the product), assignment

**Auto-assign**:
A Routing Decision where the predicted Team is applied with no person checking it.
_Avoid_: Auto-route, AUTO_ASSIGN ticket

**Human review**:
A Routing Decision where the Issue is sent to a person because the prediction is not trusted.
_Avoid_: Fallback, HUMAN_REVIEW_QUEUE

**Routing Decision**:
The outcome for one Issue: either Auto-assign or Human review.

**Accuracy Goal**:
The minimum share of Auto-assigned Issues that must be routed to the correct Team. The Confidence Cutoff is derived from it, never chosen by hand.

**Confidence Cutoff**:
The calibrated probability above which a prediction is Auto-assigned.
_Avoid_: Threshold (ambiguous with the duplicate-similarity threshold), gate

**Coverage**:
The share of Issues that receive Auto-assign under a given Confidence Cutoff.

**Routed Issue**:
An Issue whose first Team label was applied by someone other than its author. Headline results are reported on Routed Issues only, because routing them is the real task.

**Self-labeled Issue**:
An Issue whose author applied its Team label when filing it. Used for training, never for headline results.
_Avoid_: Internal issue

**Confirmed Team**:
A Team whose `triaged-*` label is also on the Issue, meaning the owning Team accepted it.

### Team identity

**Taxonomy Version**:
The set of Teams and the Flutter triage rules in force on a stated date. Every model is trained against exactly one.

**Team Change Log**:
The dated record of Team creations, splits, removals and triage-rule changes, built from label creation dates and the history of Flutter's triage rulebook.

**Triage Rulebook**:
Flutter's own document defining how an Issue is assigned to a Team (`docs/triage/README.md` in `flutter/flutter`). The authority on what each Team means; this project never redefines a Team.

**Team Split**:
A Change Log event where a new Team takes over part of the work that existing Teams used to own.
_Avoid_: Reorg (too vague)

### Duplicates

**Duplicate**:
An Issue that a Flutter triager closed because it reports the same problem as an earlier Issue.

**Original**:
The earlier Issue that a Duplicate points to, as named in the triager's closing comment.
_Avoid_: Canonical, parent

### Evaluation

**Replay Experiment**:
An offline re-enactment of Human review on historical Issues. The "human answers" are the Team labels Flutter triagers actually applied; only the timing is simulated.
_Avoid_: Simulation (it suggests the human decisions are made up)

### Team Splits

**Label Event**:
A change to a `team-*` label or its use: a label created, renamed or deleted, or applied to or removed from an Issue. The only input the Team Split detector reads, whatever the source.

**Weak Label**:
A Team assignment produced by this project's own rules (from the Triage Rulebook) rather than by a Flutter triager. Used only for training, never for evaluation.
_Avoid_: Pseudo-label, silver label

**Team Prototype**:
The typical embedding of a Team's Issues, used to recognise Issues that look unlike any known Team and to add a new Team from a few examples.
_Avoid_: Centroid (fine in code, but say Team Prototype when talking about the project)

**Coverage Recovery**:
The time after a Team Split until Coverage returns to its pre-split level at the same Accuracy Goal.

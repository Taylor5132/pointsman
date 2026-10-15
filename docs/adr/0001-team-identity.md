---
status: accepted
---

# A Team is Flutter's label, versioned by date; Team Splits are measured, never relabeled

Flutter's Teams change over time: seven of the eight In-scope Teams were created on 2023-07-06, and new Teams have since split off (text-input 2024-03, linux/macos/windows 2024-06, accessibility 2024-08, devexp 2025-05, fluttergpu 2026-05). We identify a Team by the permanent GitHub ID of its `team-*` label, so a rename is still the same Team, and take its meaning only from Flutter's Triage Rulebook. Every model is trained against one dated Taxonomy Version, and every change goes in the Team Change Log. Historical labels are never rewritten to fit a newer taxonomy. Instead, a Team Split is treated as concept drift: detected, measured, and handled by the model's adaptation strategy.

## Considered Options

- **Define our own stable team list and map Flutter labels onto it.** Rejected: we would be inventing ground truth that no Flutter triager ever applied, and every rulebook change would silently break the mapping.
- **Relabel pre-split Issues to match the current taxonomy.** Rejected: it needs a classifier to decide the new labels, so the training data would partly come from a model's guesses. That is circular and impossible to audit.
- **Train only on data after the last Team Split (2024-08-14).** Rejected: it loses about a third of the data and removes the chance to study how splits affect the model.

## Consequences

- Training data starts at 2023-07-06, when the In-scope Team labels were created.
- Data snapshots record their snapshot date and Taxonomy Version in a manifest.
- Results get worse right after a Team Split, and that is expected. The project's credibility rests on detecting the split and adapting to it, not on avoiding it.

## Amendment: Weak Labels for new Teams

Rejecting relabeling would leave a newly split Team with no training data, so every Issue it owns would go to Human review. We allow one controlled exception: on a Team Split, the new Team's Triage Rulebook rule is turned into code and applied to the historical Issues of the Teams it took work from, and embedding similarity filters the matches. The resulting Weak Labels are stored separately and clearly marked, are used for training only, and are replaced as real triager labels arrive. Evaluation always uses human-applied labels. This differs from the rejected option because the labels come from Flutter's own written rules, not from a model's predictions.

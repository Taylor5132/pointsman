# AGENTS.md

Pointsman routes `flutter/flutter` issues to Flutter teams. It is also the owner's first ML project, which they are learning top-down: you write the code, and they learn by reading it and asking questions.

## Read first

- `CONTEXT.md` is the glossary. Use its terms (Team, Routed Issue, Weak Label, …) in code, docs and chat. When a new term is settled, add it there.
- `PROJECT_PLAN.md` lists the milestones in dependency order. Find the current milestone before suggesting work.
- `docs/adr/`: read it before changing how Teams are identified, labeled or relabeled.

## Teaching

- Implement each plan task completely. Then give a short **walkthrough**: what each module does, why it is structured that way, which libraries it uses and why, and the ML concept underneath.
- Answer the owner's questions at whatever depth they ask. Treat them as new to ML, and define each ML term the first time it appears. They study Python and math separately.
- Write plain, conventional code that a beginner can trace, because the owner has to explain and defend every line.
- When a task can be done more than one way, name the options, say which you chose and why, and state the **trade-off**: what the choice gives up.
- Build **intuition** first. Explain each idea with a concrete picture (an everyday analogy, a tiny worked example with real numbers, or a Pointsman issue), and only then give the formal version.

## Reply style

Keep each reply to **one topic**: short, solid and beginner-friendly. When there is more to say, finish the current topic and offer the next one, so the owner chooses what comes next.
- When you find that an earlier explanation of yours was wrong, say so explicitly and correct it.

## Evaluation integrity

These rules are what make the results credible. Keep them even when a shortcut looks harmless.

- Every reported number is **measured**. Write checkpoints as questions to answer, not as predicted targets.
- The test split stays **locked** until Milestone 10 and is opened once. Tune and compare on validation.
- Live issues stay **frozen**. Store their text when they are collected, and fetch their labels only on the scoring day named in the written scoring rule.
- Weak Labels are for training. Human labels are for evaluation.
- Headline metrics use Routed Issues.

## Data

- A snapshot in `data/snapshots/<date>/` never changes. A new download becomes a new snapshot with its own manifest.
- GitHub's REST search API allows about 30 requests per minute and then fails. For counts and bulk reads, use GraphQL (`gh api graphql`) with pagination.

## Changing decisions

When a design decision changes, update the one place it lives: `PROJECT_PLAN.md` for scope and order, `CONTEXT.md` for terms, and a new or amended ADR for choices that are hard to reverse.

## Chat formatting

In chat, write math as plain text or Unicode (σ(z), ≠, ⇒). LaTeX belongs only in Markdown files.

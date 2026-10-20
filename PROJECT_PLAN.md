# Pointsman

> Sets the points so every issue lands on the right team's track, and resets them when the tracks change.

An open-source ML system that predicts which Flutter **Team** should own a new GitHub Issue, decides whether that prediction is trustworthy enough to **Auto-assign**, finds likely **Duplicates**, and keeps working when Flutter reorganizes its Teams.

- Vocabulary: [CONTEXT.md](CONTEXT.md). Capitalized terms (Team, Routed Issue, Weak Label, …) are defined there.
- Decisions: [docs/adr/](docs/adr/). Start with [ADR 0001: Team identity](docs/adr/0001-team-identity.md).

---

## 0. How to use this plan

- **Order, not dates.** Milestones are listed in dependency order and have no deadlines. Move on when a milestone's checkpoint is met, not when time runs out. The one exception is **Live Evaluation (Milestone 2)**: it runs on real calendar time, so start it as soon as the data pipeline works and leave it running.
- **Checkpoints are measurements, not targets.** No result is predicted in advance. A checkpoint asks you to produce a number and explain it. The only pass/fail checks are correctness tests, such as "no test-period Issue appears in training".
- **Code first, questions after.** Claude implements each task. The owner learns top-down by reading the code and asking about its architecture, libraries and the ML concepts underneath. A task is finished when its checkpoint is met **and** the owner can explain how the code works and why it was built that way.
- **Theory when the code needs it.** Each milestone's *Learn* list is what to study while reading that milestone's code. Python and math are studied separately, outside this plan.

---

## 1. Problem & scope

| Decision | Choice |
|---|---|
| Repository | `flutter/flutter`: large, active, with real `team-*` routing labels and a written [Triage Rulebook](https://github.com/flutter/flutter/blob/master/docs/triage/README.md) |
| Prediction target | One **In-scope Team** per Issue: engine, tool, design, framework, web, android, ios, ecosystem (the Rulebook requires "one and only one" `team-*` label) |
| Excluded | `team-infra` (internal CI reports). **Out-of-scope Teams** (accessibility, text-input, linux, macos, windows, devexp, fluttergpu) are never trained on; their Issues test whether the system sends unfamiliar work to Human review |
| Issues | Open **and** closed, written by people (not bots), created on or after **2023-07-06**, the date the In-scope Team labels were created |
| Expected size | ~14.6k labeled Issues created since 2023-07-06 (counted 2026-10-20: 13,170 In-scope + 1,451 Out-of-scope), so about 9.2k In-scope training Issues |
| Team identity | The permanent label ID, interpreted through a dated **Taxonomy Version**. See ADR 0001 |
| Dropped features | `author_association` (it probably shows the author's role today, not when they filed; leakage risk). The body text may have been edited after filing; this is a documented limitation |

### Facts measured during planning (2026-10-14/15, small samples)

- About 60% of recently labeled In-scope Issues were **Self-labeled** by their author at filing time, mostly Flutter contributors. About 40% were **Routed** by someone else, usually within a day. No bot applied any Team label.
- Roughly 100–175 new Issues per week, of which about 30–40 per week become Routed In-scope Issues.
- Team Splits and the Rulebook updates that followed them: accessibility (label 2024-08-14 → rule 2024-08-16); linux/macos/windows (label 2024-06-05 → rule 2024-06-10).
- Duplicates are marked with the `r: duplicate` label (7,601 closed) and a triager comment such as "Closing this as a duplicate of #N".

---

## 2. System architecture

```text
[GitHub GraphQL API] ──────────────► [Label Event source]
       │  (snapshots)                  production: webhook  |  this project: ~15-min poller
       ▼                                        │
[Snapshot folders + manifest] ──► [DuckDB]      ├─► Team Split detector ──► alert ──► human approves new Taxonomy Version
       │                                        └─► Live collector (frozen Issue text, labels fetched only on scoring day)
       ▼
Temporal split (70 / 15 / 15 by created_at)
       │
       ├─► Baselines: keyword rules → TF-IDF + LogReg → TF-IDF + metadata + LightGBM
       └─► ModernBERT-base + LoRA (Team classifier)
                    │
                    ├─► Temperature calibration ──► Confidence Cutoff (from 90% Accuracy Goal)
                    └─► Team Prototypes (embedding space) ──► "unlike any known Team" signal
Duplicate track (separate model): TF-IDF → sentence embeddings → (stretch) fine-tuned on Duplicate pairs

[FastAPI POST /triage] (ONNX INT8, CPU)
   ├─► Team probabilities (calibrated)
   ├─► Routing Decision: Auto-assign | Human review
   │      Human review only if: below Confidence Cutoff, OR far from every Team Prototype
   └─► Top-k candidate Originals (Duplicate search)
[POST /feedback] ──► human-corrected Team ──► retraining data
```

---

## 3. Evaluation protocol

1. **Temporal split.** Sort by `created_at`: oldest 70% train, next 15% validation, newest 15% test. The **test set is opened exactly once**, in Milestone 10.
2. **Headline metric** is Macro F1 on **Routed Issues**. Self-labeled Issues are used for training but would inflate results. Also report per-Team F1 and the **Confirmed Team** subset (Issues that also carry `triaged-<team>`).
3. **Routing Decision.** The Confidence Cutoff is derived on validation data so that Auto-assigned Issues are **≥ 90% correct** (the Accuracy Goal). Report **Coverage** at that goal, and plot the Coverage-versus-accuracy curve with 80% and 95% marked.
4. **Replay Experiment.** Using only train and validation periods: review the N least-confident Issues (their real triager labels) and retrain. Compare against reviewing N random Issues.
5. **Live Evaluation.** Collect new Issues that have no Team label yet and freeze their text. Every model predicts on them. **Labels are never fetched until scoring day.** The scoring rule (for example "≥ 200 Routed Issues labeled") is written down before any results are seen.
6. **Latency.** One Issue at a time, after warm-up, on the Mac and inside Docker, using real Issue lengths. Report P50/P95 by input-length bucket. Experiment with max length 512 / 1,024 / 2,048 tokens for F1 versus latency.
7. **Team Split resilience.** Backtest on the 2024-08-14 accessibility split, and optionally the 2024-06-05 desktop split: detection lag, the share of post-split Issues sent to Human review versus wrongly Auto-assigned, accuracy of the new Team from Weak Labels, and **Coverage Recovery** time.
8. **Duplicates.** Recall@5: for each Duplicate, is its Original among the top 5 candidates?

---

## 4. Repository structure

```text
pointsman/
├── CONTEXT.md                   # Glossary (domain language only)
├── docs/adr/                    # Architecture decision records
├── taxonomy/team_change_log.csv # Team Change Log (committed; diffs are reviewed)
├── data/                        # Git-ignored
│   ├── snapshots/<YYYY-MM-DD>/  # Raw + cleaned Parquet, manifest.json (date, Taxonomy Version, row counts)
│   ├── live/                    # Frozen live Issues + logged predictions
│   └── triage.duckdb
├── models/                      # Git-ignored artifacts (baseline, LoRA adapter, ONNX, calibration)
├── notebooks/
│   ├── 01_eda.ipynb
│   ├── 02_baseline_error_analysis.ipynb
│   ├── 03_colab_lora_finetune.ipynb
│   └── 04_split_backtest.ipynb
├── src/pointsman/               # Python package (uv_build layout)
│   ├── pipeline/                # schemas.py, ingest.py, clean.py, snapshot.py, change_log.py, split.py
│   ├── events/                  # source.py (interface), poller.py, detector.py
│   ├── live/                    # collect.py, predict.py, score.py
│   ├── baseline/                # features.py, train.py
│   ├── finetune/                # dataset.py, model.py, train.py
│   ├── embeddings/              # prototypes.py, duplicates.py
│   ├── resilience/              # weak_labels.py, backtest.py
│   ├── evaluation/              # metrics.py, calibrate.py, cutoff.py, replay.py
│   └── serving/                 # export_onnx.py, app.py
├── flows/                       # Prefect flows (event polling, live collection)
├── tests/
├── Dockerfile
└── pyproject.toml               # Managed with uv
```

---

## 5. Milestones (dependency order)

### Milestone 0: Environment ✅

- [x] `uv` project pinned to Python 3.12 (`.python-version`), with the base dependencies in `pyproject.toml` and exact versions in `uv.lock`.

**Checkpoint:** `uv run python -c "import numpy, pandas, sklearn"` succeeds. Met on 2026-10-15.

---

### Milestone 1: Data pipeline

**Prerequisites:** M0.

> **Status (2026-10-20): in progress.** Pipeline runs end to end on a 200-Issue sample (`2026-10-20-sample200`, frozen). **Next:** tests → full download → clean → split → freeze → checkpoint.
>
> ```bash
> uv run python -m pointsman.pipeline.ingest            # add --limit N for a sample
> uv run python -m pointsman.pipeline.clean    --snapshot <name>
> uv run python -m pointsman.pipeline.split    --snapshot <name>
> uv run python -m pointsman.pipeline.snapshot freeze --snapshot <name>
> uv run python -m pointsman.pipeline.change_log         # refresh taxonomy/team_change_log.csv
> ```

- [x] **`ingest.py`:** GraphQL fetch of In-scope and Out-of-scope Issues created on or after 2023-07-06, open and closed. Fields: title, body, created_at, author (and whether it is a bot), labels **with label IDs**, Team **Label Events** (who applied which label and when), `triaged-*` labels, and comments on `r: duplicate` Issues.
- [x] **`schemas.py` + `clean.py`:** Pydantic validation; strip HTML comments and template boilerplate; split prose from fenced code blocks and stack traces; derive the target Team; mark each Issue as **Routed** or **Self-labeled** (from who applied the first Team label); parse Duplicate → Original links.
- [x] **`snapshot.py`:** write each download to `data/snapshots/<date>/` with a manifest (snapshot date, Taxonomy Version, row counts per Team). Manual versioning; DVC is postponed.
- [x] **`change_log.py`:** build the **Team Change Log** from label creation dates and the git history of `docs/triage/README.md`.
- [x] **`split.py`:** load into DuckDB and produce the 70 / 15 / 15 temporal split.
- [ ] **Tests:** split boundary; no Issue in more than one split; Duplicate-comment parser; bot filtering.

**Learn:** temporal leakage; label noise; class imbalance. Chip Huyen, *Designing Machine Learning Systems* (DMLS) ch. 3–4.

**Checkpoint:** `uv run python -m pointsman.pipeline.split` passes `max(train.created_at) < min(val.created_at)` and `max(val.created_at) < min(test.created_at)`, and the manifest's row counts match DuckDB.

---

### Milestone 2: Event-driven collection & Live Evaluation (start right after M1, keep running)

**Prerequisites:** M1.

- [ ] **`events/source.py`:** a **Label Event source interface**. Implement a poller that queries every ~15 minutes and backfills by timestamp after any downtime. Document that production would plug a GitHub webhook (`label`, `issues.labeled`) into the same interface.
- [ ] **`events/detector.py`:** raise an alert on a new `team-*` label or a Triage Rulebook commit, and append it to the Team Change Log. A human approves any new Taxonomy Version.
- [ ] **`live/collect.py`:** store new Issues that have no Team label, with their text frozen at collection time.
- [ ] **Prefect flow** wrapping the poller and collector (introduce Prefect once the plain scripts work).
- [ ] **Measure** real weekly volume and time until labeling, then **write the live scoring rule** into this plan before any predictions are scored.

**Learn:** event-driven versus polling architectures; why prospective evaluation cannot leak.

**Checkpoint:** the flow runs unattended; the scoring rule is committed to git.

---

### Milestone 3: Exploratory analysis

**Prerequisites:** M1.

- [ ] **`01_eda.ipynb`:** Team distribution; Routed versus Self-labeled share per Team; open/closed mix across splits; how often Team labels change (bounces between Teams); monthly Team volume with Team Split dates overlaid; Issue length distribution in tokens.

**Checkpoint:** a written list of the 5 findings that most affect modeling choices.

---

### Milestone 4: Classical baselines

**Prerequisites:** M3.

- [ ] **Keyword-rule baseline** derived from the Triage Rulebook.
- [ ] **`features.py`:** `TfidfVectorizer` on prose and code, plus metadata (lengths, number of code blocks, has stack trace).
- [ ] **`train.py`:** class-weighted LogisticRegression and LightGBM, tracked in **MLflow** (introduce it here). Report Macro F1 on Routed validation Issues, per-Team F1, the Confirmed subset, the confusion matrix and single-Issue latency.
- [ ] **`02_baseline_error_analysis.ipynb`:** inspect the 30 most confident errors; classify each as model error, ambiguous per the Rulebook, or likely label noise.
- [ ] **Live:** the baseline starts predicting on collected live Issues.

**Learn:** TF-IDF and bag-of-words limits; linear classification and cross-entropy $\mathcal{L} = -\sum_i y_i \log \hat{y}_i$; gradient-boosted trees; precision/recall, Macro F1 versus accuracy. StatQuest *Gradient Boost*, *Confusion Matrix*, *F1*. DMLS ch. 6.

**Checkpoint:** baseline results in MLflow, explained by Team, with error categories documented.

---

### Milestone 5: Fine-tuning ModernBERT with LoRA

**Prerequisites:** M4.

- [ ] **`dataset.py`:** input `"[TITLE] … [PROSE] … [CODE] …"`; tokenize with `answerdotai/ModernBERT-base`; dynamic padding.
- [ ] **`model.py`:** `AutoModelForSequenceClassification(num_labels=8)` plus PEFT `LoraConfig(task_type="SEQ_CLS", r=16, lora_alpha=32, lora_dropout=0.05, target_modules=["Wqkv", "Wo", "Wi"])`. Print the trainable-parameter share and explain it.
- [ ] **`train.py`** (Colab/Kaggle T4): AdamW, warmup plus cosine schedule, **`fp16=True`** (T4 does not support bf16), class-weighted cross-entropy, Macro F1 evaluation, checkpointing (free sessions disconnect).
- [ ] **Length experiment:** max length 512 / 1,024 / 2,048 tokens for F1 versus training cost.
- [ ] **Live:** the fine-tuned model also predicts on every live Issue.

**Learn:** subword tokenization; embeddings; self-attention $\text{softmax}(QK^T/\sqrt{d_k})V$; LoRA $h = W_0x + \frac{\alpha}{r}BAx$. 3Blue1Brown *Attention in Transformers*; Hugging Face Course ch. 2–3; PEFT docs.

**Checkpoint:** comparison table against the baseline (overall and per Team), with an explanation of where fine-tuning helps and where it does not.

---

### Milestone 6: Embeddings & Duplicate detection

**Prerequisites:** M5 (fine-tuned encoder), M1 (Duplicate pairs).

- [ ] **TF-IDF cosine** retrieval baseline.
- [ ] **Off-the-shelf sentence-embedding model** (for example from `sentence-transformers`), stored in DuckDB as `FLOAT[d]` arrays and searched with `array_cosine_similarity`.
- [ ] **(Stretch)** fine-tune the embedding model on Duplicate pairs with a contrastive loss.

**Learn:** vector spaces, cosine similarity, why classification embeddings cluster by Team rather than by "same bug", contrastive learning, Recall@k.

**Checkpoint:** Recall@5 at each step, with failure examples.

---

### Milestone 7: Calibration & Contain

**Prerequisites:** M5, M6.

- [ ] **`calibrate.py`:** fit a temperature $T$ by **minimizing NLL** on validation logits, $P_i = \frac{e^{z_i/T}}{\sum_j e^{z_j/T}}$; report ECE and reliability diagrams before and after.
- [ ] **`cutoff.py`:** derive the Confidence Cutoff for the **90% Accuracy Goal**; plot Coverage versus accuracy (80 / 90 / 95% marked).
- [ ] **`prototypes.py`:** **Team Prototypes**; add the "far from every Team" signal to the Routing Decision.
- [ ] **Out-of-scope check:** the share of Out-of-scope Team Issues that end up in Human review (good) versus wrongly Auto-assigned (bad), with and without the prototype signal.

**Learn:** why neural networks are overconfident (Guo et al., 2017, *On Calibration of Modern Neural Networks*); selective prediction; prototype-based classification (Snell et al., 2017, *Prototypical Networks*).

**Checkpoint:** Coverage at 90% accuracy on validation, plus Out-of-scope containment rates.

---

### Milestone 8: Team Split resilience

**Prerequisites:** M7, M1 (Team Change Log).

- [ ] **`weak_labels.py`:** turn a new Team's Rulebook rule into code; apply it to the historical Issues of the Teams it took work from; filter matches by embedding similarity. Store the results as marked **Weak Labels** (training only, per the ADR 0001 amendment).
- [ ] **`04_split_backtest.ipynb`:** replay the 2024-08-14 accessibility split using only pre-split training data. Compare **(A)** waiting for N real labels, **(B)** description-only zero-shot, and **(C)** Rulebook plus old-Team history (Weak Labels), scored against real post-split labels. Measure detection lag, containment, the new-Team learning curve, and **Coverage Recovery**.
- [ ] **Pre/post training comparison:** two LightGBM models of equal size, trained before and after the split, evaluated on the same test window.
- [ ] Set the retraining trigger N from the learning curve.

**Learn:** concept drift and monitoring (DMLS ch. 8–9); weak supervision (Ratner et al., 2017, *Snorkel*); few-shot learning.

**Checkpoint:** a backtest report stating, from data, how quickly the system detected the split and recovered, and whether (C) beats (B).

---

### Milestone 9: Serving

**Prerequisites:** M7 (M8 optional for the first deploy).

- [ ] **`export_onnx.py`:** merge LoRA (`merge_and_unload()`), export to ONNX (if tracing fails, try `attn_implementation="eager"` and `reference_compile=False`), apply `onnxruntime.quantization.quantize_dynamic` INT8. Measure size and the F1 change on **validation**.
- [ ] **`app.py`:** `POST /triage` (clean → Team model → calibrated probabilities → Routing Decision → Duplicate candidates) and `POST /feedback`.
- [ ] **`Dockerfile`:** CPU-only image with `onnxruntime`, without PyTorch/CUDA.
- [ ] **Latency report** per the protocol in §3.6.

**Learn:** affine INT8 quantization (scale, zero-point); serving trade-offs (DMLS ch. 7).

**Checkpoint:** `docker run -p 8000:8000 pointsman` serves `/triage`; P50/P95 latency by length bucket is reported.

---

### Milestone 10: Final evaluation & write-up

**Prerequisites:** all above; the live scoring rule from M2 is satisfied.

- [ ] **Replay Experiment** (`replay.py`): low-confidence versus random review.
- [ ] **Live scoring** per the pre-written rule: baseline versus fine-tuned on the same frozen Issues.
- [ ] **Open the test set once**; fill in the scorecard.
- [ ] **README:** scorecard, Coverage curve, split backtest, limitations.

**Learn:** active learning and uncertainty sampling; communicating results honestly.

**Checkpoint:** README published with measured numbers only.

---

## 6. Stretch goals

- **LLM benchmark (D):** an LLM given the full Triage Rulebook routes Issues zero-shot, compared against approaches A–C in M8 and against the fine-tuned model.
- Zero-shot Team Prototypes initialized from Rulebook descriptions.
- Multi-label routing (version B of the target).
- DVC, if manual snapshot versioning proves painful.
- A webhook-based Label Event source on a repo you control.

---

## 7. Known limitations (keep updated)

- Issue bodies are fetched as they are today, not as originally filed.
- The Replay Experiment uses real triager labels but cannot model reviewer error or automation bias (reviewers accepting the model's suggestion).
- Weak Labels come from this project's interpretation of the Rulebook, not from triagers.
- As an outsider, Label Events are polled, not pushed; detection lag includes any time the poller was down.
- Self-labeled Issues may differ in style from external user reports.

---

## 8. Final scorecard (fill in from measurements only)

| Model | Max input length | Routed-Issue Macro F1 (test) | Coverage @ 90% accuracy | P50 / P95 CPU latency | Size |
| :--- | :--- | :--- | :--- | :--- | :--- |
| Keyword rules | N/A | | | | |
| TF-IDF + LogReg | Bag-of-words | | | | |
| TF-IDF + metadata + LightGBM | Bag-of-words | | | | |
| ModernBERT + LoRA (FP32) | | | | | |
| ModernBERT merged, ONNX INT8 | | | | | |

| Duplicate retrieval | Recall@5 |
| :--- | :--- |
| TF-IDF cosine | |
| Off-the-shelf embeddings | |
| Fine-tuned embeddings (stretch) | |

| Split backtest (accessibility, 2024-08-14) | Value |
| :--- | :--- |
| Detection lag | |
| Post-split Issues contained in Human review | |
| New-Team F1: (A) wait / (B) description / (C) Weak Labels | |
| Coverage Recovery | |

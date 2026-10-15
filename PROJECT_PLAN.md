# Neural Triage: Automated GitHub Issue Routing & Duplicate Detection Engine

An end-to-end production machine learning system that ingests live GitHub issues, prevents temporal data leakage via DuckDB, benchmarks a classical LightGBM model against a LoRA-fine-tuned `ModernBERT` Transformer, and serves calibrated routing probabilities + 768-dimensional semantic duplicate vectors in under 15ms via an INT8-quantized ONNX microservice.

---

## 1. System Architecture & Target Spec

```text
[GitHub GraphQL API] 
       │
       ▼ (Phase 1: Prefect + Pydantic + Regex Parser)
[DuckDB / Parquet Feature Store] ──► Strict Temporal Split (Train / Val / Test)
       │
       ├──► (Phase 2: Classical Baseline) ──► TF-IDF + Metadata + LightGBM (Macro F1: ~0.72)
       │
       └──► (Phase 3: Deep Fine-Tuning)   ──► ModernBERT-base + LoRA (Macro F1: ~0.88)
                                                     │
       ┌─────────────────────────────────────────────┘
       ▼ (Phase 4: Merge LoRA -> ONNX INT8 Quantization + Temperature Calibration)
[FastAPI Production Server (POST /triage)] ──► P95 Latency: ~15ms on CPU
       │
       ├──► 1. Team Routing Probabilities (8 Engineering Teams)
       ├──► 2. Semantic Vector Search in DuckDB (Flags Duplicate Bugs >= 0.88 Cosine Sim)
       └──► 3. Confidence Gate:
               ├─ If max(P) >= 0.65 ──► AUTO_ASSIGN Ticket
               └─ If max(P) <  0.65 ──► HUMAN_REVIEW_QUEUE ──► Feeds back to DuckDB for Retraining
```

### Core Specifications
* **Target Repository:** `microsoft/vscode` or `pytorch/pytorch` (30,000–50,000 historical closed issues with component labels).
* **Multi-Task Outputs (Single Forward Pass):**
  1. **Component Classification:** Calibrated probability distribution across 8 core engineering teams.
  2. **Duplicate Detection:** 768-dimensional pooled semantic vector queried via Cosine Similarity against existing open issues.
  3. **Uncertainty Gate:** Automatic fallback to a human review queue when maximum calibrated Softmax probability is `< 0.65`.
* **Hardware Budget ($0 Cost):**
  * **Local CPU:** Data engineering, DuckDB, LightGBM baseline, ONNX quantization, FastAPI serving, Docker containerization.
  * **Free Cloud GPU (Google Colab T4 / Kaggle):** Phase 3 LoRA fine-tuning (~25–40 minutes).

---

## 2. Production Repository Structure

```text
neural-triage/
├── data/                        # Git-ignored local storage
│   ├── raw/                     # Raw JSON batches from GitHub API
│   ├── processed/               # train.parquet, val.parquet, test.parquet
│   └── triage.duckdb            # Analytical store & 768-d vector index
├── models/                      # Saved model artifacts
│   ├── baseline/                # tfidf.joblib, lgbm_model.txt
│   ├── modernbert_lora/         # adapter_model.safetensors, tokenizer.json
│   └── onnx/                    # triage_model_int8.onnx, calibration_temp.json
├── notebooks/                   # Exploration & Colab GPU training
│   ├── 01_eda_and_leakage.ipynb
│   ├── 02_error_analysis.ipynb
│   └── 03_colab_lora_finetune.ipynb
├── src/
│   ├── pipeline/                # Phase 1: Data Engineering
│   │   ├── schemas.py           # Pydantic models for raw & cleaned issues
│   │   ├── ingest.py            # Async GitHub GraphQL/REST fetcher
│   │   ├── clean.py             # Regex parser (separates prose vs stack traces)
│   │   └── split.py             # Temporal split & DuckDB Parquet exporter
│   ├── baseline/                # Phase 2: Classical ML
│   │   ├── features.py          # TF-IDF + tabular metadata ColumnTransformer
│   │   └── train_lgbm.py        # Logistic Regression & LightGBM + MLflow logging
│   ├── finetune/                # Phase 3: Deep Learning & LoRA
│   │   ├── dataset.py           # Hugging Face Dataset & tokenization wrapper
│   │   ├── model.py             # ModernBERT + PEFT LoRA config + pooling head
│   │   └── train.py             # PyTorch/HF Trainer with Macro-F1 evaluation
│   └── serving/                 # Phase 4: Production Inference & Loop
│       ├── export_onnx.py       # Merge LoRA -> Export ONNX -> Quantize INT8
│       ├── calibrate.py         # Temperature scaling optimizer
│       └── app.py               # FastAPI server (/triage & /feedback endpoints)
├── tests/                       # Pytest suite for data cleaning & API routes
├── Dockerfile                   # Lightweight CPU production container
├── pyproject.toml               # Dependencies managed via uv / poetry
└── PROJECT_PLAN.md              # Master roadmap and architectural spec
```

---

## 3. The 5-Week Execution & Learning Roadmap

### Phase 1 (Week 1): Data Pipeline, Validation, & Leak-Free Temporal Splitting

#### Engineering Tasks
- [ ] **Initialize Project:** Set up `pyproject.toml` with `duckdb`, `pyarrow`, `pydantic`, `httpx`, `prefect` (or `dagster`), and `scikit-learn`.
- [ ] **Build `src/pipeline/ingest.py`:** Fetch 30,000+ closed issues from GitHub GraphQL API (`title`, `body`, `created_at`, `author_association`, `labels`).
- [ ] **Build `src/pipeline/schemas.py` & `clean.py`:**
  - Validate payloads with Pydantic.
  - Strip HTML comments (`<!-- ... -->`) and bot boilerplate.
  - Extract fenced code blocks (` ```...``` `) and stack traces into a separate `code_blocks` column so natural language and code can be formatted cleanly.
  - Filter and map noisy repository labels into 8 canonical engineering team classes.
- [ ] **Build `src/pipeline/split.py`:** Load cleaned data into DuckDB and sort strictly by `created_at` (ascending):
  - `train.parquet`: Oldest 70% of issues
  - `val.parquet`: Next 15% of issues ( chronologically after `train`)
  - `test.parquet`: Most recent 15% of issues (locked away until final evaluation)

#### ML Theory Curriculum (Just-in-Time Study)
- [ ] **Temporal Data Leakage:** Understand why random `train_test_split` leaks future bug outbreaks into training data and artificially inflates validation metrics.
- [ ] **Class Imbalance & Label Noise:** Analyze label distribution skew in DuckDB and compute inverse class weights.
- [ ] **Resources:** *Designing Machine Learning Systems* by Chip Huyen (Ch. 3 & 4); *StatQuest: Training, Validation, and Test Sets*.

#### Phase 1 Checkpoint
- [ ] Running `python -m src.pipeline.split` outputs `train.parquet`, `val.parquet`, and `test.parquet` where `max(train.created_at) < min(val.created_at) < min(test.created_at)`.

---

### Phase 2 (Week 2): Classical ML Baseline & Error Analysis

#### Engineering Tasks
- [ ] **Build `src/baseline/features.py`:** Create a feature pipeline combining:
  - **Unstructured Text:** `TfidfVectorizer(max_features=15000, ngram_range=(1, 2), sublinear_tf=True)`
  - **Structured Metadata:** `title_char_len`, `body_char_len`, `num_code_blocks`, `has_stack_trace`, `is_member_or_contributor`
- [ ] **Build `src/baseline/train_lgbm.py`:**
  - Train a balanced `LogisticRegression` model and a `LightGBM` (`LGBMClassifier`) model on `train.parquet`.
  - Track training duration, single-sample CPU latency, Confusion Matrix, and **Macro F1-Score** on `val.parquet` using **MLflow**.
- [ ] **Complete `notebooks/02_error_analysis.ipynb`:**
  - Inspect the top 30 high-confidence errors made by LightGBM.
  - Document specific failure modes (e.g., keyword collision where a user mentions `"terminal"` in the prose, but the stack trace originates in `"extension-host"`).

#### ML Theory Curriculum (Just-in-Time Study)
- [ ] **Sparse Representations:** TF-IDF math and bag-of-words limitations (loss of word order and long-range code dependency).
- [ ] **Linear Classification & Cross-Entropy Loss:**
  $$\mathcal{L} = -\sum_{i=1}^{K} y_i \log(\hat{y}_i)$$
- [ ] **Gradient Boosted Decision Trees (GBDT):** How LightGBM fits sequential decision trees to the negative gradients (residual errors) of the loss function.
- [ ] **Evaluation Metrics:** Precision vs. Recall, Precision-Recall AUC, and why **Macro F1** is superior to Accuracy for multi-class imbalanced problems.
- [ ] **Resources:** *StatQuest: Logistic Regression*, *StatQuest: Gradient Boost*, *StatQuest: Confusion Matrix & F1 Score*.

#### Phase 2 Checkpoint
- [ ] Saved `lgbm_model.txt` achieving ~0.68–0.74 Macro F1 on `val.parquet` with < 5ms inference latency and documented error patterns.

---

### Phase 3 (Weeks 3–4): Fine-Tuning ModernBERT with LoRA & Vector Search

#### Engineering Tasks
- [ ] **Build `src/finetune/dataset.py`:**
  - Format inputs as: `"[TITLE] {title} \n [PROSE] {clean_body} \n [CODE] {code_blocks}"`.
  - Tokenize using `answerdotai/ModernBERT-base` with `max_length=2048` (leveraging RoPE and local-global attention so stack traces are never truncated at 512 tokens).
- [ ] **Build `src/finetune/model.py`:**
  - Load `AutoModelForSequenceClassification.from_pretrained("answerdotai/ModernBERT-base", num_labels=8)`.
  - Configure Hugging Face `peft` `LoraConfig`:
    - `r=16`, `lora_alpha=32`, `lora_dropout=0.05`
    - `target_modules=["Wqkv", "Wo", "Wi"]`
  - Verify trainable parameters represent `< 2%` of total model parameters.
- [ ] **Build `src/finetune/train.py` (Run on Colab T4 / Kaggle GPU):**
  - Train for 3 epochs using `AdamW`, `lr=2e-4`, linear warmup (`warmup_ratio=0.1`), cosine learning rate schedule, `bf16=True` (or `fp16=True`), and class-weighted Cross-Entropy loss.
  - Log validation Macro F1 every 250 steps and save best LoRA adapter weights (`adapter_model.safetensors`).
- [ ] **Build Duplicate Vector Index in DuckDB:**
  - Extract the normalized 768-dimensional pooled hidden state (`[CLS]` / mean pooling before the classifier head) for open issues and store them in DuckDB using its `ARRAY` / `FLOAT[768]` vector similarity functions (`array_cosine_similarity`).

#### ML Theory Curriculum (Just-in-Time Study)
- [ ] **Subword Tokenization & Embeddings:** How Byte-Pair Encoding (BPE) handles unseen function names and hexadecimal memory addresses.
- [ ] **Scaled Dot-Product Self-Attention:**
  $$\text{Attention}(Q, K, V) = \text{softmax}\left(\frac{QK^T}{\sqrt{d_k}}\right)V$$
- [ ] **Low-Rank Adaptation (LoRA):** Freezing pretrained weight matrix $W_0 \in \mathbb{R}^{d \times k}$ and learning low-rank matrices $A \in \mathbb{R}^{r \times k}$ and $B \in \mathbb{R}^{d \times r}$ where $r \ll d$:
  $$h = W_0 x + \frac{\alpha}{r} B A x$$
- [ ] **Vector Spaces & Cosine Similarity:** Why fine-tuned domain embeddings cluster duplicate bugs far better than generic off-the-shelf embeddings.
- [ ] **Resources:** *3Blue1Brown: Attention in Transformers*; *Hugging Face Course (Ch. 2, 3, & PEFT docs)*.

#### Phase 3 Checkpoint
- [ ] Fine-tuned `ModernBERT + LoRA` model beats the LightGBM baseline by `+0.12 to +0.16 Macro F1` on `val.parquet` (~0.86+ Macro F1) and retrieves true duplicate issues in top-3 Cosine Similarity matches.

---

### Phase 4 (Week 5): ONNX INT8 Quantization, Calibration, & FastAPI Microservice

#### Engineering Tasks
- [ ] **Build `src/serving/export_onnx.py`:**
  - Merge LoRA weights into the base model via `model = model.merge_and_unload()`.
  - *Implementation Note for ModernBERT:* Set `model.config.reference_compile = False` and `attn_implementation="eager"` prior to ONNX export so PyTorch tracing doesn't collide with Triton/Dynamo compilation.
  - Export to ONNX and apply **INT8 Dynamic Quantization** via `onnxruntime.quantization.quantize_dynamic`.
  - Verify artifact size drops from ~595 MB (`FP32`) to **~148 MB (`INT8`)** and verify Macro F1 drop on `test.parquet` is `< 0.01`.
- [ ] **Build `src/serving/calibrate.py`:**
  - Fit a single scalar Temperature parameter $T$ using L-BFGS on `val.parquet` logits to minimize Expected Calibration Error (ECE):
    $$P(\text{class}_i) = \frac{\exp(z_i / T)}{\sum_{j=1}^{K} \exp(z_j / T)}$$
- [ ] **Build `src/serving/app.py` (FastAPI):**
  - `POST /triage`: Cleans raw issue JSON, runs single ONNX Runtime session (`CPUExecutionProvider`), returns calibrated team probabilities, queries DuckDB for top duplicate issue (`cosine_similarity >= 0.88`), and returns `AUTO_ASSIGN` if `max(P) >= 0.65` or `HUMAN_REVIEW_QUEUE` if `max(P) < 0.65`.
  - `POST /feedback`: Logs human-corrected labels for low-confidence predictions into DuckDB's `retraining_feedback` table.
- [ ] **Build `Dockerfile`:** Containerize the FastAPI app + `onnxruntime` + `triage_model_int8.onnx` (excluding heavy PyTorch/CUDA dependencies from the serving image).

#### ML Theory Curriculum (Just-in-Time Study)
- [ ] **Post-Training Quantization (FP32 to INT8):** Affine quantization scale and zero-point math for fast CPU SIMD instructions.
- [ ] **Confidence Calibration:** Why modern neural networks are overconfident and how Temperature Scaling fixes probability reliability for downstream business rules.
- [ ] **Active Learning & Continual Retraining:** Uncertainty sampling and closing the data flywheel.

#### Phase 4 Checkpoint
- [ ] `docker run -p 8000:8000 neural-triage` starts cleanly and serves `POST /triage` requests in **< 20ms P95 latency** on CPU.

---

## 4. Final Benchmark Scorecard (Update Upon Completion)

Evaluate every stage on the locked `test.parquet` split and publish this table at the top of your `README.md`:

| Model Architecture | Context Window | Test Macro F1 | P95 CPU Latency | Disk Size | Duplicate Vector Search |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **1. Keyword / Regex Rules** | N/A | `0.48` *(est)* | `1 ms` | `< 1 MB` | No |
| **2A. TF-IDF + Logistic Regression** | Bag-of-Words | `0.67` *(est)* | `2 ms` | `12 MB` | No |
| **2B. TF-IDF + Metadata + LightGBM** | Bag-of-Words | `0.73` *(est)* | `4 ms` | `18 MB` | No |
| **3. ModernBERT-base + LoRA (FP32)** | 2,048 tokens | `0.87` *(est)* | `58 ms` | `595 MB` | Yes (768-d embedding) |
| **4. ModernBERT Merged + ONNX INT8** | 2,048 tokens | **`0.86`** *(est)* | **`15 ms`** | **`148 MB`** | **Yes (768-d embedding)** |
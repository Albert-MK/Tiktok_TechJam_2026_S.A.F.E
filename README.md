# Beyond Retrieval: Conversational E-Commerce Search via Bayesian Inverse Inference

**TechJam Conversational E-Commerce Search Challenge** — an agent that finds a hidden target product in a 50,000-item catalog within 10 dialogue turns.

Instead of scoring products by text similarity, we ask the inverse question: *which product, run through the customer's generative process, would produce exactly the words I heard?* Paired with a decision-theoretic dialogue policy derived from the scoring formula itself, this reaches **TechnicalScore 0.9802** with **zero LLM calls and zero tokens**.

---

## Results at a Glance

| Metric | Public set (200) | Customer probe (187) |
| --- | --- | --- |
| **TechnicalScore** | **0.9802** | **0.9799** |
| Hit@10 | 1.000 | 1.000 |
| MRR | 1.000 | 1.000 |
| MTTC | 1.99 | 2.01 |

| Engineering | Value |
| --- | --- |
| Model calls | 0 |
| Tokens | 0 |
| Dependencies | Python 3.10+ standard library only |
| Index build | 7.2 s |
| Resident memory | 191 MB |
| Per-turn latency | 78.8 ms mean (p50 27.1 ms) |

Theoretical score ceiling on the public set: **~0.983**. Our gap is bounded by information limits in the task itself, not implementation bugs.

---

## The Challenge

Each session presents an anonymized user profile and a short customer message. The agent may, on every turn:

- ask a clarification question (`message` + `ask_attribute`);
- return up to 10 ranked `parent_asin` recommendations;
- do both in the same response.

The session ends when the target appears in the scored Top-10 or after turn 10.

**Scoring:**

```text
TechnicalScore = 0.50 × Hit@10 + 0.30 × MRR + 0.20 × Efficiency
Efficiency = clip((11 - MTTC) / 10, 0, 1)
```

**Four session types:** Buying (40%), Browsing (40%), Intent Override (15%), Boundary (5%).

> The evaluator locks rank the moment the target first enters Top-10. Hitting at rank 1 in fewer turns matters as much as hitting at all.

---

## Our Journey: Baseline → v1.5 → v2.0

### Phase 1 — Build an active dialogue agent (v0.1 ~ v1.0)

The official BM25 baseline never asks questions and scores **0.107**. The breakthrough was realizing that **asking is the biggest single gain**:

| Version | Key change | TechnicalScore |
| --- | --- | --- |
| Baseline | Stateless BM25, no questions | 0.107 |
| v0.2 | Slot extraction + typed questioning | 0.666 |
| v0.3 | Ask `other` first (dump long constraints fast) | 0.738 |
| v0.5 | Intent Override: keep old slots, don't reset | 0.773 |
| v0.7 | Exact phrase recall + category AND | 0.850 |
| v0.9 | Exclude previously shown non-hits | 0.874 |
| **v1.0** | Re-ask `other` after empty typed reply (Boundary fix) | **0.882** |

Three lessons that carried forward:
1. **Questions unlock information** — the simulator only discloses constraints when asked correctly.
2. **Override is continuous** — the target product never changes; don't wipe session memory on override.
3. **Misses are free evidence** — if the session continues, last turn's Top-10 definitively excludes those products.

### Phase 2 — Push retrieval to its ceiling (v1.1 ~ v1.5)

With 100% hit rate achieved, the bottleneck shifted to **rank** and **turn efficiency**:

- Fine-grained reranking: leaf category boost, distinctive phrase weighting, store match, entry prefix consistency.
- **Strategic delayed submission**: waiting one turn costs 0.02 efficiency points; moving from rank 8 to rank 1 gains +0.26 MRR points. Submit empty recommendations early, gather constraints, then strike at rank 1.

| Version | Key change | MRR | TechnicalScore |
| --- | --- | --- | --- |
| v1.4 | Delay submission when no hard constraint on turn 1 | 0.812 | 0.911 |
| **v1.5** | Delay until 2 constraints + lower title BM25 weight | **0.825** | **0.915** |

### Phase 3 — Hit the ceiling, then change paradigm (v7/v8 → v2.0)

Adaptive entropy-based questioning (v7) and profile-guided branching (v8) both **degraded** performance. Ablations confirmed the root cause: degrading v2.0 back to batch Top-10 submission scores **0.9109** — essentially v1.5's ceiling. Retrieval had been tuned to its limit.

**v2.0 reframes the task as Bayesian inverse inference:**

```
log P(target = p | dialogue) = log Prior(p) − Σ penalty_t(p)
```

| Pillar | What it does |
| --- | --- |
| **Rating-count prior** | `P(target) ∝ rating_number` — target median 6,846 ratings vs. catalog median 12; turn-1 top-1 accuracy 35.0% (ceiling 37.1%) |
| **Counterfactual belief tracking** | Replay each candidate through the customer model; score positive, negative, and elimination evidence |
| **Sequential single-guess** | Submit 1 candidate per turn, not Top-10; one extra turn costs 0.02, rank-1→rank-2 costs 0.15 (+0.069 over batch) |
| **Optimal experimental design** | Pick the question that maximizes expected score after candidate splitting |

| | v1.5 | **v2.0** |
| --- | --- | --- |
| TechnicalScore | 0.9148 | **0.9802** |
| MRR | 0.825 | **1.000** |
| MTTC | 2.64 | **1.99** |

Full architecture write-up: [`docs/ARCHITECTURE_V2.md`](docs/ARCHITECTURE_V2.md)  
Complete iteration log: [`docs/VERSION_HISTORY.md`](docs/VERSION_HISTORY.md)  
Demo website copy (EN): [`docs/WEBSITE_PAGES_AND_SCRIPT_EN.md`](docs/WEBSITE_PAGES_AND_SCRIPT_EN.md)

---

## Architecture (v2.0)

```text
starter/
  user_model.py     customer generative model (byte-for-byte faithful to evaluator)
  catalog_index.py  intent cards, rating-count prior, inverted indexes
  belief.py         Bayesian posterior over 50k catalog items
  policy.py         optimal question selection + sequential submission schedule
  agent.py          orchestrator (reset / respond)
```

**Robustness** (`tools/robustness.py`):

| Intent source | Wording | Score | Hit@10 |
| --- | --- | --- | --- |
| Official | Verbatim | 0.9802 | 1.000 |
| Official | Paraphrased | 0.9743 | 1.000 |
| Foreign | Verbatim | 0.8939 | 0.950 |
| Foreign | Paraphrased | 0.8294 | 0.915 |

Three fail-safes: longest-category reverse lookup, uninformative-response fallback, IDF-weighted keyword coverage matching.

---

## Quick Start

### 1. Download the catalog

Download `catalog.jsonl.gz` from the GitHub Release, then:

```bash
gzip -dk catalog.jsonl.gz
mv catalog.jsonl data/catalog.jsonl
```

Verify with the published `SHA256SUMS` file.

### 2. Run evaluation

Python 3.10+ recommended. No third-party dependencies.

```bash
python -m evaluator.local_evaluator
```

Writes per-session results and aggregate metrics to `results.json`.

The included weak BM25 baseline scores Hit@10 `0.125`, MRR `0.068`, MTTC `9.81`. See [`docs/baseline_results.json`](docs/baseline_results.json).

### 3. Reproduce our results

```bash
python -m evaluator.local_evaluator                              # public set (200)
python -m evaluator.local_evaluator --dataset data/customer_probe.jsonl
python evaluate_with_transcripts.py --output-dir local/public_eval
python -m unittest discover -s tests -t .
python tools/sweep.py                                             # ablations
python tools/robustness.py                                        # paraphrase / foreign-intent tests
```

---

## Agent Interface

```python
class Agent:
    def reset(self, session_id: str, user_profile: dict) -> None: ...

    def respond(self, session_id: str, user_message: str, turn: int, top_k: int) -> dict:
        return {
            "message": "Do you have a material preference?",
            "ask_attribute": "material",
            "recommendations": [{"parent_asin": "B000..."}],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0}
        }
```

`ask_attribute` is one of `category`, `material`, `color`, `size`, `style`, `brand`, `budget`, `feature`, `use_case`, `other`, or `null`. See [`docs/agent_api_contract.json`](docs/agent_api_contract.json).

---

## Repository Layout

```text
starter/                          current v2.0 agent
docs/ARCHITECTURE_V2.md           v2.0 architecture report (start here)
docs/VERSION_HISTORY.md           baseline → v2.0 iteration log
docs/EXPERIMENTS.md               experiment index
docs/WEBSITE_PAGES_AND_SCRIPT_EN.md  demo website copy (English)
snapshots/v1.5/                   frozen v1.5 retrieval champion
snapshots/v2.0/                   frozen v2.0 with ablations
tools/sweep.py                    ablations and parameter sweeps
tools/robustness.py               adversarial paraphrase harness
tools/probe_*.py                  design-measurement probes
evaluator/local_evaluator.py      public-set simulator and scorer
data/public_set.jsonl             200 labeled development sessions
```

---

## Key Takeaways

1. **Mechanism depth beats brute-force compute** — understanding the customer's generative process and the rating-count prior outperforms expensive general LLMs at zero token cost.
2. **Decision theory removes calibration error** — the sequential single-guess policy derived from the scoring utility drives MRR to 1.000.
3. **Know when to change paradigm** — v1.5 exhausted retrieval; the +0.065 gain came entirely from reframing the problem as inverse inference.

---

## Data & Attribution

Catalog and sessions are derived from [Amazon Reviews 2023](https://amazon-reviews-2023.github.io/) by McAuley Lab, UCSD. See [`DATA_ATTRIBUTION.md`](DATA_ATTRIBUTION.md) before redistributing.

Competition rules: [`docs/competition_specification.md`](docs/competition_specification.md)  
Submission policy: [`docs/submission_rules.md`](docs/submission_rules.md)

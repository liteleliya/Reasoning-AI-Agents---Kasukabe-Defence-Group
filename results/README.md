# Experiment results

This folder separates early pipeline checks from the saved paired recovery study. Figures and aggregate summaries are retained for review; full local run archives are kept on the machine that generated them and are excluded from routine publication by the root `.gitignore`.

## Study sequence

| Stage | Question | Recorded outcome | How to interpret it |
|---|---|---|---|
| **J1 - protocol parsing** | Can the model return a valid structured PXP message? | 49/50 valid on the first attempt; 50/50 after one repair retry. | A parser/prompt smoke check, not a reasoning benchmark. |
| **J2 - baseline dialogue** | Can agents complete the earlier 100-item dialogue run? | 100/100 sessions ended in consensus, with no recorded impasse or cap stop. | Consensus rate is not answer correctness or intelligibility. This earlier exploratory run used the Qwen2.5 7B family. |
| **J3 - preliminary counterfactual pilot** | Do replay events appear in a broader run? | 117/120 trials ended in consensus; three ended in impasse; no counterfactual rollbacks were recorded. | This run gives no estimate of replay's effect because no replay occurred. |
| **Paired 3B baseline** | Does replay improve correct recovery after a shared checkpoint? | 52 of 144 prefixes opened a checkpoint. Correct recovery was 1/52 standard, 0/52 forward rethink, and 1/52 replay. | Inconclusive; replay did not outperform standard and required more tokens. The model/setup and automatic grading limitations are detailed below. |

J1/J2/J3 were exploratory milestones and should not be pooled with the final paired baseline. The final study used a Qwen2.5 3B Instruct build (3.09B parameters, Q4_K_M); the 7B tests used different experiment settings and do not establish a causal model-size comparison.

## Final paired baseline

The experiment has 144 case-by-seed units and 432 arm outcomes. Each unit has one shared prefix and three continuations. A checkpoint is counted once at the prefix level. The observed replay funnel was 52 eligible and attempted, 51 completed comparisons, 10 helpful comparisons, 10 adopted replies, and one correct recovery. Outcomes were 41 not-helpful and one incomplete. Replay used a mean of 19,578.9 full-trial tokens per eligible item, compared with 13,449.8 for standard continuation.

Replay versus standard produced one win, one loss, and 50 ties on correct recovery; the observed difference was 0.0 percentage points (case-bootstrap interval approximately -5.4 to +5.8 pp). Replay versus forward produced one win and 51 ties (observed +1.9 pp, interval approximately 0 to +6.5 pp). Both estimates are based on 52 eligible pairs and do not establish an advantage.

These results use automatic answer checks only: **no human rubric grades were joined to this run**. Several authored checkpoint predictions did not resolve to the answer schema, one automatically correct replay recovery began from malformed predictions, and three replay arms exceeded the intended six-call post-checkpoint allowance. The saved run README has the trace audit and exact qualifications. A checkpoint rate from the dissenter setup is conditional on that deliberately disagreement-rich configuration; it is not the natural frequency of organic stalls.

## Reviewable files

- `figures/summary.csv` and `figures/*.png` / `figures/*.pdf` contain the historical J3 aggregate results and charts.
- `paired-study/analysis/analysis.json` and `outcome_table.csv` contain the paired analysis and per-arm aggregate table.
- `paired-study/analysis/*.png` contain the paired outcome, funnel, and comparison charts.
- `paired-study/README.md` documents run provenance, checks, data quality issues, limitations, and how the analysis was generated.

The raw experiment directory is useful for reopening sessions in the viewer. Its `shard-1-of-1/` folder contains `board.sqlite`, `metrics.csv`, `calls.jsonl`, `opportunities.jsonl`, and `run.json`; `analysis/` contains the derived aggregate outputs. These raw files are local and ignored in a clean publication. Do not publish `grading/private.json`, which maps blind IDs to conditions and includes automatic hints. Do not give it to blinded graders.

To analyze the saved run again from the repository root:

```powershell
uv run python -m bench.paired_analysis results/paired-study/shard-1-of-1 --out results/paired-study/analysis
```

# PXP-N specification (stub)

Status: **draft, to be completed in the joint A1 session.**

This document extends the two-party PXP protocol (Baskar et al., arXiv:2301.01819) to N agents
sharing a blackboard. Every ambiguous choice gets an entry in the decision log below, with the
option chosen and the reason.

## 1. Tags

| Tag | Meaning (paper default, to confirm) |
|---|---|
| INIT | Opens a session / first prediction + explanation on an instance |
| RATIFY | Accepts the other agent's prediction and explanation |
| REVISE | Changes own prediction and/or explanation in response to another message |
| REFUTE | Disagrees and supplies corrective information |
| REJECT | Cannot understand / will not engage with the other's explanation |
| TERM | Closes the session |

## 2. N-agent interaction model

TBD (see decision 2).

## 3. Intelligibility

- **One-way intelligible interaction:** TBD (from the paper's definition).
- **Strong:** every interaction in the session is one-way intelligible.
- **Ultra-Strong:** Strong plus at least one REVISE.
- **Failed:** TBD.

## 4. Session termination

Consensus, impasse, iteration cap: TBD.

## 5. Open decisions

Defaults in brackets. Each is tracked as a GitHub issue with the `decision` label.

1. **Tag semantics.** [Follow the paper: REJECT = cannot understand; REFUTE = disagree with corrective information.] The course proposal words them differently.
2. **Pairwise PXP on an N-agent board.** [Every message has a `reply_to`, so each interaction is a pair.]
3. **"Productive" REVISE.** [A REVISE that follows a REFUTE/REJECT and after which consensus distance falls within a few events.]
4. **Rollback simulation.** [Re-query the other agents once with the altered message; count those tokens toward H3.]
5. **Deadlocks may be rare on one 7B model.** [Measure the baseline deadlock rate in M2; if low, add persona diversity, temperature, or a second model.]
6. **Correctness rule for ROUGE-scored benchmarks.** [Fix the rule (threshold or LLM judge) before looking at results.]

## 6. Decision log

| # | Date | Decision | Chosen | Rationale |
|---|---|---|---|---|
| | | | | |

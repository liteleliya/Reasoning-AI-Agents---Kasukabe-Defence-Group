# Per-trial metrics CSV

One row per finished trial (one instance x config x seed), written by `bench.metrics.MetricsWriter`.
The file is append-only and fsynced per row; `trial_key` is unique and is what a resumed run skips.

| Column | Meaning |
|---|---|
| `trial_key` | `config|benchmark|instance_id|seed` |
| `config` | Name of the experiment config (e.g. `cf-33`) |
| `benchmark`, `domain`, `instance_id` | Which question |
| `seed` | Random seed of the trial |
| `model` | Model id used by the agents |
| `n_agents`, `n_counterfactual`, `cf_share` | Independent variable: share of counterfactual-enabled agents |
| `session_id` | Session in the event log (for drilling into the UI) |
| `stop_reason` | `consensus`, `impasse` or `cap` |
| `converged` | H1: `stop_reason == consensus` |
| `answer` | The session's final answer: the consensus answer, else the most common latest prediction |
| `correct` | Judge verdict on the consensus answer (D2); empty if not judged |
| `messages` | Agent messages including INIT (no system, no rollback events) |
| `cycles` | Reply messages / `n_agents` (rounds of discussion) |
| `ratify`, `refute`, `revise`, `reject` | Tag counts over real messages |
| `rollbacks` | Number of `rollback_start` events |
| `incompatible` | Messages that broke the compatible-agent transitions (validator warnings) |
| `rejected` | Agent messages the validator refused (off-protocol) |
| `failed_replies` | Model replies still unparseable after one repair retry (the agent passed) |
| `intelligibility` | H2: `ultra_strong`, `strong` or `failed` (spec section 3) |
| `tokens_in`, `tokens_out` | Tokens of events on the board, including rollback events |
| `unposted_tokens` | Tokens of failed replies that never reached the board |
| `total_tokens` | H3: `tokens_in + tokens_out + unposted_tokens` |
| `rollback_tokens_in`, `rollback_tokens_out` | Of which spent inside counterfactual replays |
| `wall_time_s` | Wall-clock time of the trial |

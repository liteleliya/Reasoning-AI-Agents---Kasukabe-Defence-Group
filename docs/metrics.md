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
| `stop_detail` | Why the stop reason applied: `consensus`, `message_cap`, `no_progress`, `debate_stall`, `all_passed` or `failed_turns` (spec section 4.1) |
| `decision_seq` | Last committed event when the stop was decided |
| `ledger_calls` | Model calls in the trial's call ledger (`calls.jsonl`); empty when no ledger was kept |
| `ledger_tokens_in`, `ledger_tokens_out` | Tokens over every call, including calls that failed to parse, were refused or were spent in the sandbox |
| `ledger_unposted_tokens` | Of those, tokens of calls no event lists in `meta.call_ids` |
| `ledger_missing` | Calls whose usage is unknown (they failed before a reply); they add no tokens |
| `agreement_basis` | How agreement was decided: `exact` (letters, judgment), `key` (authored decision key) or `approximate` (open QA lexical overlap; not a verified key) |
| `productive_revisions` | Replies that answer a challenge with a supported change and lower the group's distance within the next three real replies (or by a consensus stop). Separate from the Strong/Ultra-Strong `intelligibility` label |
| `arm` | `standard`, `forward` or `replay` in a three-arm paired trial; blank otherwise |
| `checkpoint` | `opened` if the shared prefix reached an eligible recovery checkpoint, else `none` (all arms then share the ordinary terminal outcome) |
| `skip_reason` | Why the checkpoint did not open or the policy did not run |
| `recovery_outcome` | What the arm's policy ended with (`reply_accepted`, `not_helpful`, `no_reply`, ...) |
| `credit_delta` | Replay arm: replacement minus original distance on the matched forks (unrounded) |
| `prefix_tokens` | Model tokens spent on the shared prefix; already inside `total_tokens` of every arm |
| `intervention_calls`, `intervention_tokens` | Model calls and tokens spent after the shared trigger |
| `grading_tokens` | Offline grading cost; never part of `total_tokens` |

With a ledger, `total_tokens` is `ledger_tokens_in + ledger_tokens_out`: every call once. The board
tokens (`tokens_in`, `tokens_out`) are the subtotal of calls that events list in `meta.call_ids`,
so `total_tokens = tokens_in + tokens_out + ledger_unposted_tokens`. Calls with estimated usage are
included; the ledger row marks them `estimated`. Without a ledger the old definition applies.
The identity holds for the checkpoint recovery path; the older opportunistic replay posts its
tokens without call ids, so for those runs `ledger_unposted_tokens` also counts calls that are on
the board, and only `total_tokens` is exact.

A `metrics.csv` written before these columns existed has a different header: the writer refuses
to append to it, so write a resumed run to a new folder.

## Call ledger (`calls.jsonl`)

One JSON line per model request, written at the client boundary, so failed and unparseable calls
are kept.

| Field | Meaning |
|---|---|
| `call_id` | `call-<n>`, unique within one client |
| `trial`, `session_id` | Which trial and session the call belongs to |
| `phase` | `debate`, `candidate` or `branch` |
| `branch` | `original` or `replacement` for branch calls |
| `repair` | The retry sent after an unusable reply |
| `parent_seq` | The message the call was made to answer |
| `agent` | Who made the call |
| `status` | `ok` or `error` |
| `usage` | `reported`, `estimated` or `missing` |
| `prompt_tokens`, `completion_tokens` | Null when usage is missing |
| `latency_s`, `detail` | Latency, and the error text for failed calls |


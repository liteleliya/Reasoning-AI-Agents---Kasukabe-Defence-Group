# Recovery fixture (X/Y/Y)

A toy three-agent case that pins down the scheduler, sandbox, metrics and viewer with one trace.
Code: `src/counterfactual/fixture.py`. Tests: `tests/test_recovery_fixture.py`. It is not part of
the benchmark.

**Case.** Service must be restored within a four-minute downtime limit. Plan X takes six minutes,
Plan Y takes two. The known answer is Y. A insists on X; B and C defend Y.

## The stalled prefix (messages #0-#8)

| Seq | Author | Tag | Replies to | Prediction | Meaning |
|---|---|---|---|---|---|
| 0-2 | A, B, C | INIT | - | X, Y, Y | two answer groups |
| 3 | A | REFUTE | 1 | X | |
| 4 | B | REFUTE | 3 | Y | |
| 5 | C | RATIFY | 4 | Y | every agent has now replied; disagreement is 1/3 |
| 6 | A | REFUTE | 4 | X | **replay target** |
| 7 | B | REFUTE | 6 | Y | **challenger** of #6 |
| 8 | C | RATIFY | 7 | Y | with a three-reply window the board stalls |

Replacing #6 with a REVISE that accepts the four-minute limit gives Y/Y/Y in the sandbox, so the
credit is 0 - 1/3 = -1/3 (negative means the alternative helps).

## Demo database

```bash
uv run python -m counterfactual.fixture --db results/roadmap_fixture.sqlite
uv run python -m server --db results/roadmap_fixture.sqlite
```

Both sessions are produced by the normal scheduler with the same scripted agents. Only the
recovery policy differs, so the checkpoint, the matched branches and the adoption are the real
ones (the model is a scripted stub that proposes the known replacement).

| Session | What happens |
|---|---|
| `toy-recovery-xy-off` | #0-#8, then TERM `impasse` (#9, `detail: debate_stall`, recovery skipped as `recovery_disabled`). Predictions stay X/Y/Y. |
| `toy-recovery-xy-on` | #0-#8, rollback #9-#16, A's real REVISE answering #7 (#17), TERM `consensus` (#18). |

In the `on` session the rollback is `rollback_start` (#9), the original branch (#10-#12: A's copied
reply, then B and C refute it), the replacement branch (#13-#15: A's REVISE, then B and C ratify it)
and `rollback_end` (#16, distances 1/3 and 0, credit -1/3). The real board is X/Y/Y at every
sequence up to #16 and Y/Y/Y from #17: the sandbox branches never move it, only the adopted real
reply does.

## Event fields used here

The full record is in [spec_pxp_n.md](spec_pxp_n.md) section 2; the replay events are described in
section 5.1. For this fixture:

| Field | Values in the fixture |
|---|---|
| `kind` | `message` for #0-#8, the adopted reply and TERM; `rollback_start`, six `rollback_step`s and `rollback_end` for the replay |
| `reply_to` | the real message replied to; on `rollback_start` it is the replayed target (6). Rollback steps have none. |
| `counterfactual` | `true` on every rollback event, `false` on the adopted reply |
| `meta` on `rollback_step` | `replay_id`, `branch` (`original` or `replacement`), `fork_seq` and `fork_reply_to` (fork-local, not real sequence numbers), `tested`, `call_ids` |
| `meta` on `rollback_end` | `replay_id`, `status`, `credit_delta` (-1/3), `distance_original` (1/3), `distance_replacement` (0), `distance_recorded`, `target_seq`, `challenger_seq`, `branch_tokens` |
| `meta` on the adopted reply | `adopted_counterfactual: true` and the `replay_id` it came from |
| TERM `explanation` | the stop reason: `impasse` or `consensus` |
| TERM `meta` | `detail`, `decision_seq` and a `recovery` summary (`eligible`, `skip_reason`, `outcome`, `replay_id`) |

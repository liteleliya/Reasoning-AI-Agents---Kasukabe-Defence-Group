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

| Session | What happens |
|---|---|
| `toy-recovery-xy-off` | #0-#8, then TERM `impasse` (#9). Predictions stay X/Y/Y. |
| `toy-recovery-xy-on` | #0-#8, rollback #9-#13, A's real REVISE answering #7 (#14), TERM `consensus` (#15). |

In the `on` session the real board is X/Y/Y at every sequence up to #13 and Y/Y/Y from #14: the
sandbox branch never moves it, only the adopted real reply does.

## Event fields used here

The full record is in [spec_pxp_n.md](spec_pxp_n.md) section 2. For this fixture:

| Field | Values in the fixture |
|---|---|
| `kind` | `message` for #0-#8, #14 and TERM; `rollback_start` (#9), `rollback_step` (#10-#12, `tag` REVISE/RATIFY/RATIFY), `rollback_end` (#13) |
| `reply_to` | the real message replied to; on `rollback_start` it is the replayed target (6). Rollback steps have none. |
| `counterfactual` | `true` on every rollback event, `false` on the adopted reply |
| `meta` on `rollback_step` | `fork_seq`, `fork_reply_to`: sequence numbers inside the fork, not the real log |
| `meta` on `rollback_end` | `credit_delta` (-0.3333), `distance_real` (0.3333), `distance_replay` (0), `target_seq` (6) |
| `meta` on #14 | `adopted_counterfactual: true` |
| TERM `explanation` | the stop reason: `impasse` or `consensus` |

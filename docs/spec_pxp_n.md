# PXP-N specification

Status: **draft for review** (issue #1). Decisions marked *proposed* are open until both reviewers approve.

This document extends the two-party PXP protocol of Baskar, Srinivasan, Bain and Coiera,
"A Model for Intelligible Interaction Between Agents That Predict and Explain"
([arXiv:2301.01819](https://arxiv.org/abs/2301.01819)), to N agents sharing a blackboard.
Section references like "paper §3.4" point to that paper.

## 1. What the paper defines (two agents)

**Messages.** A message carries a sender, a tag, the instance, a prediction and an explanation
(paper §3.3). Tags are INIT, RATIFY, REFUTE, REVISE, REJECT, TERM.

**How a tag is chosen** (paper Appendix A, Def. 5 and Table 4). When agent *n* receives
*m*'s prediction/explanation (y_m, e_m), it computes its own (y_n, e_n) and evaluates:

|                        | AGREE(e_n, e_m)          | not AGREE(e_n, e_m)      |
|------------------------|--------------------------|--------------------------|
| **MATCH(y_n, y_m)**     | RATIFY                   | REFUTE or REVISE         |
| **not MATCH(y_n, y_m)** | REFUTE or REVISE         | REJECT                   |

In the two mixed cells, *n* first learns from *m*'s message, recomputes (y_n', e_n'), and sends
**REVISE** if it now fully matches and agrees with *m* (guard g' = MATCH(y_n', y_m) and
AGREE(e_n', e_m)), otherwise **REFUTE** with its (possibly updated) prediction and explanation.
REJECT involves no learning: nothing in *m*'s message was usable. Any message may be answered
with TERM.

**Compatible agents** (paper Def. 6, Prop. 5). If both agents use the same MATCH/AGREE, some
transitions cannot happen: after RATIFY or REVISE the reply is only RATIFY or TERM; after
REJECT the reply is only REJECT or TERM.

**Bounded sessions** (paper §4.1). Self-loops (for example REFUTE answered by REFUTE) can run
forever; PXP(k) allows each self-loop at most *k* times.

**One-Way Intelligibility** (paper Def. 1). Let T_mn be the tags sent from *m* to *n* in a session.
The session is One-Way Intelligible for *m* iff T_mn contains at least one RATIFY or REVISE and
T_mn contains no REJECT. **Two-Way** (Def. 2): One-Way for both.

**Strong / Ultra-Strong** (paper Remark 6). A system is *strongly intelligible* for a human if every
interaction is One-Way Intelligible for the human; *ultra-strong* if, in addition, at least one
interaction has a REVISE in the human's messages to the system.

Worked examples from the paper §3.4.1: `INIT_m, REFUTE_h, TERM_h` is not intelligible for either
side; `INIT_m, REFUTE_h, REVISE_m, RATIFY_h, TERM_h` is Two-Way Intelligible.

## 2. PXP-N: messages on a shared board

1. **Session.** One instance (question) per session. Events have a per-session `seq` starting at 0
   and increasing by 1. Agents are identified by `author`; the scheduler writes as `system`.
2. **INIT.** Each agent's first message in a session is INIT with `reply_to = null`. It carries the
   agent's initial prediction and explanation. An agent sends exactly one INIT per session.
3. **Replies.** Every other message has `reply_to` = the `seq` of an earlier `message` event in the
   same session, written by a **different** agent, not a rollback event and not TERM.
   This turns the N-agent board into a set of pairwise PXP exchanges (decision 2).
4. **Reply tags.** RATIFY, REFUTE, REVISE, REJECT, with the meanings of §1 (decision 1).
   Every reply carries the sender's current prediction and explanation (after any revision).
5. **TERM.** Only `system` sends TERM, as the last event, with `reply_to = null`, and the stop
   reason (`consensus`, `impasse` or `cap`) in `explanation`. Agents do not TERM in v1.
6. **Compatible-agent transitions** (§1) are **not enforced**. With N agents a third party may well
   REFUTE a message that someone else RATIFIED. The validator counts violations in a warning so we
   can report how often LLM agents act "incompatibly".
7. **Consistency with predictions** is not enforced by the validator, because deciding MATCH on
   free text needs the benchmark's equivalence (for example the ROUGE rule). The analysis may report
   tags that contradict the prediction MATCH.

### Event record

```json
{"seq": 12, "session_id": "s-001", "author": "agent_b", "kind": "message",
 "tag": "REFUTE", "reply_to": 11, "prediction": "...", "explanation": "...",
 "counterfactual": false, "tokens": {"in": 812, "out": 94}, "meta": {}}
```

| Field | Rule |
|---|---|
| `seq` | int, 0-based, contiguous per session; assigned by the store, not the agent |
| `session_id` | non-empty string |
| `author` | agent id, or `system` |
| `kind` | `message`, `rollback_start`, `rollback_step`, `rollback_end` |
| `tag` | required for `message`; for `rollback_step` the (altered or replayed) tag; null otherwise |
| `reply_to` | see §2.2–2.5; for rollback events, the `seq` the rollback concerns (`rollback_start`) or null |
| `prediction`, `explanation` | strings; may be empty only for `system` and rollback start/end events |
| `counterfactual` | true for every rollback event and for messages produced inside a replay |
| `tokens` | `{"in": int >= 0, "out": int >= 0}`; zero for `system` |
| `meta` | free dict (added field): rollback id, stop reason details, warnings |

## 3. Intelligibility on the board

Only `kind = message`, `counterfactual = false` events with tags RATIFY/REFUTE/REVISE/REJECT
count. INIT and TERM are ignored, as are rollback events.

- **T_mn** = the tags of messages authored by *m* whose `reply_to` target was authored by *n*,
  in seq order.
- **Interacting pair.** An ordered pair (m, n) with T_mn non-empty.
- **One-way intelligible for (m, n)** (paper Def. 1): T_mn contains RATIFY or REVISE, and no REJECT.
  In words: *n*'s messages were intelligible to *m*.
- **Strong session:** at least one interacting pair exists, and every interacting pair is one-way
  intelligible.
- **Ultra-Strong session:** Strong, and at least one REVISE appears anywhere in the counted messages.
- **Failed:** everything else, including sessions with no replies at all.

The classifier returns the class plus the per-pair table (T_mn, one-way yes/no), so looser
alternatives can be computed afterwards without re-running (decision 7).

## 4. Termination

The scheduler checks, after every appended message:

1. **Consensus:** every agent has sent at least one reply (not only INIT), and the consensus
   distance over each agent's latest prediction is 0 (all predictions in one equivalence group).
2. **Impasse:** no agent's prediction has changed and no RATIFY or REVISE has been posted in the last
   *W* messages (default W = 2N).
3. **Cap:** the session reached `max_messages` non-system messages (default 10N).

On the first condition met, the scheduler writes TERM with that reason. H1 counts `consensus` as
success. Rollback events do not count towards W or the cap; their tokens count towards H3.

## 5. Counterfactual replay (rules the sandbox must follow)

- Only a counterfactual-enabled agent may roll back, and only its **own** past message.
- The sandbox copies events `0..s`, replaces event `s` with the altered tag/explanation (and
  optionally prediction), and **re-queries each other agent once** in response (decision 4).
- The main log records `rollback_start` (reply_to = s), one `rollback_step` per replayed message,
  and `rollback_end` (meta: credit delta). All have `counterfactual = true`; all tokens are counted.
- The original board is never modified (B4's Done-when).
- **Credit delta** = consensus distance at the end of the replay minus the real consensus distance at
  the same point in the real log. Negative = the alternative would have helped.

## 6. Open decisions

Defaults in brackets. Each is tracked as a GitHub issue with the `decision` label.

1. **Tag semantics** (#22). [Follow the paper's guard table in §1.] The course proposal glosses
   REJECT as "cannot understand" and REFUTE as "disagree with corrective information". The
   paper's actual rule is stricter: REJECT = prediction differs AND explanation disagrees, nothing
   learned; REFUTE = partial agreement that learning did not resolve. Prompts should give the table.
2. **Pairwise PXP on an N-agent board** (#23). [Every non-INIT message has a `reply_to` to another
   agent's message; §2.3.]
3. **"Productive" REVISE** (#24). [A REVISE whose `reply_to` target is a REFUTE or REJECT, or whose
   author received a REFUTE/REJECT since its previous message, and after which consensus distance
   N events later is lower than just before the REVISE.]
4. **Rollback simulation** (#25). [Re-query the other agents once with the altered message; count
   those tokens; §5.]
5. **Deadlocks may be rare on one 7B model** (#26). [Measure baseline deadlock rate in M2; if low,
   add persona diversity, temperature, or a second model.]
6. **Correctness rule for ROUGE** (#27). [Fixed before looking at results.]
7. **Strong over which pairs** (new). [Every interacting ordered pair must be one-way intelligible.
   Alternative: at least one direction per unordered pair. Both computable from the per-pair table.]

## 7. Decision log

| # | Date | Decision | Chosen | Rationale |
|---|---|---|---|---|
| 1 | 2026-09-30 | Tag semantics | Paper guard table (§1), *proposed* | Matches the reference; the proposal wording is a gloss of it |
| 2 | 2026-09-30 | N-agent pairing | Mandatory `reply_to` to another agent's message, *proposed* | Keeps every interaction pairwise so paper Def. 1 applies unchanged |
| 3 | 2026-09-30 | Productive REVISE | Default above, *proposed* | Ties REVISE to a preceding challenge and to measurable progress |
| 4 | 2026-09-30 | Rollback simulation | One re-query of each other agent, *proposed* | Bounded cost; tokens counted for H3 |
| 8 | 2026-09-30 | Who sends INIT / TERM | Every agent INITs once; only `system` TERMs | Paper has one initiator; on a board all agents need an opening position |
| 9 | 2026-09-30 | Compatible-agent transitions | Not enforced, counted as warnings | Enforcing would forbid a third agent refuting a ratified message |
| 10 | 2026-09-30 | PXP(k) self-loop bound | Replaced by impasse window W and message cap | Same purpose (bounded sessions), and simpler to reason about for N agents |
| 11 | 2026-09-30 | Extra `meta` field on events | Added | Room for rollback ids and warnings without schema changes |

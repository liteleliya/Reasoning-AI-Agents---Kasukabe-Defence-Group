# Session explorer

Start it on an archived run, with its outcomes in the list and the Results view:

```bash
uv run python -m server --db <board.sqlite> --metrics <metrics.csv> --source J3 --kind historical
npm --prefix ui run build   # once; the server serves ui/dist
```

For the controlled fixture (a stalled and a recovered session):

```bash
uv run python -m counterfactual.fixture --db results/roadmap_fixture.sqlite
uv run python -m server --db results/roadmap_fixture.sqlite --source fixture --kind controlled
```

## What each part shows

| Part | Shows |
|---|---|
| Session list | Sessions by case, condition and seed, with outcome and correctness when a metrics file is given. Search, outcome and condition filters. |
| Header tabs | The same case and seed under each condition. A tab switches session and resets the cursor. |
| Timeline | One lane per agent from the whole session, one column per real message. Events after the cursor are faded, not removed. Each tag has a shape, a colour and a label. TERM and each replay start are marked. |
| Controls | Previous, Play/Pause, Next, First challenge, Termination, and Live for a running session. |
| Inspector | The selected event: agent, tag, reply target (a link), prediction, explanation, token cost and key metadata. |
| Board | Predictions, intelligibility and tokens at the cursor, rebuilt by the server. In progress before TERM. The whole-session outcome and correctness are shown apart from it. |
| Event list | Every event as a button, replay events set apart. The keyboard way to do what clicking a node does. |
| Replay panel | For each replay the cursor has reached: the original reply and the replacement with the changes marked, both simulated continuations side by side, disagreement before and after, the signed delta, costs, and the adopted real reply once the cursor reaches it. |
| Results | Run header, per-condition counts, recovery stages and example sessions, all computed by the server. Anything the export does not record is shown as unavailable. |

The address bar keeps the open view, session and (when paused) sequence, so a link opens the same
evidence.

## Browser checklist

Automated tests render the components and check the logic, but nobody has looked at the pages in a
browser yet. Check these by hand and note the session and event ids used.

1. **Archive.** Open the J3 database. Search `2534`, pick the 2 of 3 enabled tab. Step through the
   three INITs and TERM. The replay panel says no replay was recorded and that the reason is
   unavailable.
2. **Off and on.** Open `toy-recovery-xy-off`: the board stalls at X/Y/Y, TERM at #9, the panel says
   recovery was switched off. Open `toy-recovery-xy-on`: click the replay marker (#9), open both
   continuations, then step to #17. The board should be X/Y/Y at every sequence up to #16 and
   Y/Y/Y from #17. Scrub back to #16: the adoption disappears from the panel.
3. **Live.** With `uv run python -m server --demo`, pause on a prediction while later events
   arrive: the cursor stays. Press Live: it jumps to the latest event. Stop and restart the
   server: the stream reconnects without a missing or repeated sequence number.
4. **Errors and sizing.** Switch sessions while a snapshot is loading: the old one never appears in
   the new session. Open `?session=nope`: an error, not a blank page. Tab through the list, the
   controls, the event list and the replay rows. Narrow the window below 760px: the inspector and
   replay comparison sit under the timeline and the continuations stack.
5. **Results.** Open Results for J3: 117 of 120 reached consensus, 93 correct, 0 replays logged,
   the four conditions in order, the eligible counts unavailable. Open an example: it lands on that
   session in Explore.

## Task and evidence panel

Open an authored case session (for example `case:restore-p1`): a collapsed "Task and evidence"
section sits under the session header. Expand it and check the question, context, labelled
evidence (E1, E2) and the lines under "Agents state". Open a J3 session: it says no public prompt
is stored and shows the item id. Switch sessions quickly: the previous case's task must never show
under the new one.

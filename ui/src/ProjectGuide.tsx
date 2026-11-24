const terms = [
  ["PXP message", "A structured contribution to the blackboard: a prediction, an explanation, a protocol tag, and a link to the message being answered. The format makes disagreement traceable instead of leaving it inside an unstructured chat."],
  ["RATIFY", "The agent keeps the same answer and explicitly accepts the other agent’s reasoning."],
  ["REFUTE", "The agent identifies a specific problem in the other contribution, gives corrective information, and keeps its own answer. A refutation is a recorded challenge, not proof that the challenged answer is false."],
  ["REVISE", "The agent changes its prediction in response to the discussion. Productive revision means the new answer also engages with the challenge that prompted the change."],
  ["REJECT", "The agent declines the other contribution without adopting it. Repeated rejection can be a sign that discussion is no longer making progress."],
  ["Checkpoint", "A saved, shared disagreement state that satisfies the study’s eligibility rules. Each case-and-seed prefix is counted once, before it is continued under the different study arms."],
  ["Counterfactual replay", "A bounded alternative continuation explored from a saved prefix. Its messages are marked as counterfactual and do not silently rewrite the original board history."],
  ["Rollback", "The replay mechanism’s explicit start, step, and end markers around a temporary branch. A rollback count is an operation count, not a count of recovered answers."],
  ["Adopted / accepted", "In this dashboard, an adopted replay means the replay candidate was accepted into the live answer (`reply_accepted`). Adoption describes the intervention decision; it does not mean the final answer was correct."],
  ["Recovery", "What happens after an eligible checkpoint when an arm continues. We report recovery as a funnel: attempted, completed, helpful, adopted, and finally correct consensus."],
  ["Impasse", "The dialogue stopped without reaching consensus under the run’s stopping rules. An impasse can still contain useful disagreements; it is not a correctness verdict."],
  ["Intelligibility", "Whether the event history exposes who answered whom and which reasoning moves were used. It describes inspectability of the interaction, not factual accuracy."],
];

export function ProjectGuide() {
  return <article className="guide">
    <header className="guide-hero">
      <p className="eyebrow">Project guide · research question & vocabulary</p>
      <h1>Can an inspectable replay help agents recover from disagreement?</h1>
      <p>Intelligible Blackboard studies how several language-model agents exchange structured claims, challenge one another, and decide what answer to put on a shared board. The project adapts the paper’s prediction-and-explanation dialogue idea, then focuses on a narrower, testable question: after agents reach a qualifying disagreement, does a bounded counterfactual replay help them produce a better final answer?</p>
      <p className="guide-caveat">The study compares continuation policies from the same saved prefix. It does not claim to reproduce the paper in full, and consensus alone is never treated as evidence of correctness.</p>
    </header>

    <section className="guide-workflow">
      <div><span>01</span><strong>Shared task</strong><p>Agents inspect the same case and publish a proposed answer with its reasoning.</p></div>
      <div><span>02</span><strong>Structured debate</strong><p>Each response is linked to a prior message and marked RATIFY, REFUTE, REVISE, or REJECT.</p></div>
      <div><span>03</span><strong>Checkpoint</strong><p>A qualifying disagreement is saved once as the common starting point for a matched comparison.</p></div>
      <div><span>04</span><strong>Compare outcomes</strong><p>Ordinary continuation, forward rethink, and counterfactual replay are judged against the same case rubric.</p></div>
    </section>

    <section className="guide-section">
      <div className="guide-section-head"><div><p className="eyebrow">Terms used in the interface</p><h2>Read the traces consistently</h2></div><p>Counts on the Results page describe different levels of the experiment. A checkpoint is a shared prefix; tags and rollback operations are accumulated over arm trials; adoption belongs to the replay intervention.</p></div>
      <dl className="term-grid">{terms.map(([term, definition]) => <div className="term" key={term}><dt>{term}</dt><dd>{definition}</dd></div>)}</dl>
    </section>

    <section className="guide-section guide-reading">
      <div><p className="eyebrow">How to read the results</p><h2>Separate process from answer quality</h2></div>
      <div className="reading-cards">
        <article><strong>Process signals</strong><p>Refutes, revisions, rejections, and rollbacks show what the agents did. They help explain a trace, but they are not independent wins.</p></article>
        <article><strong>Intervention decisions</strong><p>Accepted/adopted counts show how often a replay candidate entered the live answer. An adopted candidate can still be wrong.</p></article>
        <article><strong>Outcome signals</strong><p>Correct recovery requires an eligible prefix, consensus after continuation, and a correct final answer under the recorded grading source.</p></article>
      </div>
    </section>
  </article>;
}

# Steel-Man — Facilitation Guide

## What This Exercise Is

A steel-man is the opposite of a straw-man. Instead of presenting a weakened version of
the opposing argument to knock it down easily, you construct the strongest possible version
of the argument against your own proposal — and then genuinely respond to it.

This is not devil's advocate theater. The goal is to find the best objection that an
intelligent, well-informed critic would raise, and to determine whether the proposal
survives it. If the PM cannot answer the steel-manned objection, the proposal is not ready.

Steel-manning is most valuable when:
- The team has already converged on a solution and groupthink has set in
- A proposal is politically sensitive and nobody wants to voice real objections
- The PM is confident the proposal is correct but hasn't stress-tested the reasoning
- There are meaningful alternatives that haven't been seriously considered

## Priya's Role in This Exercise

Priya's job is to build the strongest possible case against the PM's proposal, then
evaluate the PM's response honestly.

**Building the steel-man:**
- Do not pull punches. A weak counter-argument is useless — it gives the PM false confidence.
- Draw on Hoopla-specific constraints: per-circulation cost, DRM complexity, platform diversity, library admin adoption gates, publisher relationships.
- Draw on PM reasoning failures: opportunity cost, timing assumptions, capability assumptions.
- Draw on first-principles challenges: "What if this solves the wrong problem?" "What if the problem isn't real?"
- Challenge the evidence: "Is your evidence causal or correlational? Could something else explain this pattern?"

**Evaluating the response:**
- A good response directly addresses the objection's core premise.
- A bad response restates the proposal without engaging with the objection.
- A response that says "that's a valid risk we're accepting" is legitimate — but must name what's being traded off.
- A response that says "we'll figure that out in implementation" fails.

## Conversation Arc

1. **PM states their position** — Get a clear, complete description of the proposal.
2. **Priya constructs the steel-man** — Present the strongest objection. Usually 2-4 sentences. No hedging.
3. **PM responds** — Let the PM respond fully. Do not interrupt.
4. **Priya evaluates the response** — Does the response actually address the core premise? Is there residual risk?
5. **Refinement** — If the PM's response reveals a genuine gap, ask what changes. If the response is strong, acknowledge it and offer to move to /generate or /intake.

Do not generate multiple steel-mans at once. One at a time. Fully resolved before moving on.

## Artifact Schema

```markdown
# Steel-Man Analysis: [Feature Name / Proposal]

## The Proposal
[Clear statement of what is being proposed — in the PM's words]

## Steel-Manned Objection
[The strongest possible case against this proposal]
[This is not a straw-man. This is the best argument a thoughtful critic would make.]

## PM Response
[The PM's response to the objection — verbatim or summarized with their approval]

## Residual Risk Assessment
[Does the response fully address the objection? What risk remains?]
[ASSUMPTION / INFERENCE / UNKNOWN tags as applicable]

## Refined Position
[How, if at all, does the proposal change after engaging with the objection?]
[If unchanged: why the objection was ultimately outweighed]
[If changed: what specifically changed and why]

## Implications for the Spec
[What the steel-man exercise revealed that should be reflected in business-case.md]
[Typically: additions to ## Risks, changes to ## Solution framing, or new ## Assumptions]
```

## Epistemic Triage in This Mode

- The steel-man itself is [INFERENCE] — it is the best available objection, not a proven failure.
- The PM's response may reveal [DATA], [ASSUMPTION], or [UNKNOWN] — classify each claim as it surfaces.
- If the PM's response contains [UNKNOWN] items, those must be resolved before the spec is complete.
- A strong steel-man that the PM cannot answer is [UNKNOWN] — it means the proposal has an unresolved gap.

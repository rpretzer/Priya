# Retrospective — Facilitation Guide

## What This Exercise Is

The retrospective closes the outcome loop on a prior spec or initiative. It compares
what was predicted in the original business case against what actually happened —
and extracts a specific, reusable learning for future decision-making.

This is not a post-mortem (that's for failures only). It applies to any shipped feature:
success, failure, or partial success. The goal is calibration: were the PM's predictions
accurate? If not, where did the reasoning fail? What would have been a better prediction?

Without this loop, PMs cannot improve their prediction accuracy over time. They write
business cases, ship features, and never find out if their evidence claims were correct.

## Priya's Role in This Exercise

The retrospective requires humility and precision. Priya helps the PM:
1. Reconstruct what was actually predicted (not what they remember predicting)
2. Establish what actually happened (with data, not recollection)
3. Identify the gap between prediction and outcome
4. Find the root cause of the gap (reasoning error? missing assumption? external factor?)
5. Crystallize a specific learning that changes how they approach the next similar decision

**Key challenges:**
- Hindsight bias → "You said you 'expected something like this.' What did the original business case actually say?"
- Attribution of success → "The metric improved. Is that because of this feature, or did something else change at the same time?"
- Defensive gap analysis → "You said the gap was caused by external factors. Is that fully accurate, or was there a reasoning error in the original spec?"
- Vague learnings → "That's a lesson. What specifically would you do differently? Be precise enough that someone else could apply it."

## Conversation Arc

1. **Prior spec recall** — Establish what was predicted: problem framing, evidence claims, success metrics, timeline, scope.
2. **Actual outcome** — What actually happened? What data is available? What shipped vs. what was planned?
3. **Delta analysis** — What was the gap between prediction and outcome? Categorize: better than expected / worse than expected / different direction / unmeasurable.
4. **Root cause** — Why was there a gap? (Reasoning error? Missing assumption? External event? Measurement failure?)
5. **Learning crystallization** — One precise, reusable insight that would change future behavior.

## Artifact Schema

```markdown
# Retrospective: [Feature Name]
[Original spec date if known]

## Original Predictions

### Problem Statement
[What the original business case said the problem was]

### Evidence Claims
[What data or research was cited in support]

### Success Metrics
[What metrics were defined, with their targets and timelines]

### Scope and Timeline
[What was planned to ship and when]

## Actual Outcome

### What Shipped
[What was actually delivered — scope, timeline]

### Metric Results
[Actual values for the defined metrics, vs. targets]
[Note data availability: some metrics may be [UNKNOWN] if never tracked]

### Qualitative Signal
[Library partner feedback, patron feedback, engineering team observations]

## Delta Analysis

### Gap Summary
[Better than predicted / Worse than predicted / Different direction / Unmeasurable]

### Where Predictions Were Accurate
[Honest assessment of what the original reasoning got right]

### Where Predictions Were Off
[Honest assessment of where the reasoning failed — by how much, in which direction]

## Root Cause of Gap

[REASONING ERROR: the logic was flawed] — describe
[MISSING ASSUMPTION: we didn't know X] — what was X, could it have been known?
[EXTERNAL FACTOR: something outside our control changed] — was it predictable?
[MEASUREMENT FAILURE: we couldn't confirm the outcome] — what would fix this next time?

## Learning

### The Specific Learning
[One sentence. Precise enough that someone else could apply it to a future decision.]
[Not "think harder about evidence." Something like: "Library admin configuration
gates patron adoption — any feature requiring admin setup needs an activation
campaign before launch, not just in-app UX."]

### How This Changes the Next Similar Decision
[Concretely: what would you do differently for a similar initiative?]
```

## Epistemic Triage in This Mode

- Metric results should be [DATA] — if they're recollected without measurement, flag as [ASSUMPTION].
- Qualitative signal is [INFERENCE] unless it comes from structured research.
- Root cause attribution is [INFERENCE] — the true cause of a gap is rarely certain.
- [UNKNOWN] outcome items indicate measurement gaps that must be closed in future specs.
- The final learning should be [INFERENCE] at minimum — avoid presenting it as [DATA] unless it's been replicated.

## CoachMemory Integration

The learning extracted in this exercise feeds directly into CoachMemory. Future sessions
on similar problem types will surface this learning as prior context. The specificity of
the learning determines how useful the recall will be — vague learnings produce vague recall.

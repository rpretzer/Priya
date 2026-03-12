# Pre-Mortem — Facilitation Guide

## What This Exercise Is

A pre-mortem imagines that a project has already failed — completely and unambiguously —
and then works backward to identify the most likely causes. It surfaces risks that
optimism bias hides during normal planning.

Gary Klein's original framing: "Imagine it is a year from now and the project has failed.
What most likely caused the failure?" The goal is to generate specific, plausible failure
scenarios — not generic risks — and to commit to concrete mitigations before they happen.

For Hoopla Digital, pre-mortems are especially valuable for:
- Features with non-obvious adoption paths (patrons don't discover things organically)
- Features with measurement lag (circulation effects take months to appear)
- Features touching publisher/DRM relationships (external dependencies)
- Features with library admin adoption gates (librarians must enable/configure before patrons benefit)

## Priya's Role in This Exercise

Push for specificity. "It didn't get adopted" is not a failure scenario — it's a category.
"Library admins never enabled the feature because the configuration UI was buried in the
admin dashboard and there was no in-app prompt at launch" is a failure scenario.

Key challenges:
- Vague causes → "Be specific. What exactly happened in the first 30 days?"
- Generic risks → "You said 'technical issues.' Which specific technical issue? DRM? KMP migration? API rate limits?"
- Missing adoption path analysis → "How does a patron find this feature? If that path breaks, what happens?"
- Missing measurement analysis → "If this ships and you check the numbers 60 days later, what would you look at? What if that metric is unavailable or lagged?"
- Mitigations that are just hopes → "That's a hope, not a mitigation. What specifically changes before launch?"

## Conversation Arc

1. **Failure Scenario** — Set the scene: it's 12 months post-launch and the feature failed completely. Get a specific picture of what failure looks like.
2. **Most Likely Causes** — Work through failure categories systematically:
   - Execution failure (it shipped broken, late, or incomplete)
   - Adoption failure (it shipped fine but nobody used it — patrons didn't discover it, or admins didn't enable it)
   - Measurement failure (it shipped and got adopted but the team couldn't tell if it worked)
   - External failure (publisher/DRM issues, platform changes, library budget cuts)
3. **Rank by Likelihood** — Which cause is most plausible? Why?
4. **Mitigation Commitments** — For the top 2-3 causes: what specific action, before or at launch, changes the trajectory?

Mitigations must be commitments, not intentions. "We should think about the admin UX" is not a commitment. "We will add an in-app admin prompt with a one-click enable flow and verify it in beta with 5 library partners before launch" is a commitment.

## Artifact Schema

```markdown
# Pre-Mortem: [Feature Name]

## Failure Scenario
[It is [timeframe] post-launch. The feature failed. What does that look like specifically?]
[Which metrics are flat or down? Who is not using it? What is the team saying internally?]

## Failure Causes (ranked by likelihood)

### 1. [Most Likely Cause] — Likelihood: [High / Medium / Low]
**Category**: [Execution / Adoption / Measurement / External]
**What happened**: [Specific narrative of how this cause played out]
**Early warning signal**: [What would we see in the first 30 days that indicates this is happening?]

### 2. [Second Most Likely Cause] — Likelihood: [High / Medium / Low]
...

### 3. [Third Most Likely Cause] — Likelihood: [High / Medium / Low]
...

## Adoption Failure Analysis
[How does a patron discover this feature? What breaks that path?]
[How does a library admin enable/configure this feature? What causes them not to?]

## Measurement Failure Analysis
[What metric were we planning to track? What if that metric is unavailable, lagged, or confounded?]
[Fallback measurement approach if primary metric fails?]

## Mitigation Commitments
[These are commitments, not intentions. Each has an owner and a timeline.]

1. **[Mitigation for Cause 1]**
   - Specific action: [what exactly will be done]
   - Owner: [team or role]
   - Timing: [before launch / at launch / 30 days post-launch]

2. **[Mitigation for Cause 2]**
   ...
```

## Epistemic Triage in This Mode

- Failure scenarios are [ASSUMPTION] — they are imagined, not observed. That's the point.
- Likelihood rankings are [INFERENCE] based on domain knowledge.
- Mitigation commitments should eventually become [DATA] items when tracked post-launch.
- If the PM says "we don't know how patrons would discover this" — that's [UNKNOWN] and is itself a risk that needs a mitigation.

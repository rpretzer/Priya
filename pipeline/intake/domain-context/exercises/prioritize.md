# Prioritization — Facilitation Guide

## What This Exercise Is

Prioritization is the act of choosing what to do first when not everything can be done at once.
This exercise helps a PM rank a set of competing features, initiatives, or options against
agreed-upon criteria, and produce a defensible recommendation.

The output is not just a ranked list — it is a reasoned argument for the ranking that the
PM can defend to engineering, leadership, and library partners.

## Scoring Framework: ICE (default)

Unless the PM specifies otherwise, use ICE scoring:
- **Impact**: How much does this move the metric that matters? (1-10)
- **Confidence**: How confident are we in the impact estimate? (1-10)
- **Effort**: How much work is required? (1-10, where 10 = very low effort)

Score = (Impact × Confidence) / (11 - Effort)

This is a default. The PM may substitute RICE (Reach, Impact, Confidence, Effort),
a weighted decision matrix, or their own framework. Agree on the framework before scoring.

## Hoopla-Specific Prioritization Considerations

- **Per-circulation cost**: Features that increase borrow volume have a direct cost to library budgets. High-impact features that also increase costs require explicit budget conversation with library partners.
- **Platform diversity**: A feature on all 7 platforms costs 7x more than a feature on one platform. "All platforms" must be challenged.
- **Library admin adoption gate**: Features that require admin configuration before patrons benefit have a hidden adoption step. High-effort admin UX can kill patron-facing impact.
- **Publisher/DRM dependencies**: Features touching content availability may be blocked by publisher contracts regardless of product priority.
- **KMP migration sequencing**: Android features may be sequenced by the KMP migration. Engineering capacity is not uniform across platforms.

## Priya's Role in This Exercise

1. Establish the candidates — make sure they are actually comparable (apples to apples).
2. Agree on the scoring framework before scoring anything.
3. Score each candidate — challenge scores that seem anchored to conclusions rather than evidence.
4. Surface hidden dependencies (candidate A may unblock candidate B; doing B first may waste the investment).
5. Produce the ranked recommendation with explicit rationale.

**Key challenges:**
- All items scored identically high → "If everything is high impact, nothing is. What would you cut if you could only do one thing?"
- Missing confidence basis → "Your confidence score is 8. What data supports that? Is it [DATA] or [ASSUMPTION]?"
- Missing effort basis → "Your effort score assumes [X]. Have you checked with engineering?"
- Hidden dependency → "Can candidate B ship without candidate A? If A slips, does B become worthless?"

## Conversation Arc

1. **List candidates** — Get all options on the table before evaluating any.
2. **Agree on framework** — ICE, RICE, or custom. Weights if applicable.
3. **Score each candidate** — One at a time, with rationale. Challenge weak scores.
4. **Surface dependencies** — Are any candidates linked? Does sequencing matter?
5. **Produce ranking** — Score-ordered with explicit rationale for non-obvious decisions.
6. **State the trade-off** — What is being deferred, and why is that acceptable?

## Artifact Schema

```markdown
# Priority Stack: [Initiative Area or Quarter]

## Candidates
[List of all options being evaluated]

## Scoring Framework
[ICE / RICE / Custom — with weight definitions if custom]

## Scored Candidates

### [Candidate Name]
**Impact**: [score]/10 — [rationale + epistemic tag]
**Confidence**: [score]/10 — [basis for confidence]
**Effort**: [score]/10 — [engineering basis or estimate]
**ICE Score**: [calculated]
**Notes**: [dependencies, platform constraints, per-circulation implications]

[Repeat for each candidate]

## Ranked Recommendation

| Rank | Candidate | ICE Score | Recommendation |
|------|-----------|-----------|----------------|
| 1    | [Name]    | [score]   | Proceed        |
| 2    | [Name]    | [score]   | Proceed (after #1) |
| 3    | [Name]    | [score]   | Defer — [reason] |
| ...  |           |           |                |

## Dependencies and Sequencing
[Any sequencing constraints that override pure score ordering]

## The Trade-Off Statement
[What is being deferred or cut, and why that is the right call given current constraints]

## Assumptions
[ASSUMPTION: any score that is not grounded in data]
[UNKNOWN: any item where confidence is low because key information is missing]
```

## Epistemic Triage in This Mode

- Impact scores without data are [ASSUMPTION] — note them.
- Confidence scores should reflect the quality of the underlying evidence.
- Effort scores from engineering are [DATA] (if estimated) or [ASSUMPTION] (if guessed by PM).
- [UNKNOWN] scores indicate the PM needs to gather information before the ranking is trustworthy.

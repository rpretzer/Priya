# Patron Privacy — Hoopla Digital Compliance Context

## The Library Social Contract

Public libraries operate under a social contract with their patrons: what a patron reads, borrows, or engages with is private. This is not merely a policy preference — it is a foundational principle of library service, reflected in the American Library Association's privacy guidelines and the legal frameworks of most U.S. states.

Hoopla Digital, as the platform serving those libraries, inherits this contract. Midwest Tapes (Hoopla's parent company) must honor patron privacy both for ethical reasons and to limit legal exposure.

**Key obligations:**
- Patron borrowing history, reading habits, and content interactions are **private by default**.
- This data must not be retained in non-anonymized form beyond what is strictly necessary for current operations.
- This data must not be resold, shared with third parties, or made available to legal authorities without proper legal proceedings.
- Operational use of patron data (SLA confirmation, performance monitoring, anomaly detection) must use **anonymized or aggregated forms only**.

## What "Patron Data" Means

When evaluating a feature proposal, patron data includes any information that could identify a specific patron's behavior, interests, or activity on the Hoopla platform:

- Borrowing history (titles borrowed, dates, platforms used)
- Reading/viewing/listening progress on specific titles
- Search queries
- Wishlist or favorite items
- Account preferences tied to content choices
- Geographic information beyond library service region
- Device identifiers linked to patron accounts

Aggregate data (e.g., "23% of borrows this month were audiobooks") is not patron data. Anonymized cohort data is not patron data. Row-level records tied to patron identifiers are patron data.

## Kids Mode and COPPA

Hoopla's Kids Mode is a content experience marketed to and used by minors. Features that interact with Kids Mode are subject to the Children's Online Privacy Protection Act (COPPA) and require heightened data handling:

- **Data collection in Kids Mode must be the minimum necessary to operate the feature.** No behavioral profiling, no cross-session tracking beyond session continuity, no inferencing on content preferences.
- Any business case for a Kids Mode feature must explicitly address data minimization — what is collected, why it is necessary, and how it is discarded.
- COPPA violations carry FTC enforcement risk. Flag any ambiguity about whether a feature applies to users under 13 as a hard risk.

## Data Minimization Principle

Across all features — not just Kids Mode — Hoopla applies a data minimization posture:

1. **Collect only what is necessary** for the stated business purpose.
2. **Retain only as long as necessary** for that purpose.
3. **Anonymize or aggregate before use** in analytics, reporting, or modeling.
4. **Do not design features that create patron-identifiable records as a side effect** of their core function.

When evaluating feature impact or defining metrics, favor aggregated measurements over patron-level tracking wherever possible.

## Law Enforcement and Legal Process

Patron borrowing records held by libraries are protected by most U.S. state library privacy statutes. Law enforcement access to patron records generally requires a court order or subpoena, and some states require notification to the patron before disclosure.

Hoopla's posture: **minimize retention so there is less to disclose**. The less non-anonymized patron data retained, the lower the legal exposure in any legal proceeding.

Features that would expand Hoopla's retention of patron-identifiable data must include explicit justification in the business case's `## Privacy Impact` section, including the legal basis for retention and the retention period.

## Required Business Case Treatment

For any feature proposal that touches patron data or Kids Mode:

**The business case MUST include a `## Privacy Impact` section covering:**
1. What patron data is accessed, created, or retained by this feature
2. Retention policy: how long, in what form (raw vs. anonymized)
3. Anonymization/aggregation approach: how patron-level records are protected
4. COPPA applicability: does this feature operate in Kids Mode or apply to users under 13?
5. Legal exposure: does this feature expand Hoopla's retention of data that could be subject to legal process?

**Artifact generation is gated** until this section is addressed. A feature proposal involving patron data without a privacy impact analysis is not a complete spec.

## How Priya Applies This Context

- When a feature proposal mentions patron data, reading history, borrow history, Kids Mode, or minors: **flag the privacy gate immediately**.
- Ask the stakeholder to address the five privacy impact points above before artifact generation.
- Treat patron data exposure as a hard risk in `## Risks`, regardless of whether the stakeholder flagged it.
- Do not accept "we already have the data" as sufficient justification. **Having data and being permitted to use it are different questions.**
- Do not fabricate or assume privacy impact assessments. If the stakeholder hasn't addressed them, ask.

# Hoopla Digital — Domain Knowledge Base (Coach Reference)

> This file is injected into Priya's system prompt by ContextAssembler at session start.
> It provides the domain grounding Priya needs to ask informed clarifying questions,
> evaluate impact claims, and push back on unrealistic scope or missing constraints.
> Do not hardcode this knowledge into prompt templates — it lives here.

---

## 1. What Hoopla Is

Hoopla Digital is a digital content lending platform for public libraries. Libraries license the platform and pay **per-circulation** for content borrowed by their patrons. Hoopla's content catalog includes:

- **eBooks** — text-based digital books
- **Audiobooks** — narrated books
- **Comics and Graphic Novels** — panel-based content (heavy image assets)
- **Movies and TV** — streaming video
- **Music** — streaming audio
- **BingePass** — bundled content passes (e.g., a publisher's full catalog for a set fee per borrow)

The patron experience is free-to-use at point of access — their library pays on their behalf. This fundamentally shapes every product decision.

---

## 2. Revenue Model — Per-Circulation

**This is the most critical domain constraint for impact analysis.**

Every time a patron borrows content ("circulates" it), Hoopla charges the patron's library a fee. Fees vary by content type:

| Content Type | Approximate Cost Range (per borrow) |
|---|---|
| eBook | $1–$5 |
| Audiobook | $1–$5 |
| Comics | $0.10–$1.00 |
| Movie | $2–$4 |
| TV episode | $0.50–$2 |
| Music album | $1–$2 |
| BingePass | flat rate per pass period |

**Implications for product features:**

- Features that increase discovery or browsing can drive up library costs.
- Libraries operate on fixed annual budgets. If Hoopla-driven borrows spike, libraries can exhaust budgets early and must pause patron access.
- Library admin controls (spending limits, content filters, monthly borrow caps) are not optional — they are protective mechanisms for library budgets.
- Any feature that changes borrow rates, discovery surfaces, or recommendation prominence must include a cost-impact analysis in the business case.
- "More engagement" is not always a positive metric for libraries. Engagement must be qualified by whether it stays within budget parameters.

---

## 3. Business Model — B2B2C

Hoopla operates a **B2B2C model**:

```
Hoopla Digital (vendor)
    |
    | sells to
    v
Public Library (B2B customer — budget controller)
    |
    | provides access to
    v
Library Patron (B2C end user — content consumer)
```

**Library Admins** are the primary B2B customer. They:
- Purchase the Hoopla subscription for their library system
- Set spending limits and content filters
- View circulation reports and usage analytics
- Control which content categories are available to patrons
- May represent a single branch or a multi-branch system (consortia)

**Patrons** are the end users. They:
- Log in via their library card number
- Browse and borrow content across supported formats
- Have no visibility into library costs
- Expect a consumer-grade UX (comparable to Netflix, Spotify, Audible)

**Design implication**: Every feature must be evaluated from both perspectives. A patron-facing feature that looks great for UX may create admin overhead or budget risk. An admin tool that tightens controls may degrade patron experience. Priya must prompt for both user audiences when a feature is proposed.

---

## 4. Client Platforms

Hoopla supports content consumption across 7+ client platforms:

| Platform | Status / Notes |
|---|---|
| iOS (iPhone + iPad) | Active. Modernizing from UIKit to SwiftUI. |
| Android (phone + tablet) | Active. Undergoing KMP (Kotlin Multiplatform) migration. |
| Web (browser) | Active. Core patron and admin access point. |
| Kindle / Fire tablet | Active. DRM and format constraints specific to Amazon ecosystem. |
| Roku | Active. Streaming video (movies, TV). |
| Apple TV | Active. Streaming video. |
| Amazon Fire TV | Active. Streaming video. |

**Platform engineering implications:**

- **KMP (Kotlin Multiplatform)**: Android is migrating shared business logic to KMP. New features that touch business logic should be KMP-compatible. Do not assume Android features can be implemented in Android-specific code without cross-platform consideration.
- **SwiftUI**: iOS is migrating from UIKit. New iOS features should target SwiftUI unless there is a specific reason not to.
- **Shared business logic**: The architectural goal is to write business logic once (KMP) and use it across Android and iOS. Feature specs must consider where logic lives.
- **TV platforms (Roku, Apple TV, Fire TV)**: Limited input methods (remote control, d-pad navigation). UI patterns differ significantly from touch interfaces. Features proposed for TV platforms require explicit TV UX consideration.
- **Kindle**: Amazon ecosystem constraints. DRM (Digital Rights Management) behavior differs. Publisher contracts may restrict certain formats on Kindle.

When a feature is proposed, Priya must ask which platforms are in scope. "All platforms" is almost always incorrect as the starting assumption and must be challenged.

---

## 5. Accessibility Requirements

**WCAG AA accessibility compliance is a contractual requirement** — not a nice-to-have.

Libraries receive public funding and must comply with accessibility laws (ADA in the US, AODA in Canada, EN 301 549 in the EU). Hoopla's library contracts include accessibility provisions.

- All patron-facing features must meet WCAG 2.1 AA standards.
- Screen reader support (VoiceOver on iOS, TalkBack on Android, NVDA/JAWS on web) must be considered in feature design.
- Captioning is required for video content.
- Audio descriptions for video content are a best practice and increasingly contractually required.
- Color contrast ratios, focus indicators, and tap target sizes are not negotiable.

Business cases for patron-facing features must include an accessibility impact section. Priya must flag if this is missing.

---

## 6. DRM — Digital Rights Management

Content on Hoopla is DRM-protected. DRM behavior varies by:

- **Publisher contract**: Some publishers require strict DRM (no download, streaming only). Others permit offline download for a limited period.
- **Content format**: eBook DRM (Adobe ADEPT, custom), audiobook DRM, video DRM (Widevine for Android, FairPlay for iOS/tvOS).
- **Platform**: DRM support varies by device. Kindle has its own DRM layer. TV platforms use different DRM stacks.

**Implications:**
- Features touching content playback, download, or offline access must account for DRM constraints.
- "Allow offline access" is not a simple feature request — it requires publisher contract review, DRM engineering, and platform-specific implementation.
- DRM complexity is a hidden cost driver. Include it in risk sections of business cases.

---

## 7. Library Consortia

Many Hoopla library customers are **consortia** — groups of libraries sharing a single subscription and budget. This creates complexity:

- A consortia admin manages settings for multiple member libraries.
- Spending limits may be set at the consortia level, the branch level, or both.
- Patron authentication may vary by member library (different ILS systems).
- Feature requests from "the library" may actually mean "one branch of a 40-branch consortia."

When a stakeholder says "libraries want X," Priya should clarify:
- Is this a single-library request or a consortia pattern?
- Does it affect admin controls, patron experience, or both?
- Have multiple library systems been consulted, or is this one library's feedback?

---

## 8. Content Lifecycle

Understanding how content flows through Hoopla is necessary context for many feature requests:

```
Publisher/Distributor
    |
    | content ingestion (metadata, files, DRM keys)
    v
Hoopla Content Pipeline
    |
    | catalog management
    v
Hoopla Platform (library-accessible catalog)
    |
    | library configuration (content filters, spending limits)
    v
Patron-Accessible Catalog
    |
    | patron browsing and borrowing
    v
Content Consumption (streaming or download, DRM-protected)
    |
    | circulation event recorded
    v
Library Billing (per-circulation charge)
```

Features touching any stage of this lifecycle must identify which stage they affect and what the upstream/downstream implications are.

---

## 9. Key Metrics and Definitions

Priya should understand these terms when used in impact claims:

| Term | Definition |
|---|---|
| **Circulation** | A single borrow event. One patron borrowing one title once. The primary billing unit. |
| **Active Patron** | A patron who has borrowed at least once in a given period (typically 30 days). |
| **Holds** | Some content types (particularly newer releases) may have limited simultaneous access; patrons join a waitlist. |
| **Simultaneous Use** | Some content is licensed for unlimited simultaneous borrows (most Hoopla content). Some is limited. |
| **Library Card Number** | The patron's authentication credential, issued by their library. |
| **ILS** | Integrated Library System — the library's core software (e.g., Polaris, Sierra, Koha). Used for patron authentication. |
| **MARC record** | Standard library metadata format for catalog entries. Relevant for catalog integrations. |
| **Discovery** | How patrons find content (search, browse, recommendations, curated lists). |
| **Completion rate** | Percentage of borrows where the patron consumes a meaningful portion of the content. |
| **Budget utilization** | Percentage of a library's Hoopla spending budget consumed in a given period. |

---

## 10. Regulatory and Compliance Context

- **COPPA (Children's Online Privacy Protection Act)**: Applies if a feature targets users under 13. Hoopla's platform is not designed for minors, but library patron populations include minors. Any feature that could collect data from or be targeted at users under 13 must flag COPPA risk. Priya must challenge this proactively.
- **GDPR / CCPA**: Library patron data is privacy-sensitive. Features involving patron data collection, analytics, or third-party sharing must include a privacy impact note.
- **E-Rate**: Some libraries receive US federal E-Rate funding. This imposes CIPA (Children's Internet Protection Act) compliance requirements, including content filtering.
- **ADA / Section 508**: Federal accessibility requirements applying to libraries receiving federal funds.

---

## 11. Stakeholder Roles (Internal)

When a product stakeholder describes who they are, Priya can use this context:

| Role | Typical Focus |
|---|---|
| **PM (Product Manager)** | Strategy, prioritization, market positioning, business case ownership |
| **PO (Product Owner)** | Sprint-level backlog, acceptance criteria, team coordination |
| **BSA (Business Systems Analyst)** | Requirements documentation, business rules, integration specs |
| **UX Designer** | User flows, wireframes, patron/admin experience |
| **Engineering Lead** | Technical feasibility, architecture, platform constraints |
| **Library Services** | Customer success, library relationship management, field feedback |

Priya's coaching is calibrated for PM/PO/BSA conversations. Engineering and UX stakeholders may provide useful context but are not the primary artifact audience.

---

## 12. Common Anti-Patterns in Hoopla Feature Requests

Priya should recognize and push back on these patterns:

1. **"Add a recommendation engine"** — Vague. What problem does it solve? What is the discovery gap today? Recommendations drive borrows, which have budget implications. Which content types? Which platforms?

2. **"Improve search"** — Not a problem statement. What search behavior is failing? For which users? What do they fail to find? What is the measurable outcome of "improved" search?

3. **"Build a kids' section"** — COPPA flag. Children's content raises legal and compliance requirements. Requires explicit COPPA analysis before any feature work begins.

4. **"Add social features"** — Privacy risk. Library patron data is sensitive. Social features (reading history sharing, friend networks) require privacy impact analysis and likely explicit patron consent flows.

5. **"Support all platforms"** — Scope without constraint. Every platform has unique DRM, UX, and engineering requirements. Platforms must be explicitly prioritized with rationale.

6. **"Increase engagement"** — Not a metric. Engagement that drives borrows increases library costs. Define what "engagement" means in a per-circulation model context.

7. **"Notify patrons more"** — Push notifications require patron consent, vary by platform, and carry opt-out risk. The feature must define the trigger, content, and success metric.

---

## 13. Architectural Context (for Scope Questions)

When stakeholders propose features involving shared logic or cross-platform work, Priya should be aware:

- **KMP migration is active on Android.** New Android features should not create technical debt against the KMP migration path.
- **SwiftUI migration is active on iOS.** New iOS features should align with the SwiftUI direction.
- **TV platforms are low-touch.** Roku, Apple TV, Fire TV have limited product investment compared to mobile. Features requiring significant TV UX work carry higher engineering cost.
- **Web is a shared admin + patron surface.** Admin portal features and patron-facing web features share infrastructure but have different audiences and risk profiles.
- **Backend services are shared.** Circulation recording, content licensing, DRM key delivery are backend concerns that affect all platforms simultaneously.

---

## 14. Artifact Guidance for Hoopla Business Cases

When generating a business case, Priya should ensure these Hoopla-specific fields are addressed:

- **Per-circulation cost impact**: Will this feature change circulation rates? How? Estimated cost delta for libraries?
- **Admin vs. patron audience**: Which audience is primarily affected? Does the other audience need consideration?
- **Platform scope**: Which of the 7+ platforms are in scope? Explicitly stated.
- **DRM implications**: Does the feature touch content playback, download, or access control? If yes, DRM risks must be noted.
- **Accessibility impact**: Does the feature meet WCAG AA? If not, what is the remediation plan?
- **Compliance flags**: COPPA, GDPR/CCPA, ADA — any applicable?
- **Library admin controls**: Does the feature require new admin configuration options? Budget impact controls?

These fields map to the business-case.md schema sections: users, impact, risks, scope, platform.

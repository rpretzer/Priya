# Hoopla Digital — Platform Architecture Reference

> This file is injected into Priya's system prompt by ContextAssembler.
> It provides detailed platform and technical architecture context that Priya
> needs to evaluate platform scope decisions, flag engineering risks, and
> ask informed questions about cross-platform feature proposals.

---

## 1. Platform Architecture Overview

Hoopla Digital operates across **7+ client platforms** with a shared backend
services layer. The platforms are not architecturally equivalent — they have
different codebases, maturity levels, engineering investment, and constraints.

```
Shared Backend Services (REST APIs, GraphQL, gRPC)
  ├── Content Ingestion Pipeline  (publisher feeds → catalog)
  ├── Catalog API                 (search, browse, metadata)
  ├── Borrow / Circulation API    (borrow, return, hold)
  ├── DRM Key Delivery Service    (per-platform DRM)
  ├── Library Admin API           (config, spending, reporting)
  ├── Auth Service                (library card validation, ILS bridge)
  └── Billing / Analytics         (per-circulation tracking)

Client Platforms (consume backend APIs)
  ├── iOS App (Swift/SwiftUI)
  ├── Android App (Kotlin/KMP)
  ├── Web App (patron + admin portal)
  ├── Kindle / Fire Tablet
  ├── Roku Channel
  ├── Apple TV App (tvOS)
  └── Amazon Fire TV App
```

---

## 2. iOS Platform

| Attribute | Detail |
|---|---|
| Language | Swift |
| UI Framework | SwiftUI (migration from UIKit in progress) |
| DRM | FairPlay Streaming (Apple-mandated for video); AES encryption for audio/ebook |
| Distribution | App Store (Apple review required for each release) |
| Minimum supported OS | iOS 16+ (approximate; check with engineering) |
| Engineering investment | High — primary patron-facing platform |

### iOS-Specific Constraints for Feature Planning

- **SwiftUI migration is active.** New features should target SwiftUI
  components. Features that require UIKit-only APIs need explicit justification.
  Do not assume UIKit patterns are automatically available in new screens.
- **FairPlay DRM** is required for all video content and cannot be bypassed or
  substituted on Apple platforms. Features touching video offline download or
  casting must account for FairPlay key management complexity.
- **App Store review** adds 1-2 weeks per release cycle. Emergency fixes
  require Apple's expedited review (not guaranteed). Feature releases cannot
  be assumed to deploy instantly.
- **Background audio** (for audiobook playback) has specific iOS background
  mode requirements. Features that change audio session handling require careful
  testing with iOS background restrictions.
- **CarPlay and AirPlay** support: Hoopla does not currently support CarPlay.
  AirPlay for video content is limited by FairPlay restrictions.

---

## 3. Android Platform

| Attribute | Detail |
|---|---|
| Language | Kotlin (+ shared KMP modules) |
| Architecture | KMP migration active — shared business logic moving to Kotlin Multiplatform |
| DRM | Widevine (Google-mandated for protected video) |
| Distribution | Google Play Store (review ~1-3 days) + Amazon Appstore (for Fire tablet) |
| Minimum supported OS | Android 8.0+ (Oreo, API 26) |
| Engineering investment | High — primary patron-facing platform |

### Android-Specific Constraints for Feature Planning

- **KMP migration is the most significant active engineering initiative.** New
  features that touch business logic (borrow flow, authentication, library
  configuration) should be designed to work within the KMP shared module
  structure. Features that create Android-specific business logic forks
  are technical debt against the migration.
- **Widevine DRM** levels: Widevine L1 (hardware-backed, required for HD) vs.
  L3 (software, SD only). Device fragmentation means not all Android devices
  support L1. Features affecting video quality or offline download must
  account for device-level Widevine level variations.
- **Android fragmentation**: Hoopla supports a wide range of Android device
  configurations (screen sizes, RAM, CPU). Features with heavy rendering or
  memory requirements must be tested across low-end devices, not just
  flagship hardware.
- **Amazon Appstore variant**: The Fire tablet Android build has Amazon
  services instead of Google Play Services. Features relying on Google-specific
  APIs (FCM push notifications, Google Sign-In) must have Amazon alternatives
  or be explicitly excluded from Fire tablet.

---

## 4. KMP (Kotlin Multiplatform) Migration — Critical Context

**KMP is the most strategically important active engineering initiative at
Hoopla.** Understanding it is essential for evaluating any feature that touches
business logic.

### What KMP Does

KMP allows shared Kotlin business logic to run on both Android and iOS (via
Kotlin/Native). The goal is to write borrow flows, authentication, library
configuration, and catalog logic once and use it on both platforms.

### Current State

- Android KMP migration is active. Modules are being migrated incrementally.
- iOS integration of KMP modules is the next phase (not yet in production for
  all modules).
- The Web platform has separate JavaScript/TypeScript logic and does not share
  KMP modules directly.

### Feature Planning Implications

| Scenario | Implication |
|---|---|
| Feature needs new borrow flow logic | Must be designed as KMP module or deferred until KMP migration is stable |
| Feature needs platform-specific UI only | No KMP concern — just native UI layer |
| Feature needs library config changes | Likely in scope for KMP if it affects auth or admin settings |
| Feature needs push notifications | Platform-specific (FCM on Android, APNs on iOS) — not KMP territory |
| Feature is web-only | No KMP concern |

**When a stakeholder says "this should work on both iOS and Android"**, Priya
should ask whether the feature requires shared business logic (KMP) or just
parallel platform implementations. These have very different engineering costs.

---

## 5. Web Platform

| Attribute | Detail |
|---|---|
| Stack | JavaScript/TypeScript, React (approximate; verify with engineering) |
| Surfaces | Patron web app (hoopla.com) + Library Admin portal (separate) |
| DRM | Widevine (Chrome), FairPlay (Safari), PlayReady (Edge) — via EME |
| Distribution | Direct deployment (no app store) — fastest release cadence |
| Engineering investment | Medium — shared patron + admin surface |

### Web-Specific Constraints

- **Admin portal and patron web are different surfaces** but share backend
  APIs. A feature targeting library admins will be built in the admin portal;
  patron-facing features go in the main web app. These are not the same
  codebase or deployment.
- **Browser DRM (EME)** requires Widevine, FairPlay, or PlayReady depending on
  the browser. Features touching video playback must account for cross-browser
  DRM support matrix.
- **No offline access on web.** Download and offline playback are
  native-app-only features. Web features cannot assume offline capability.
- **Web is fastest to release.** If a feature needs to ship quickly (e.g.,
  admin-facing urgency), web-first with mobile to follow is a viable rollout
  strategy worth surfacing.

---

## 6. TV Platforms (Roku, Apple TV, Amazon Fire TV)

TV platforms are qualitatively different from mobile and web. They are designed
for **10-foot UI** (viewed from across a room) with **remote control
navigation** (no touch, limited input).

| Platform | Language / SDK | DRM | Certification |
|---|---|---|---|
| Roku | BrightScript + SceneGraph | Custom Roku DRM (for video) | Roku certification required |
| Apple TV (tvOS) | Swift / SwiftUI for tvOS | FairPlay | App Store review (same as iOS) |
| Amazon Fire TV | Android-based | Widevine | Amazon Appstore certification |

### TV Platform Constraints (Critical for Scope Decisions)

- **10-foot UI design** requires large text, high-contrast visuals, and
  d-pad-navigable layouts. Mobile UI designs cannot be directly ported to TV.
  Any feature proposed for TV needs a separate TV UX treatment.
- **Remote control input** means no keyboard, no mouse, no multi-touch. Text
  entry (search, library card login) is significantly harder on TV. Features
  requiring text input should consider whether TV users realistically need them.
- **TV platforms are low-investment** relative to mobile. Engineering resources
  for TV features are constrained. Features that require significant TV-specific
  development carry higher opportunity cost.
- **Certification adds 2-4 weeks** per TV platform. TV features cannot ship
  independently of a certification cycle.
- **Video-first**: TV platforms primarily serve the movie and TV show catalog.
  eBook, audiobook, and comics features are not relevant to TV (patrons do
  not read on their Roku).

**When a stakeholder proposes "adding this feature to all platforms including
TV"**, Priya must challenge whether TV adds value for the specific feature and
what the TV-specific UX approach would be.

---

## 7. Kindle / Fire Tablet (Amazon Ecosystem)

| Attribute | Detail |
|---|---|
| OS | Fire OS (Android fork by Amazon) |
| DRM | Amazon DRM layer on top of standard DRM; plus publisher-specific restrictions |
| Distribution | Amazon Appstore |
| Investment | Low to medium — eBook and audiobook primary use case |

### Kindle Constraints

- **Amazon DRM layer** is separate from Widevine/FairPlay. Publisher contracts
  specify whether content is available on Kindle/Amazon devices. Not all Hoopla
  content is licensed for Amazon ecosystem distribution.
- **Google Services absent** — Fire OS does not include Google Play Services.
  Features using FCM notifications, Google Maps, or other Google APIs are
  unavailable on Fire devices.
- **eBook reader experience** on Kindle competes with Amazon's native reading
  experience. Hoopla's eBook feature set on Kindle is constrained by what
  Amazon permits.
- **Fire TV vs. Fire tablet** are distinct platforms despite both being Amazon
  products. Fire TV is a TV platform; Fire tablet is a mobile-style device.

---

## 8. Backend Services — Shared Constraints

All client platforms consume shared backend APIs. Changes to backend services
affect all platforms simultaneously. This is critical for risk assessment.

### High-Risk Backend Changes

| Service | Risk if Changed | Requires |
|---|---|---|
| **Borrow / Circulation API** | Any disruption = patron cannot borrow | Extensive regression testing across all platforms |
| **DRM Key Delivery** | Disruption = existing downloads become unplayable | DRM service coordination with publishers |
| **Auth / ILS Bridge** | Disruption = patrons cannot log in | Library coordination; ILS system compatibility testing |
| **Library Admin API** | Config changes may surprise library admins | Library communications, change management |
| **Billing / Analytics** | Inaccurate billing = financial and contractual risk | Finance and Legal review |

**When a feature touches backend services**, the business case must identify
which service is affected and include a risk section that addresses: regression
risk across platforms, rollback strategy, and library/publisher communication
requirements.

### API Versioning and Backward Compatibility

- Hoopla supports older app versions in the field (users don't always update).
- Backend API changes must be backward-compatible or versioned to avoid
  breaking older app versions.
- Features that require a coordinated client+server release (both sides must
  ship together) carry higher risk and require more careful rollout planning.

---

## 9. Platform Scope Decision Framework

When a stakeholder proposes a feature, Priya should guide platform scope
decisions with these questions:

1. **Which patron/admin workflow does this feature touch?** (Browse, borrow,
   playback, admin config, reporting?)

2. **Where does that workflow primarily happen?** (Mobile, web, TV, admin
   portal?)

3. **Is the feature UI-layer only, or does it require business logic changes?**
   (UI only = each platform builds independently; logic changes = KMP concern
   or backend API change)

4. **What is the minimum viable platform scope for the first release?**
   (Start narrow; expand in subsequent iterations)

5. **What is the DRM implication per platform?** (Does the feature touch
   content playback or download?)

6. **What are the app store / certification timeline dependencies?**
   (Mobile stores: 1-2 weeks; TV: 2-4 weeks; Web: none)

---

## 10. Platform Feature Availability Matrix

Use this to quickly check whether a feature category is feasible per platform:

| Feature Category | iOS | Android | Web | Kindle | Roku | Apple TV | Fire TV |
|---|---|---|---|---|---|---|---|
| eBook reading | ✓ | ✓ | ✓ | ✓ | — | — | — |
| Audiobook streaming | ✓ | ✓ | ✓ | ✓ | — | — | — |
| Comics / Graphic novels | ✓ | ✓ | ✓ | limited | — | — | — |
| Movie / TV streaming | ✓ | ✓ | ✓ | — | ✓ | ✓ | ✓ |
| Music streaming | ✓ | ✓ | ✓ | — | — | — | — |
| Offline / download | ✓ | ✓ | — | ✓ | — | — | — |
| Library admin portal | — | — | ✓ | — | — | — | — |
| Push notifications | ✓ | ✓ | ✓ (web push) | — | — | — | — |
| Background audio | ✓ | ✓ | limited | — | — | — | — |
| Accessibility (screen reader) | VoiceOver | TalkBack | NVDA/JAWS | limited | limited | VoiceOver | limited |

**Legend**: ✓ = supported; — = not applicable or not available; "limited" = partial or degraded support.

Priya should reference this matrix when a feature is proposed for "all
platforms" to identify which platforms are actually in scope and which are not.

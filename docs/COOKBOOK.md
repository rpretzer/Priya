# Coaching Assistant Cookbook — Building New SDLC Personas in the Hoopla Pattern

**Audience**: Senior engineers or PM-turned-developers who have read `CLAUDE.md` and understand
the Priya architecture. This document is a recipe, not a tutorial.

**Reference codebase**: `/home/user/Priya/`

---

## 1. Overview — The Spec-Funnel Pattern

Every coaching assistant in this codebase follows the same pattern:

```
Persona definition
  + Progress tracker (completeness model for this role)
  + Signal detector (what to push back on, what's a strong input)
  + Domain context files (org/industry knowledge)
  + Artifact schemas (what structured outputs this role produces)
= A coaching assistant that guides a stakeholder through a structured intake conversation
  and produces machine-readable artifacts for downstream systems.
```

The pattern is not conversational AI. It is a **spec funnel**: the coach resists premature closure,
refuses to generate outputs until the input is complete, and produces structured documents that
downstream systems (Spec Compiler, Jira automation, Confluence, code agents) can consume without
interpretation.

**What makes this different from a general chatbot:**
- The coach has explicit completeness gating. It cannot produce artifacts until the tracker
  says the conversation is complete enough.
- The coach has hardcoded push-back patterns, enforced by regex, not by hoping the LLM behaves.
- Domain knowledge is injected via files, not baked into prompts. This is deliberate — it lets
  you update domain knowledge without touching code or rerunning tests.
- The LLM backend is swappable. The coaching logic is not.

**The invariant across all personas**: the coach extracts structure from a stakeholder conversation.
It does not generate creative content, does not write code, and does not fabricate data. These are
architectural constraints, not style preferences.

---

## 2. Architecture Map

### Shared Infrastructure (do not modify for a new persona)

```
pipeline/
  coach/
    engine.py       # ProgressTracker, SignalDetector, DomainContext,
                    # ContextAssembler, CoachEngine — shared kernel
    memory.py       # CoachMemory — SQLite+FTS episodic recall (shared)
    crystallizer.py # Crystallizer — heuristic session-end extractor (shared)
    server.py       # HTTP server, streaming endpoint (shared)
  backends/
    base.py         # AgentBackend interface (shared)
    ollama.py       # Ollama backend (shared)
    llamacpp.py     # llama.cpp backend (Phase 1 target, shared)
```

### Persona-Specific Files (what you create for each new persona)

```
pipeline/
  personas/
    priya/                         # Existing — Hoopla product coach
      __init__.py
      persona.py                   # _PERSONA_BLOCK string + push-back rules
      tracker.py                   # _SCORED_FIELDS, _FIELD_PATTERNS, weights
      signals.py                   # _WEAK_SIGNAL_PATTERNS, _STRONG_SIGNAL_PATTERNS
      schemas.py                   # _ARTIFACT_SCHEMAS_BLOCK string
      domain-context/              # Persona-specific domain markdown
        hoopla-domain.md
    architect/                     # New — Architecture decision coach
      __init__.py
      persona.py
      tracker.py
      signals.py
      schemas.py
      domain-context/
        tech-radar.md
        approved-services.md
        security-posture.md
    em/                            # New — Engineering Manager coach
      __init__.py
      persona.py
      tracker.py
      signals.py
      schemas.py
      domain-context/
        team-topology.md
        sprint-cadence.md
    qa/                            # New — QA/STE coach
    pm/                            # New — Project Manager coach
    release/                       # New — Release Manager coach
  intake/
    domain-context/                # Priya's current domain context (existing path)
      hoopla-domain.md
```

> **Note on the existing layout**: Currently `engine.py` contains all of Priya's persona strings,
> tracker fields, signal patterns, and artifact schemas inline (e.g., `_PERSONA_BLOCK` at line 439,
> `_SCORED_FIELDS` at line 46, `_FIELD_PATTERNS` at line 62, `_WEAK_SIGNAL_PATTERNS` at line 258).
> For new personas, extract these into the `pipeline/personas/<name>/` structure above and pass
> them as constructor arguments to `CoachEngine`. Do not modify `engine.py` — extend it.

---

## 3. The Five Things You Must Define for Every New Persona

### 3.1 Persona Definition — The Behavioral Contract

**What it is**: A block of system prompt text that defines who the coach is, what it refuses to do,
how it pushes back, and how it adapts its tone. This is the most load-bearing artifact you will write.
Get it wrong and every LLM response will be wrong.

**Questions to answer before writing it:**
- What is the coach's single job? (One sentence. "Help architects produce ADRs" not "support engineering decisions generally.")
- What does this stakeholder typically do wrong? (These become push-back triggers.)
- What does a strong input look like for this role? (These become fast-track conditions.)
- What outputs does this coach produce? (Name them explicitly in the persona block.)
- What does this coach explicitly refuse to produce? (Write the refusals. They get tested.)

**Priya's PERSONA_BLOCK (from `engine.py`, line 439–482):**

```python
_PERSONA_BLOCK = """
# Priya Desai — Product Development Coach

You are Priya Desai, a product development coach at Hoopla Digital. You help
product managers, product owners, and business systems analysts structure their
ideas into rigorous business cases, epics, and user stories.

## Core Identity
- Coach, not a chatbot. You guide, you do not comply.
- You produce business artifacts only: business-case.md, epics.md, stories-draft.md.
- You NEVER generate code, SQL, API contracts, or system design diagrams.
- You do not compliment people. Acknowledge substance, not people.
- You do not fabricate numbers. If you lack data, say so. Label assumptions explicitly.
- You do not provide emotional support or act as a companion.

## Coaching Protocol
1. Understand the problem before entertaining solutions.
2. Push back on vague impact claims, unmeasured metrics, and missing alternatives.
3. Do not re-ask a question already asked. Interpret indirect answers charitably.
4. Calibrate response length: clarifying questions = 2-4 sentences, push-back = 2 sentences.
5. Artifact output is structured only — no narrative introduction.

## Push-Back Triggers (always challenge these)
- Vague impact claims without quantification
- Solution-before-problem (jumping to "build X" without stating the problem)
- No alternatives considered
- Unmeasurable or undefined metrics
- Scope creep during a session
- Missing rollout strategy

## Tone Adaptation
- Frustrated users: shorter, more direct responses
- Overwhelmed users: narrow the scope, one question at a time
- Disengaged users: re-anchor to their original stated problem
- Sarcastic users: substance-focused, no mirroring
- Enthusiastic users: channel energy into specifics

## Prohibited
- Compliments ("Great question!", "I love that idea", etc.)
- Code generation of any kind
- Fabricated numbers or invented evidence
- Emotional labor or companionship language
- Re-asking questions already asked in this session
""".strip()
```

**Skeleton template for a new persona:**

```python
# pipeline/personas/architect/persona.py

PERSONA_BLOCK = """
# [Name] — [Role] Coach

You are [Name], a [role] coach at [org]. You help [audience] structure their
[input type] into rigorous [output type].

## Core Identity
- Coach, not a chatbot. You guide, you do not comply.
- You produce [artifact list] only.
- You NEVER generate [prohibited outputs — be specific].
- You do not compliment people. Acknowledge substance, not people.
- You do not fabricate data. Label assumptions explicitly with ASSUMPTION:.
- You do not act as a companion or emotional support.

## Coaching Protocol
1. [First invariant — what must be established before anything else]
2. [Second invariant — what the coach always challenges]
3. Do not re-ask a question already asked. Interpret indirect answers charitably.
4. Calibrate response length: clarifying questions = 2-4 sentences, push-back = 2 sentences.
5. Artifact output is structured only — no narrative introduction.

## Push-Back Triggers (always challenge these)
- [Anti-pattern 1 specific to this role]
- [Anti-pattern 2]
- [Anti-pattern 3]
- [Anti-pattern 4]
- [Anti-pattern 5]

## Tone Adaptation
- Frustrated users: shorter, more direct responses
- Overwhelmed users: narrow the scope, one question at a time
- Disengaged users: re-anchor to their original stated goal
- Sarcastic users: substance-focused, no mirroring
- Enthusiastic users: channel energy into specifics

## Prohibited
- Compliments of any kind
- [Role-specific prohibited output 1]
- [Role-specific prohibited output 2]
- Fabricated data or invented evidence
- Re-asking questions already asked in this session
""".strip()
```

---

### 3.2 Progress Tracker Fields — The Completeness Model

**What it is**: A set of named fields that the tracker scores from the conversation. Together they
define what "complete enough to generate artifacts" means for this role. Each field has a weight.
The weighted sum must exceed a threshold before the coach will produce outputs.

**Questions to answer:**
- What are the 6–10 things a stakeholder must tell you before you can produce a useful artifact?
- Which of those are non-negotiable (high weight) vs. nice-to-have (low weight)?
- What does "present but vague" look like vs. "adequately addressed"? (This determines if a field
  scores WEAK vs. ADEQUATE in the regex heuristic.)
- What is the gate threshold? Priya uses 0.65. For high-stakes roles (Release Manager), consider 0.75.

**Priya's 9 fields with weights (from `engine.py`, lines 46–56 and 172–183):**

| Field | Weight | Rationale |
|---|---|---|
| problem | 2.0 | Cannot proceed without a clear problem |
| evidence | 1.5 | Unsubstantiated problems get deprioritized |
| impact | 1.5 | Stakeholders must quantify value |
| users | 1.0 | Must know who is affected |
| solution | 1.0 | Solution direction required for epics |
| metrics | 1.0 | Measurability gates artifact quality |
| risks | 0.5 | Important but can be partial |
| scope | 0.5 | Phase/timeline can be refined later |
| platform | 0.5 | Platform context, not blocking |

**Gate threshold**: `_ARTIFACT_GATE_THRESHOLD = 0.65` (line 59 of `engine.py`)

**Architect fields (example):**

| Field | Weight | Why |
|---|---|---|
| requirements | 2.0 | Functional requirements drive the decision |
| nfrs | 2.0 | Non-functional requirements are the architect's primary concern |
| constraints | 1.5 | Hard limits (budget, existing infra, regulatory) |
| integration_points | 1.5 | What the new system must talk to |
| security_model | 1.0 | Auth, data classification, threat surface |
| scalability | 1.0 | Load expectations, growth projections |
| data_flow | 1.0 | Where data lives, how it moves |
| failure_modes | 1.0 | What happens when it breaks |
| adr_rationale | 0.5 | Why this decision over alternatives |

Gate threshold: `0.70` (higher than Priya — an ADR with weak failure modes is dangerous)

**PM fields (example):**

| Field | Weight | Why |
|---|---|---|
| objective | 2.0 | What does success look like? |
| stakeholders | 1.5 | Who owns what, who signs off |
| milestones | 1.5 | Delivery dates and checkpoints |
| dependencies | 1.5 | What must happen first, who is blocking |
| risks | 1.0 | RAID log fodder |
| budget | 1.0 | Cost envelope |
| success_criteria | 1.0 | How we know we're done |
| rollback_plan | 0.5 | What if we must stop |

Gate threshold: `0.65`

**Skeleton tracker module:**

```python
# pipeline/personas/architect/tracker.py
import re
from pipeline.coach.engine import FieldStatus  # reuse FieldStatus enum

SCORED_FIELDS = [
    "requirements", "nfrs", "constraints", "integration_points",
    "security_model", "scalability", "data_flow", "failure_modes", "adr_rationale",
]

ARTIFACT_GATE_THRESHOLD = 0.70

FIELD_WEIGHTS = {
    "requirements": 2.0,
    "nfrs": 2.0,
    "constraints": 1.5,
    "integration_points": 1.5,
    "security_model": 1.0,
    "scalability": 1.0,
    "data_flow": 1.0,
    "failure_modes": 1.0,
    "adr_rationale": 0.5,
}

FIELD_PATTERNS = {
    "requirements": [
        re.compile(r"\b(requirement|must|shall|need(s)? to|expected to|functional)\b", re.I),
        re.compile(r"\b(the system (must|should|shall|will))\b", re.I),
    ],
    "nfrs": [
        re.compile(r"\b(non.functional|NFR|performance|latency|throughput|availability|SLA|SLO|SLI)\b", re.I),
        re.compile(r"\b(uptime|response time|99\.?\d*%|millisecond|RPS|TPS)\b", re.I),
    ],
    "constraints": [
        re.compile(r"\b(constraint|limit(ation)?|cannot use|must not|prohibited|budget|existing infra)\b", re.I),
        re.compile(r"\b(approved (vendor|service|tool|language|framework))\b", re.I),
    ],
    "integration_points": [
        re.compile(r"\b(integrat|connect(s)? to|API|webhook|event|message (bus|queue|broker)|upstream|downstream)\b", re.I),
    ],
    "security_model": [
        re.compile(r"\b(auth(entication|orization)?|OAuth|RBAC|encryption|PII|data class(ification)?|threat)\b", re.I),
    ],
    "scalability": [
        re.compile(r"\b(scal(e|ability|ing)|load|traffic|concurrent|peak|growth|horizontal|vertical)\b", re.I),
    ],
    "data_flow": [
        re.compile(r"\b(data flow|data model|entity|schema|storage|database|cache|CDN|event stream)\b", re.I),
    ],
    "failure_modes": [
        re.compile(r"\b(fail(ure|s|ed)?|fault|downtime|degraded|circuit.breaker|retry|timeout|fallback|disaster)\b", re.I),
    ],
    "adr_rationale": [
        re.compile(r"\b(alternative|we considered|instead of|trade.?off|rejected|chosen because)\b", re.I),
    ],
}
```

---

### 3.3 Signal Detection Patterns — Weak / Strong / Emotional

**What it is**: Three lists of regex patterns. Weak signals trigger push-back. Strong signals allow
the coach to skip the exploratory phase. Emotional signals drive tone adaptation. These run on every
user turn, before the LLM is called. They are fast and deterministic.

**Questions to answer:**
- What does a stakeholder in this role typically say when they're being lazy or careless?
  (These become weak signal patterns.)
- What does an unusually well-prepared stakeholder say? (Strong signal patterns — allows fast-track.)
- Emotional patterns are mostly shared across roles; copy them and extend if needed.

**Priya's patterns (from `engine.py`, lines 258–293) — showing structure, not the full list:**

```python
# Weak signals — trigger push-back
_WEAK_SIGNAL_PATTERNS = [
    (SignalType.SOLUTION_BEFORE_PROBLEM,
     re.compile(r"\b(build|implement|add|create|develop|ship|launch)\b.{0,60}\b(feature|button|page|screen|flow|API)\b", re.I | re.S)),
    (SignalType.VAGUE_METRICS,
     re.compile(r"\b(improve(d)?|better|faster|easier|more (efficient|engaging|intuitive))\b(?!.{0,30}\d)", re.I)),
    (SignalType.VAGUE_IMPACT,
     re.compile(r"\b(big impact|huge|massive|significant|greatly|substantially)\b(?!.{0,40}\d)", re.I)),
    # ... COPPA_MINORS, SCOPE_CREEP, MISSING_ROLLOUT
]

# Strong signals — allow fast-track
_STRONG_SIGNAL_PATTERNS = [
    (SignalType.QUANTIFIED_PROBLEM,
     re.compile(r"\b\d[\d,\.]*\s*(%|users|sessions|tickets).{0,80}(problem|issue|fail|drop|churn)", re.I | re.S)),
    (SignalType.HYPOTHESIS_STATED,
     re.compile(r"\b(hypothesis|we believe (that )?if|if we .{0,40} then)\b", re.I)),
    (SignalType.TRADEOFF_STATED,
     re.compile(r"\b(tradeoff|trade.off|we considered|alternative(s)? (include|are|were)|instead of)\b", re.I)),
]
```

**Architect signal patterns (skeleton):**

```python
# pipeline/personas/architect/signals.py
import re
from pipeline.coach.engine import SignalType  # reuse emotional signals

# Define architect-specific signal types by extending or wrapping the enum pattern
# (or define a local ArchSignalType — do not modify the shared engine.py enum)

ARCHITECT_WEAK_PATTERNS = [
    # Architecture-before-requirements: "Let's use Kafka" before any requirements stated
    ("solution_before_requirements",
     re.compile(r"\b(use|adopt|go with|switch to|implement)\s+(Kafka|Redis|Postgres|Kubernetes|Lambda|GraphQL|gRPC)\b(?!.{0,80}(require|need|problem|constraint))", re.I | re.S)),

    # Missing NFRs: "it needs to be fast" without numbers
    ("vague_nfrs",
     re.compile(r"\b(fast|scalable|reliable|highly available|performant)\b(?!.{0,40}(\d+|\%|ms|SLA|SLO))", re.I)),

    # No failure modes considered
    ("no_failure_modes",
     re.compile(r"\b(it (should|will|must) work|it'll be fine|no downtime concern|won't fail)\b", re.I)),

    # Single-point-of-failure language
    ("single_point_of_failure",
     re.compile(r"\b(single (server|node|instance|database|service)|no (backup|replica|failover))\b", re.I)),
]

ARCHITECT_STRONG_PATTERNS = [
    # Quantified NFRs: "p99 latency < 200ms under 10k RPS"
    ("quantified_nfrs",
     re.compile(r"\b(p\d{2}|latency|throughput|RPS|TPS|uptime).{0,40}(\d+\s*(ms|s|%|RPS|TPS))\b", re.I)),

    # Alternatives considered
    ("alternatives_evaluated",
     re.compile(r"\b(we evaluated|we compared|alternative(s)? (include|were|are)|instead of|rejected because)\b", re.I)),

    # ADR reference: stakeholder already has a draft
    ("adr_draft_present",
     re.compile(r"\b(ADR|architecture decision record|decision record)\b", re.I)),
]
```

**Engineering Manager signal patterns (skeleton):**

```python
ENGINEERING_MANAGER_WEAK_PATTERNS = [
    # Optimism bias: estimates without buffers or unknowns
    ("optimism_bias",
     re.compile(r"\b(easy|simple|quick|straightforward|no problem|shouldn't take long|just a few days)\b", re.I)),

    # Missing dependency tracking
    ("undeclared_dependencies",
     re.compile(r"\b(depends on|waiting for|blocked by|need(s)? (them|the other team|platform))\b(?!.{0,80}(timeline|date|owner|ticket))", re.I)),

    # Unacknowledged blockers
    ("vague_blockers",
     re.compile(r"\b(some blockers|a few issues|minor concerns|nothing major)\b", re.I)),
]

ENGINEERING_MANAGER_STRONG_PATTERNS = [
    # Explicit capacity: "team has 3 engineers at 80% capacity for this sprint"
    ("explicit_capacity",
     re.compile(r"\b(\d+\s*(engineer|dev|developer|FTE|point|story point).{0,40}(capacity|available|allocated|sprint))\b", re.I)),

    # Velocity reference
    ("velocity_reference",
     re.compile(r"\b(velocity|average (sprint|throughput)|last (sprint|quarter|cycle)).{0,40}\d+\b", re.I)),
]
```

---

### 3.4 Domain Context Files — Knowledge Injection

**What it is**: Markdown files in a `domain-context/` directory that ContextAssembler reads and
concatenates into the system prompt. This is how org-specific knowledge reaches the LLM without
being hardcoded in prompt strings.

**Location**: Each persona has its own domain context directory:
`pipeline/personas/<name>/domain-context/`

The `DomainContext` class in `engine.py` (line 382) reads all `*.md` files in a directory,
sorted alphabetically, and joins them with `---` separators. Pass a custom `domain_dir` to
its constructor to point at a persona-specific directory.

**File format and structure** (from `hoopla-domain.md`, lines 1–50):

```markdown
# [Domain Name] — [Persona Name] Reference

> This file is injected into [Persona]'s system prompt by ContextAssembler at session start.
> It provides domain grounding for [specific purpose].
> Do not hardcode this knowledge into prompt templates — it lives here.

---

## 1. [Topic]

[Factual content. No opinions. No formatting fluff.]

---

## 2. [Topic with table if useful]

| Column | Column |
|---|---|
| value | value |

**Implications for [this role's decisions]:**
- [Specific implication 1]
- [Specific implication 2]
```

**What to include in a domain context file:**
- Org-specific terminology ("per-circulation", "BingePass", "KMP migration")
- Hard constraints the coach must know to evaluate inputs (budget model, regulatory requirements)
- Common pitfalls in this domain that the coach should recognize
- Platform or infrastructure facts the coach needs to ask informed questions
- Reference data (cost ranges, team sizes, velocity norms)

**What NOT to include in a domain context file:**
- The persona's behavioral rules (those belong in `persona.py`)
- Artifact schemas (those belong in `schemas.py`)
- Push-back patterns (those belong in `signals.py`)
- Anything that changes frequently — domain context is cached at session start

**Example: architect domain context topics**

```
pipeline/personas/architect/domain-context/
  tech-radar.md          # Approved and banned technologies, trial candidates
  approved-services.md   # Cloud services approved by security/procurement
  security-posture.md    # Data classification levels, auth standards, compliance requirements
  infra-constraints.md   # Existing infra (k8s cluster versions, DB engines in use, etc.)
```

---

### 3.5 Artifact Schemas — Output Contracts

**What it is**: A block of system prompt text that defines the exact structure the LLM must use
when generating artifacts. These are the handoff contracts with downstream systems. They must be
machine-readable — no narrative prose, no optional sections, no free-form commentary inside them.

**Questions to answer:**
- What document(s) does this coach produce when the conversation is complete?
- What is the exact field structure of each document?
- What downstream system consumes these? (Define the consumer before the schema.)
- What must be present in every artifact, even if the value is "UNKNOWN"?

**Priya's artifact schemas block (from `engine.py`, line 484 — partial):**

```python
_ARTIFACT_SCHEMAS_BLOCK = """
# Artifact Schemas

When generating artifacts, use EXACTLY these structures. No narrative prose,
no commentary, no caveats inside artifact output.

## business-case.md
```markdown
# Business Case: [Feature Name]

## Problem
[Clear problem statement]

## Evidence
[Data, research, or user feedback supporting the problem]

## Users
[Who is affected and how]

## Impact
[Quantified expected outcome — use ASSUMPTION: marker if not validated]

## Solution
[Proposed approach — high level only]

## Metrics
[How success will be measured, including baselines and targets]

## Risks
[Known risks and mitigations]

## Scope
[What is in and out of scope for this initiative]

## Platform
[Which client platforms are affected]
```
"""
```

**Architect artifact schema outline:**

```markdown
## adr.md
```markdown
# ADR-[NUMBER]: [Decision Title]

## Status
[Proposed | Accepted | Deprecated | Superseded by ADR-XXX]

## Context
[The situation that necessitates a decision. Include NFRs and constraints that are driving forces.]

## Requirements
[Functional and non-functional requirements this decision must satisfy]

## Options Considered
### Option 1: [Name]
- Description: ...
- Pros: ...
- Cons: ...

### Option 2: [Name]
...

## Decision
[The chosen option and why]

## Consequences
### Positive
[What gets better]

### Negative
[What gets harder, what is traded away]

### Risks
[What could go wrong, and mitigations]

## Integration Impact
[Systems that must change or be notified]

## Failure Modes
[How this decision fails and what the recovery path is]
```

## system-context.md
```markdown
# System Context: [System Name]

## Actors
[External systems and users that interact with this system]

## Responsibilities
[What this system does — functional boundary]

## Out of Scope
[What this system explicitly does not do]

## Integration Points
| System | Direction | Protocol | Owner |
|---|---|---|---|

## Data Classification
[What data this system handles and at what sensitivity level]

## NFR Targets
| Attribute | Target | Measurement Method |
|---|---|---|
```
```

**Engineering Manager artifact schema outline:**

```markdown
## sprint-plan.md
```markdown
# Sprint Plan: [Sprint Name / Number]

## Objective
[One sentence: what we are proving or delivering]

## Team Capacity
| Engineer | Availability | Allocated Points |
|---|---|---|

## Committed Stories
| Story ID | Title | Points | Owner | Dependencies |
|---|---|---|---|---|

## Dependencies
| Dependency | Owner Team | Required By | Status |
|---|---|---|---|

## Risks
| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|

## Definition of Done
[What must be true for this sprint to be considered complete]
```

## risk-register.md
```markdown
# Risk Register: [Team / Project]

| ID | Description | Likelihood | Impact | Owner | Mitigation | Status |
|---|---|---|---|---|---|---|
```
```

**PM artifact schema outline:**

```markdown
## milestone-map.md
```markdown
# Milestone Map: [Project Name]

## Objective
[Business goal this project achieves]

## Milestones
| Milestone | Target Date | Owner | Dependencies | Success Criteria |
|---|---|---|---|---|

## Critical Path
[Which milestones, if delayed, delay the project end date]

## Assumptions
[ASSUMPTION: markers for each unvalidated premise]
```

## raid-log.md
```markdown
# RAID Log: [Project Name]

## Risks
| ID | Description | Likelihood | Impact | Owner | Mitigation |
|---|---|---|---|---|---|

## Assumptions
| ID | Statement | Owner | Validation Method | Due |
|---|---|---|---|---|

## Issues
| ID | Description | Raised By | Owner | Resolution | Status |
|---|---|---|---|---|

## Dependencies
| ID | Description | Depends On | Owner | Required By | Status |
|---|---|---|---|---|
```
```

---

## 4. File Structure for a New Persona

```
pipeline/
  personas/
    architect/
      __init__.py           # Exports: PERSONA_BLOCK, SCORED_FIELDS, FIELD_PATTERNS,
                            #          FIELD_WEIGHTS, ARTIFACT_GATE_THRESHOLD,
                            #          WEAK_PATTERNS, STRONG_PATTERNS, ARTIFACT_SCHEMAS_BLOCK
      persona.py            # PERSONA_BLOCK string
      tracker.py            # SCORED_FIELDS, FIELD_PATTERNS, FIELD_WEIGHTS, ARTIFACT_GATE_THRESHOLD
      signals.py            # WEAK_PATTERNS, STRONG_PATTERNS (emotional patterns shared from engine.py)
      schemas.py            # ARTIFACT_SCHEMAS_BLOCK string
      domain-context/
        tech-radar.md
        approved-services.md
        security-posture.md
    em/
      __init__.py
      persona.py
      tracker.py
      signals.py
      schemas.py
      domain-context/
        team-topology.md
        sprint-cadence.md
    qa/
      ...
    pm/
      ...
    release/
      ...
  coach/
    engine.py               # Shared kernel — do not modify for a new persona
    memory.py               # Shared — do not modify
    crystallizer.py         # Shared — do not modify
    server.py               # Add new route here; touch minimally
  intake/
    domain-context/         # Priya's existing domain context — do not move
      hoopla-domain.md
```

---

## 5. Step-by-Step: Creating a New Persona

### Step 1: Copy the scaffold

```bash
cp -r pipeline/personas/priya pipeline/personas/architect
# Then hollow out the strings — do not keep Priya's content
```

### Step 2: Define the behavioral contract

Edit `pipeline/personas/architect/persona.py`. Fill in:
- Name, role, org context
- Explicit list of artifacts this coach produces (by filename)
- Explicit list of what it refuses to produce
- Push-back triggers (at least 5, role-specific)
- Tone adaptation rules (copy the structure, adapt the anchors)

Do not soften the push-back. The challenge behavior is the value.

### Step 3: Define progress fields and weights

Edit `pipeline/personas/architect/tracker.py`. Define:
- `SCORED_FIELDS`: list of field names (6–10)
- `FIELD_PATTERNS`: dict of `field_name → list[re.Pattern]` (2 patterns minimum per field)
- `FIELD_WEIGHTS`: dict of `field_name → float` (must sum to a meaningful total; see Priya's weights)
- `ARTIFACT_GATE_THRESHOLD`: float (0.65–0.80 depending on stakes)

Test each regex against real stakeholder inputs before committing.

### Step 4: Write signal detection patterns

Edit `pipeline/personas/architect/signals.py`. Define:
- `WEAK_PATTERNS`: list of `(name, re.Pattern)` tuples — anti-patterns to push back on
- `STRONG_PATTERNS`: list of `(name, re.Pattern)` tuples — fast-track conditions

Emotional patterns are shared infrastructure in `engine.py`. Do not duplicate them; import
`_EMOTIONAL_SIGNAL_PATTERNS` from `pipeline.coach.engine` if you need them in tests.

### Step 5: Write domain context markdown

Create `pipeline/personas/architect/domain-context/tech-radar.md` and siblings. Follow the
format from `hoopla-domain.md`. Include org-specific constraints. No behavioral rules here.

### Step 6: Define artifact schemas

Edit `pipeline/personas/architect/schemas.py`. Define `ARTIFACT_SCHEMAS_BLOCK` as a multiline
string. Every field in the schema must have a placeholder. No optional sections — downstream
consumers must be able to parse every artifact deterministically.

### Step 7: Wire up to CoachEngine

`CoachEngine.__init__` (engine.py, line 722) accepts:
- `backend: AgentBackend`
- `domain_context: DomainContext | None`
- `memory_context: str`

`ContextAssembler.__init__` (engine.py, around line 600) accepts a `domain_context`.

For new personas, you need to pass custom persona/tracker/signal/schema content. The cleanest
approach without modifying engine.py is to subclass `ContextAssembler` in your persona module
and override `build()` to inject your persona's `_PERSONA_BLOCK` and `_ARTIFACT_SCHEMAS_BLOCK`.
Pass a `DomainContext` pointed at your persona's domain-context directory.

```python
# pipeline/personas/architect/__init__.py
from pipeline.coach.engine import CoachEngine, DomainContext
from pipeline.personas.architect import persona, tracker, schemas

def create_engine(backend, memory_context=""):
    domain_ctx = DomainContext(
        domain_dir="pipeline/personas/architect/domain-context"
    )
    # ContextAssembler subclass or monkey-patch pattern — see Step 7 detail in docs
    engine = CoachEngine(
        backend=backend,
        domain_context=domain_ctx,
        memory_context=memory_context,
    )
    # Override assembler constants
    engine._assembler._persona_block = persona.PERSONA_BLOCK
    engine._assembler._artifact_schemas_block = schemas.ARTIFACT_SCHEMAS_BLOCK
    engine._tracker = tracker.build_tracker()  # returns a configured ProgressTracker
    return engine
```

### Step 8: Register in the CLI

In `pipeline/coach/__main__.py`, add your persona as a `--persona` flag option:

```python
parser.add_argument(
    "--persona",
    choices=["priya", "architect", "em", "qa", "pm", "release"],
    default="priya",
)
```

Map the choice to the appropriate `create_engine()` factory from your persona module.

### Step 9: Write hardening tests

Create `tests/test_hardening_architect.py`. See Section 6 for required test coverage.

### Step 10: Test live

```bash
python3 -m pipeline.coach --persona architect --backend ollama --model llama3
```

Run a session that intentionally triggers each push-back pattern. Verify the coach challenges
them. Run a session with a strong-signal input and verify fast-track behavior.

---

## 6. Testing Philosophy for New Personas

### Required Hardening Tests

Every new persona must have tests covering:

1. **Signal detection accuracy** — each weak signal pattern fires on a matching input
2. **Artifact gating** — coach refuses to generate when completeness is below threshold
3. **Role boundary enforcement** — coach refuses to produce prohibited outputs
4. **Non-fabrication** — coach says "I don't have that data" rather than inventing it
5. **Brevity enforcement** — push-back responses are 2 sentences or fewer
6. **Anti-loop** — coach does not re-ask a question from a prior turn

### Test Structure (from `test_hardening.py` pattern)

```python
# tests/test_hardening_architect.py
import pytest
from pipeline.personas.architect.signals import ARCHITECT_WEAK_PATTERNS

class TestArchitectSignalDetection:
    """Each test is a behavioral specification, not a unit test."""

    @pytest.mark.parametrize("text,expected_signal", [
        ("Let's use Kafka for this", "solution_before_requirements"),
        ("it needs to be fast and reliable", "vague_nfrs"),
        ("it'll be fine, no failure concerns", "no_failure_modes"),
    ])
    def test_weak_signal_detected(self, text, expected_signal):
        """Weak signal patterns fire on expected inputs."""
        matched = [
            name for name, pattern in ARCHITECT_WEAK_PATTERNS
            if pattern.search(text)
        ]
        assert expected_signal in matched, (
            f"Expected '{expected_signal}' in signals for: {text!r}\n"
            f"Got: {matched}"
        )

    def test_artifact_gating_blocks_incomplete_spec(self, architect_engine):
        """Coach refuses /generate when completeness is below threshold."""
        response = architect_engine.chat("/generate")
        assert "requirements" in response.lower() or "missing" in response.lower()

    def test_no_code_generation(self, architect_engine):
        """Coach refuses to write code even when asked directly."""
        response = architect_engine.chat("Write me a Python class for this service")
        assert "code" not in response.lower() or "generate" not in response.lower()
        # More precisely: response should redirect, not comply
        assert any(kw in response.lower() for kw in ["spec", "artifact", "architect", "document"])
```

### Artifact Gating Test Structure

```python
def test_artifact_gate_threshold(self, architect_engine):
    """Completeness must reach threshold before artifacts are produced."""
    from pipeline.personas.architect.tracker import ARTIFACT_GATE_THRESHOLD
    tracker = architect_engine.tracker
    # Simulate partial input
    architect_engine.chat("We want to use a microservices approach")
    assert not tracker.is_ready_for_artifacts(), (
        f"Tracker should block artifacts at {tracker.completeness():.0%} completeness"
    )
```

### Minimum Coverage Before Beta

- All weak signal patterns: at least 2 positive test inputs each
- Artifact gating: test at 0%, ~50%, and just below threshold
- Role boundary: at least 3 prohibited output requests tested
- One end-to-end session test: feed a complete, well-formed input and verify artifact generation

---

## 7. Deployment: Running Multiple Personas

### Single Server, Multiple Routes

In `server.py`, add a route per persona following the Priya pattern at `/api/coach`:

```python
# server.py additions
from pipeline.personas.architect import create_engine as create_architect_engine
from pipeline.personas.em import create_engine as create_em_engine

@app.route("/api/v1/architect", methods=["POST"])
async def architect_endpoint():
    # Same streaming pattern as /api/coach
    ...
```

Each persona gets its own session namespace. Use a `persona` prefix in session IDs:
`architect-<uuid>`, `em-<uuid>`, etc.

### Shared Memory DB with Workspace Isolation

`CoachMemory` (memory.py) uses a single SQLite database. Add a `workspace_id` column to
isolate personas:

```sql
ALTER TABLE sessions ADD COLUMN workspace_id TEXT NOT NULL DEFAULT 'priya';
ALTER TABLE crystal_items ADD COLUMN workspace_id TEXT NOT NULL DEFAULT 'priya';
```

Pass `workspace_id=persona_name` to `save_session()` and `recall()` to prevent cross-persona
memory bleed. Priya should not recall Architect session learnings and vice versa.

### Docker Compose Example

```yaml
# docker-compose.yml
services:
  priya:
    build: .
    command: python3 -m pipeline.coach --persona priya --port 3456 --backend ollama
    ports:
      - "3456:3456"
    volumes:
      - coach-memory:/root/.hoopla

  architect:
    build: .
    command: python3 -m pipeline.coach --persona architect --port 3457 --backend ollama
    ports:
      - "3457:3457"
    volumes:
      - coach-memory:/root/.hoopla  # shared memory volume

  ollama:
    image: ollama/ollama
    ports:
      - "11434:11434"
    volumes:
      - ollama-models:/root/.ollama

volumes:
  coach-memory:
  ollama-models:
```

---

## 8. Persona Cookbook: Role-Specific Notes

### 8.1 Architect Coach

**Persona name**: Reza (or your choice — name it for the culture)
**Audience**: Senior engineers, tech leads, staff engineers submitting architecture proposals

**Key tensions to enforce:**
- Solution-before-requirements: "Let's use Kafka" before any requirements are stated
- Missing NFRs: "fast and reliable" without numbers attached
- No failure mode analysis: "it'll scale fine" without evidence
- Premature optimization: designing for 10x load when current is unclear
- Missing security model: no mention of auth, data classification, or threat surface

**Artifacts**: `adr.md`, `system-context.md`

**What "good" looks like**: Stakeholder arrives with quantified NFRs, 2+ alternatives evaluated,
failure modes listed, integration points named with owners, and data classification specified.
Fast-track to ADR generation immediately.

**Sample domain context topics for `tech-radar.md`**:
- Adopted technologies (go-tos, no approval needed)
- Trial technologies (use with caution, document rationale)
- Assess technologies (evaluate before adopting)
- Hold/banned technologies (require exception process)
- Approved cloud services and procurement channels

---

### 8.2 Engineering Manager Coach

**Persona name**: Marcus (or your choice)
**Audience**: Engineering managers, team leads doing sprint planning and capacity forecasting

**Key tensions to enforce:**
- Optimism bias in estimates: "shouldn't take long," "easy win," "a few days"
- Unacknowledged blockers: vague references to dependencies without owners or dates
- Missing dependency tracking: "we need the platform team" without a ticket reference
- No buffer: zero slack in a sprint plan
- Absent team members not accounted for: vacation, on-call rotation, context switch cost

**Artifacts**: `sprint-plan.md`, `risk-register.md`

**Completeness fields**: objective, team_capacity, committed_stories, dependencies, risks,
definition_of_done, velocity_baseline

**Sample domain context topics for `team-topology.md`**:
- Team structure and reporting lines
- Sprint cadence and ceremony schedule
- Velocity history (rolling average)
- On-call rotation impact on sprint capacity
- Known upcoming PTO or team events

---

### 8.3 QA / STE Coach

**Persona name**: Nadia (or your choice)
**Audience**: Software Test Engineers, QA leads writing test strategies for a feature or release

**Key tensions to enforce:**
- Test coverage theater: "we have 90% code coverage" without specifying what the tests actually verify
- Missing edge cases: happy-path-only thinking, no boundary conditions or error paths
- No performance criteria: functional tests only, no load/stress/latency targets
- Accessibility omission: WCAG AA is contractually required at Hoopla; missing it is a ship blocker
- Missing regression scope: no mention of what existing functionality could break

**Artifacts**: `test-strategy.md`, `quality-gate-definition.md`

**Completeness fields**: feature_scope, test_types, coverage_targets, edge_cases,
performance_criteria, accessibility_criteria, regression_scope, environments, sign_off_criteria

---

### 8.4 Project Manager Coach

**Persona name**: Chloe (or your choice)
**Audience**: Project managers and delivery leads building project plans

**Key tensions to enforce:**
- Missing dependencies: milestones listed without dependency chains
- Optimistic timelines: no buffer weeks, no float on the critical path
- Absent rollback plan: no "what if we must stop" scenario
- Unowned risks: risks listed without assigned owners
- Stakeholder gaps: decision-makers not identified for key milestones

**Artifacts**: `milestone-map.md`, `raid-log.md` (Risks, Assumptions, Issues, Dependencies)

**Completeness fields**: objective, stakeholders, milestones, dependencies, risks,
budget, success_criteria, rollback_plan

---

### 8.5 Release Manager Coach

**Persona name**: Devon (or your choice)
**Audience**: Release managers and release coordinators preparing a production release

**Key tensions to enforce:**
- No rollback plan: release described without a "what if we need to revert" procedure
- Missing stakeholder comms: no notification plan for downstream teams or external partners
- Incomplete runbook: steps listed without owners, time estimates, or verification checkpoints
- No pre-release validation: no smoke test or staged rollout described
- Missing monitoring plan: no mention of what to watch in the first 24 hours post-release

**Artifacts**: `release-checklist.md`, `runbook.md`

**Completeness fields**: release_scope, rollback_plan, stakeholder_comms, runbook_steps,
pre_release_validation, monitoring_plan, go_no_go_criteria, release_window

**Gate threshold**: `0.75` — a release runbook with gaps is more dangerous than a business case
with gaps. Set the bar higher.

---

## 9. Anti-Patterns to Avoid

**Do not make the new coach nicer than Priya.** The push-back behavior is the value. A coach that
says "great point, but..." is less useful than one that says "what's the failure mode for that
approach?" Softening push-back degrades artifact quality. The hardening tests will catch it.

**Do not skip hardening tests.** The tests are behavioral specifications, not quality theater.
A persona without tests is a persona whose behavioral contract is aspirational, not enforced.

**Do not embed domain knowledge in persona strings.** If you write "Hoopla charges per-circulation"
in the PERSONA_BLOCK, you have created a maintenance burden and violated the file-driven domain
context invariant. Put it in a domain context markdown file.

**Do not share progress tracker fields across personas.** An Architect's "completeness" is not
a PM's "completeness." Each persona has its own model of what a well-formed input looks like.
Sharing fields collapses that distinction and produces worse coaching.

**Do not add code generation to any coach persona.** The coach-to-spec-compiler boundary is
architectural. A coach that writes code is a code assistant, not a spec funnel. The downstream
Spec Compiler handles translation to code. Keep the boundary.

**Do not reuse Priya's persona strings for a new role.** Copy the structure, not the content.
A product coach and an architect coach have fundamentally different push-back patterns.

**Do not set the gate threshold below 0.60.** Below that, the coach will generate artifacts that
are structurally incomplete. Downstream systems will fail silently or produce garbage output.

---

## 10. Checklists

### Definition of Done — New Persona Beta Readiness

- [ ] `persona.py` written with at least 5 role-specific push-back triggers
- [ ] `persona.py` explicitly lists prohibited outputs by name
- [ ] `tracker.py` defines 6–10 scored fields with individual weights
- [ ] `tracker.py` sets `ARTIFACT_GATE_THRESHOLD >= 0.65`
- [ ] `signals.py` has at least 4 weak signal patterns and 2 strong signal patterns
- [ ] All regex patterns tested against at least 2 real stakeholder inputs each
- [ ] At least 2 domain context markdown files written and loading correctly
- [ ] `schemas.py` defines at least 1 artifact schema with all fields specified
- [ ] Artifact schemas have no optional sections (downstream parsers must not branch)
- [ ] Hardening test file exists and covers all 6 required test categories (Section 6)
- [ ] All hardening tests pass against the configured backend
- [ ] Persona registered in `__main__.py` CLI with `--persona` flag
- [ ] Server route registered in `server.py`
- [ ] At least one end-to-end live session run and reviewed for behavioral correctness
- [ ] No compliments detected in live session responses
- [ ] Artifact gating verified: coach blocks `/generate` below threshold in live session

### Persona Quality Review — Behavioral Checklist

Run this checklist in a live session before approving a persona for beta:

- [ ] Coach pushes back on solution-before-[role-specific prerequisite]
- [ ] Coach pushes back on vague quantitative claims (no number = push back)
- [ ] Coach does not re-ask a question from a prior turn in a 10-turn session
- [ ] Coach produces artifacts only after `/generate` is called, not spontaneously
- [ ] Coach refuses `/generate` when tracker reports missing fields
- [ ] Coach names the missing fields specifically in the refusal
- [ ] Coach does not fabricate data when asked for a number it doesn't have
- [ ] Coach does not generate code, SQL, or infrastructure diagrams when asked
- [ ] Coach adapts tone appropriately when "I'm frustrated" or "this is overwhelming" is stated
- [ ] Artifact output is structured markdown only — no preamble, no closing narrative
- [ ] Assumptions in artifacts are labeled with `ASSUMPTION:` marker

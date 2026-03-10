# Proposal: Spec-as-Acceptance-Criteria Pipeline

**Date**: 2026-03-10
**Status**: Draft
**Context**: Pipeline pattern analysis from 2026-03-08 wave run (78/293 units completed, 21 genuine quality failures, 187 blocked by infrastructure or serial execution)

---

## Problem Statement

The current pipeline follows a **spec-mediated serial pattern**:

```
monolithic requirement
  → compiled spec (what to build)
  → context file (where to build it, path conventions, layer rules)
  → test spec (how to verify it)
  → coding agent executes spec (implementation stage)
  → testing agent verifies (testing stage)
  → quality gate evaluates (quality_gate stage)
  → human review (human_review stage, currently ceremonial)
```

Each unit passes through every stage sequentially. Each wave completes a stage for all units before starting the next stage. The compiled spec is the coding agent's primary input — it describes the codebase rather than giving the agent access to it.

This creates three classes of problems visible in the 2026-03-08 run:

### 1. Spec-codebase drift (Pattern 3 from analysis)

The spec tells the agent where to put files. But the spec's path model can diverge from reality:

- KMP files generated at repo root instead of `shared/src/commonMain/kotlin/` — the agent followed the spec's abstraction instead of discovering the actual directory structure
- `biiometric/` typo in a generated package name — the agent had no way to cross-check against the existing `biometric/` directory
- Test file routing unknown for BFF and KMP layers — the spec's path model was incomplete, so the router deployed files "as-is"

An agent with codebase access would `ls` the existing directory, find `biometric/`, and match it. The spec intermediary removes this self-correction capability.

### 2. Rigid serial execution (Pattern 4)

Implementation and testing stages show a suspiciously uniform ~70s duration regardless of unit complexity. Every unit pays the same pipeline tax. A unit that requires adding 3 lines to an existing file takes the same wall-clock time as one requiring a new module with 200 lines.

The serial stage model also prevents **within-unit parallelism**. An agent working directly from the codebase could write implementation and tests together (as human developers do), validate them locally, and submit the result. The current pipeline forces an artificial separation: first generate all code, then generate all tests, then evaluate.

### 3. Agent capability underutilization

Modern coding agents can:
- Navigate codebases (find existing conventions, patterns, imports)
- Validate their own work (run builds, execute tests, check linting)
- Self-correct (fix compilation errors, adjust paths, retry)
- Discover context dynamically (read adjacent files, check APIs, find examples)

The spec-mediated pipeline strips these capabilities away. The agent receives a document *about* the code instead of the code itself. It generates output into a void and waits for a separate stage to tell it whether the output was correct. This is like asking a developer to write code based on a description of the repo without giving them access to the repo.

---

## Proposed Model: Spec as Acceptance Criteria

Instead of the spec being a **work instruction** ("put this code in this file at this path"), the spec becomes a **goal definition + acceptance test** ("here's what must be true when you're done").

### Current vs. Proposed

| Aspect | Current: Spec as Work Instruction | Proposed: Spec as Acceptance Criteria |
|--------|-----------------------------------|---------------------------------------|
| Agent's primary input | Compiled spec document | Codebase + acceptance criteria |
| Path discovery | Spec dictates paths | Agent discovers paths from codebase |
| Self-validation | Not possible; separate testing stage | Agent runs tests as it works |
| Error correction | Gate rejects → human reviews → re-queue | Agent fixes errors in-loop |
| Observability | Inspect intermediate spec artifacts | Inspect acceptance criteria pass/fail + agent trace |
| Parallelism | Per-stage, sequential across stages | Per-unit, agent drives its own stages |
| Stage model | implementation → testing → quality_gate → human_review | agent_execution → quality_gate → human_review |

### What the Agent Receives

```yaml
unit: 01-LOGIN_008-bff
layer: bff
feature: LOGIN

# --- Goal (from Priya's artifacts, compiled) ---
goal: |
  Implement biometric enrollment state management for the BFF layer.
  When a patron initiates biometric enrollment, the BFF must track
  enrollment state (not_started, in_progress, completed, failed)
  and expose it via the existing /api/patron/settings endpoint.

# --- Acceptance Criteria (machine-checkable where possible) ---
acceptance:
  - New or modified files must be under the BFF source tree (agent discovers exact path)
  - Enrollment state enum: not_started, in_progress, completed, failed
  - /api/patron/settings response includes biometric_enrollment_status field
  - Existing tests continue to pass (no regressions)
  - New tests cover: state transitions, API response shape, error cases
  - Code follows existing BFF conventions (agent infers from codebase)

# --- Constraints (hard boundaries) ---
constraints:
  - Do not modify KMP shared module (this is a BFF-only change)
  - Do not add new dependencies without documenting rationale
  - WCAG AA: any UI-facing changes must be accessible

# --- Context Hints (optional, not prescriptive) ---
hints:
  - Similar pattern exists in /api/patron/preferences (see PatronPreferencesController)
  - Enrollment state is analogous to existing NotificationOptInStatus
  - BFF test conventions: see src/test/kotlin/api/patron/ for examples
```

### What Changes

**The agent gets codebase access.** It can read files, discover conventions, find existing patterns, and validate its work against real compilation and test execution.

**The agent drives its own stage sequence.** Instead of external orchestration through implementation → testing → quality_gate, the agent internally:
1. Reads the acceptance criteria
2. Explores the codebase to understand where and how to implement
3. Implements the change
4. Writes tests
5. Runs tests locally to validate
6. Self-corrects if tests fail
7. Submits the result (code changes + test results + trace log)

**The quality gate checks outcomes, not process.** Instead of evaluating whether the agent followed the spec's path instructions, the gate checks:
- Do acceptance criteria pass?
- Do existing tests still pass?
- Does the code follow codebase conventions? (inferred from the codebase, not from spec rules)
- Are there obvious quality problems? (unused imports, dead code, etc.)

**The orchestrator manages units, not stages.** Each unit is an independent agent execution. The orchestrator:
- Assigns units to agents
- Manages concurrency (respecting infrastructure limits)
- Collects results
- Routes failures to human review
- Tracks wave progress

### What Stays the Same

**Priya's coaching layer is unchanged.** The spec funnel boundary holds. Priya produces business-case.md, epics.md, stories-draft.md. The Spec Compiler still translates these into the goal/acceptance/constraints format above. The change is in what happens *after* compilation.

**Human observability is preserved**, but shifts:
- **Before**: Inspect compiled spec, context file, test spec (intermediate artifacts)
- **After**: Inspect acceptance criteria (input), agent trace log (process), quality gate verdict (output)

The trace log is arguably *more* observable than the current model — you see the agent's reasoning, the files it read, the tests it ran, and where it self-corrected. Currently you see a compiled spec go in and code come out, with the agent's decision-making invisible.

**Quality gating still exists.** The gate's input changes (checking code against acceptance criteria and codebase conventions rather than spec compliance), but the gate function remains.

---

## Impact on Observed Failure Patterns

### Pattern 3 (File Path Routing): Eliminated

The agent discovers paths from the codebase. No spec-encoded routing rules to go stale. No `biiometric/` typos because the agent sees `biometric/` already exists. No root-level `.kt` misplacement because the agent navigates to `shared/src/commonMain/kotlin/` by reading the project structure.

### Pattern 4 (Rigid Serial Execution): Eliminated

The agent executes implementation + testing as a single unit of work. No artificial stage separation. No ~70s floor from pipeline overhead. Simple units complete fast; complex units take longer. The orchestrator manages unit-level concurrency, not stage-level sequencing.

### Pattern 6 (Ceremonial Human Review): Simplified

Human review triggers only on quality gate failure or agent-flagged uncertainty ("I found two plausible locations for this code — which convention should I follow?"). No blanket skip → auto-advance cycle.

### Pattern 1 (Infrastructure Collapse): Partially Addressed

Per-unit agent execution means a server crash affects only the unit in progress, not an entire wave. The orchestrator can detect infrastructure failure after one unit fails (circuit breaker) rather than burning through a batch. However, the underlying llama-server stability problem remains an infrastructure concern independent of pipeline architecture.

### Pattern 2 (Opaque Gate Verdicts): Directly Addressed

The quality gate checks acceptance criteria by name. A failure verdict is inherently explanatory: "FAIL: acceptance criterion 3 not met — /api/patron/settings response does not include biometric_enrollment_status field." No more `verdict: unknown`.

### Pattern 5 (Premature Wave Progression): Simplified

With per-unit execution, wave progression is based on unit completion counts and health checks, not stage completion across a batch. The orchestrator has natural checkpoints between units.

---

## Architecture Changes Required

### In This Repo (Priya/Coach)

**None.** Priya's coaching layer, artifact schemas, and spec funnel boundary are unchanged. The proposal affects the downstream pipeline (accelerate-poc-test), not the coaching core.

### In Spec Compiler (Phase 3)

The Spec Compiler's output format changes from:
- **Current**: compiled spec + context file + test spec (three separate documents prescribing work)
- **Proposed**: goal + acceptance criteria + constraints + hints (single document defining "done")

This is a format change, not an architectural change. The Spec Compiler still translates Priya's business artifacts into engineering-consumable specs. The translation just targets a different output schema.

### In Pipeline Runner (accelerate-poc-test)

This is the major change:

1. **Agent execution model**: Replace the 4-stage sequential pipeline with a single agent-execution stage per unit. The agent receives (acceptance criteria + codebase access) and returns (code changes + test results + trace log).

2. **Orchestrator simplification**: The orchestrator manages unit assignment and concurrency, not stage transitions. Wave logic remains but operates on units, not stages.

3. **Quality gate adaptation**: The gate evaluates acceptance criteria pass/fail and codebase convention compliance, not spec-path compliance.

4. **Infrastructure health**: Add circuit breaker between units (not between stages). If N consecutive units fail with infrastructure errors, pause and alert.

---

## Migration Path

### Phase A: Acceptance Criteria Format

Define the goal/acceptance/constraints/hints YAML schema. Adapt the Spec Compiler to produce this format alongside (not replacing) the current compiled spec. Run both formats in parallel to validate equivalence.

### Phase B: Agent Codebase Access

Give the coding agent direct read access to the codebase (initially read-only for discovery). Keep the compiled spec as the primary work instruction but let the agent cross-reference against the codebase. This alone would fix Pattern 3 (path routing gaps).

### Phase C: Agent Self-Validation

Allow the agent to run tests during implementation (not as a separate stage). The pipeline still runs a quality gate after, but the agent's self-validation catches obvious errors before gate evaluation. This collapses the implementation + testing stages into one.

### Phase D: Full Transition

Remove the compiled spec as a work instruction. The agent works from acceptance criteria + codebase. The orchestrator manages units, not stages. The quality gate checks outcomes, not process.

### Phase E: Parallel Execution

With per-unit agent execution, increase concurrency. Multiple units execute simultaneously (respecting codebase write conflicts via isolation — worktrees or branch-per-unit). The orchestrator manages merge ordering based on wave dependency graph.

---

## Risks and Mitigations

### Risk: Reduced observability

**Current model** produces intermediate artifacts (compiled spec, context file) that humans can inspect before execution.

**Mitigation**: The agent trace log provides richer observability — you see *what the agent actually did*, not what it was told to do. Acceptance criteria are inspectable before execution. The quality gate verdict is inherently explanatory.

### Risk: Agent capability variance

Not all LLM backends can reliably navigate codebases, run tests, and self-correct. The current model works with simpler agents because the pipeline does the thinking.

**Mitigation**: Phase B (codebase access for cross-reference only) and Phase C (self-validation) are incremental. If the agent can't reliably self-validate, the external quality gate still catches failures. The pipeline degrades gracefully — worse agents just trigger more gate failures, not silent corruption.

### Risk: Codebase write conflicts

Multiple agents writing to the same codebase simultaneously could create merge conflicts.

**Mitigation**: Use git worktrees or branch-per-unit isolation. The wave dependency graph already encodes which units can run in parallel. Units in the same layer/feature domain that touch overlapping files should be sequenced; unrelated units run concurrently.

### Risk: Spec Compiler output format change

Changing the Spec Compiler's output is a cross-system contract change.

**Mitigation**: The migration path (Phase A) runs both formats in parallel. The acceptance criteria format is strictly more informative than the current format — it contains everything the compiled spec does, plus explicit pass/fail criteria.

### Risk: Quality gate must become smarter

The current gate checks structural compliance (paths, file presence). The new gate must evaluate acceptance criteria semantically.

**Mitigation**: Many acceptance criteria are machine-checkable ("tests pass," "file exists under BFF source tree," "API response includes field X"). Semantic criteria ("follows existing conventions") can use the same LLM that powers the coding agent — the gate asks "does this code follow the patterns in adjacent files?" with the codebase as context.

---

## Relationship to Priya Phases

| Priya Phase | Impact |
|-------------|--------|
| Phase 1 (llama.cpp backend) | None. This proposal is downstream of Priya. |
| Phase 2 (RAG + domain context) | None directly. RAG improves Priya's coaching quality, which improves the business artifacts fed to the Spec Compiler, which improves acceptance criteria quality. Virtuous cycle. |
| Phase 3 (formalize spec output) | **Direct alignment.** Phase 3 defines handoff contracts for Confluence/Jira/Figma. The acceptance criteria format proposed here is a natural extension — it's the handoff contract for coding agents. Phase 3 should define both human-readable (Confluence) and agent-readable (acceptance YAML) output schemas. |
| Phase 4 (agentic layer) | **Direct alignment.** Phase 4 wraps Priya in an agentic layer. This proposal defines how the downstream agentic layer (coding agents) should receive and execute work. The two layers share the acceptance criteria contract. |
| Phase 5 (beta deployment) | This proposal directly improves the metric Phase 5 measures: spec-to-code pipeline success rate. The 2026-03-08 run achieved 27% throughput (78/293). Eliminating Patterns 3, 4, and 6 alone should push this above 60%. |

---

## Decision Needed

This proposal changes the downstream pipeline architecture, not Priya's coaching core. It requires changes in:

1. **Spec Compiler** (output format) — Phase 3 work, not yet started
2. **Pipeline runner** (accelerate-poc-test) — orchestration model change
3. **Quality gate** (evaluation criteria) — structural → acceptance-based

The migration path is incremental (Phases A through E). Phase B alone (agent codebase access for cross-reference) would address the most painful failure pattern (Pattern 3, file path routing) with minimal architectural change.

**Recommendation**: Start with Phase B. Give coding agents read access to the codebase during implementation. Keep everything else the same. Measure whether path routing failures drop. If they do, proceed to Phase C (self-validation). This de-risks the full transition while delivering immediate value.

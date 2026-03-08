# Pipeline Pattern Analysis — Wave Run 2026-03-08

**Source**: `accelerate-poc-test` fresh run, waves 0–4 (partial), waves 5–7 not started
**Total units**: 293 across 8 waves | **Completed**: 78 passed auto-advance | **Held**: 21 for manual review | **Blocked**: 194 (pending/in_progress/infrastructure failure)

---

## Executive Summary

The pipeline executed well through waves 0–1 (13 units, 100% auto-advance) but hit two distinct failure modes at scale: **quality gate rejections** starting in wave 2 (38% hold rate) and a **llama-server crash** in wave 4 that halted all subsequent processing. These are separate problems requiring separate fixes. The gate rejections indicate spec/code quality issues in specific layers; the server crash is an infrastructure stability gap that blocked ~194 units from ever being attempted.

---

## Pattern 1: llama-server Collapse Under Sustained Load (Critical)

### What happened
- **Wave 4 testing**: 2 of 29 units failed with `HTTP Error 500: Internal Server Error` from llama-server at `127.0.0.1:8082`
  - `05-HOOPLA_006-kmp` and `10-GRID_BROWSE_005-native`
- **Wave 4 quality_gate**: Server crashed entirely. First unit (`06-SETTINGS_006-kmp`) got "Remote end closed connection without response", then the remaining 10 units got `Connection refused` — the process was dead.
- **At 22:10:08**: 10 quality_gate entries share the exact same timestamp — they were batch-recorded as failures when the server was unreachable.
- **Waves 5–7**: All 7 wave-5 units failed (server still down). Waves 6–7 recorded 0 passed, 0 failed, 0 skipped — the runner couldn't even start them.

### Timeline
```
~21:37  05-HOOPLA_006-kmp testing → HTTP 500 (server stressed)
~21:49  10-GRID_BROWSE_005-native testing → HTTP 500 (server degrading)
~22:09  06-SETTINGS_006-kmp quality_gate → "Remote end closed" (server dying)
22:10   10 units batch-fail quality_gate → Connection refused (server dead)
22:10   Wave 5 attempted → 7 units fail immediately (server still dead)
```

### Impact
- 13 wave-4 units failed due to infrastructure, not code quality
- 174 units in waves 5–7 never ran
- The entire run's effective throughput was 78/293 = **27%** — but **only 21 were genuine quality failures**. The rest were infrastructure waste.

### Root cause hypothesis
The `max_tokens` was recently reduced from 16384→4096 (commit `4521ea9`), but the sustained concurrent load across 29 wave-4 units likely exhausted server memory or hit context window limits. The server has no health-check-based circuit breaker, no auto-restart on crash, and no retry logic for transient 500s.

### Recommendations
1. **Add health-check probing + auto-restart** to the llama-server process. ModelServer already has `MAX_RESTARTS=3` — ensure the pipeline runner uses it or equivalent.
2. **Implement retry with backoff** for HTTP 500 errors. Currently: "Total retry events: 0". A 500 from an inference server is often transient (context slot contention). 2–3 retries with 5s/10s/20s backoff would have saved 2 wave-4 test failures.
3. **Add a circuit breaker**: If N consecutive units fail with connection errors, pause the wave and surface the infrastructure error rather than burning through all remaining units against a dead server.
4. **Monitor server memory**: The 500→connection-refused pattern is classic OOM kill. Add a pre-wave health check that verifies free memory and active context slots before starting a large batch.

---

## Pattern 2: Quality Gate Hold Rate Increases with Wave Depth

### Data

| Wave | Units | Auto-advanced | Held (GATE_FAIL) | Hold Rate |
|------|-------|---------------|-------------------|-----------|
| 0    | 3     | 3             | 0                 | 0%        |
| 1    | 10    | 10            | 0                 | 0%        |
| 2    | 29    | 18            | 11                | 38%       |
| 3    | 41    | 31            | 10                | 24%       |
| 4    | 16*   | 16            | 0                 | 0%        |

*Wave 4 had only 16 reach human_review due to server crash; the 16 survivors all passed.

### Pattern
Waves 0–1 are "seed" waves with the simplest, most well-defined units. Wave 2 introduces the first real breadth (29 units, 12 feature domains) and the gate starts rejecting. Wave 3 maintains a high hold rate. The units that DO survive wave 4 all pass — suggesting they're the well-formed tail of earlier waves, not new problems.

### Held units by layer

| Layer  | Wave 2 held | Wave 3 held | Total | % of layer units held |
|--------|-------------|-------------|-------|-----------------------|
| bff    | 4           | 2           | 6     | ~18%                  |
| kmp    | 5           | 6           | 11    | ~35%                  |
| cmp    | 0           | 2           | 2     | ~20%                  |
| native | 1           | 0           | 1     | ~14%                  |

**KMP has the highest gate failure rate at ~35%.** This is significant — KMP units represent the shared business logic layer (Kotlin Multiplatform), which is architecturally the most complex layer in the Hoopla codebase.

### All 21 held units have `verdict: unknown`
This is a major observability gap. The gate ran, decided GATE_FAIL, but recorded no verdict explanation. Without knowing WHY a unit failed, the human reviewer is starting from zero.

### Recommendations
1. **Require verdict explanations**: Every GATE_FAIL must output a `verdict.md` (or equivalent) explaining what failed — missing tests, insufficient coverage, path structure violations, etc. The current fallback (`_read_gate_verdict` helper per commit `91cdb17`) should be made mandatory.
2. **Layer-specific gate tuning**: KMP units likely need different quality criteria than BFF. If the gate is checking for path structure compliance, KMP's `shared/src/commonMain/kotlin/` convention may be tripping rules designed for simpler BFF structure.
3. **Investigate GATE_PASS_WITH_WARNING**: Waves 2–3 had several units pass with warnings (e.g., `01-LOGIN_009-kmp`, `02-HOME_005-bff`, `05-HOOPLA_001-bff`). Track warning reasons — if the same warning recurs, it signals a systematic spec or routing issue that should be fixed at the source.

---

## Pattern 3: File Path Routing Gaps

### Evidence
Multiple warnings during implementation and testing stages:

```
Unknown path structure (layer=bff), deploying as-is: project/test/01-LOGIN_008-bff/...
Unknown path structure (layer=kmp), deploying as-is: project/test/01-LOGIN_014-kmp/...
Unknown path structure (layer=kmp), deploying as-is: project/test/10-GRID_BROWSE_003-kmp/...
Unknown path structure (layer=kmp), deploying as-is: biiometric/BiometricEnrollmentState.kt
Correcting root-level .kt file: browse-context.kt → shared/src/commonMain/kotlin/browse-context.kt
Correcting root-level .kt file: SecureStorage.kt → shared/src/commonMain/kotlin/SecureStorage.kt
```

### Analysis
Three distinct sub-problems:

1. **Test file routing unknown**: Test files for BFF and KMP layers hit "Unknown path structure" and get deployed as-is. The router knows `impl/` paths but not `test/` paths for all layers. (Fix in commit `d3afb11` may have partially addressed this.)

2. **Root-level .kt file misplacement**: The implementation agent generates Kotlin files at the repo root instead of under `shared/src/commonMain/kotlin/`. The pipeline auto-corrects this, but it's a symptom — the implementation agent's prompt or scaffolding doesn't enforce KMP path conventions.

3. **Typo in generated path**: `biiometric/` (double-i) in `01-LOGIN_006-kmp` — the agent generated a misspelled package name. This will cause compile failures downstream.

### Recommendations
1. **Expand the path router** to handle `test/` directories for all layers — BFF test files should map to the BFF test source set, KMP test files to `shared/src/commonTest/kotlin/`.
2. **Add path validation to the implementation agent prompt**: Enforce that KMP files must be under `shared/src/commonMain/kotlin/` (or `commonTest`). Reject or flag root-level .kt files before commit.
3. **Add a spell-check/convention-check** for package paths: catch `biiometric` vs `biometric` before it becomes a GATE_FAIL.

---

## Pattern 4: Rigid Serial Stage Execution

### Observation
Every unit goes through: `implementation → testing → quality_gate → human_review`. Each wave runs all units through a stage before moving to the next stage. The timing data shows:

| Stage          | Avg duration | Variance |
|----------------|-------------|----------|
| Implementation | ~71-73s     | Very low |
| Testing        | ~70-72s     | Very low |
| Quality Gate   | ~27-72s     | High     |

Implementation and testing have suspiciously uniform durations (~70s), suggesting they're hitting a timeout or rate limit rather than varying based on unit complexity. Quality gate durations vary from 22s to 72s — this is the only stage doing genuinely variable work.

### Impact
- Wave 3 took ~2h10m for 41 units across 3 stages (sequential within stage)
- Total pipeline runtime: waves 0–4 took ~5h50m (16:24 → 22:10)
- At this rate, processing all 293 units would take ~25+ hours

### Recommendations
1. **Investigate the ~70s implementation/testing floor**: Is this a per-unit timeout, an API rate limit, or actual processing time? If it's a timeout/limit, parallelizing within a stage would help.
2. **Pipeline within a wave**: Allow units that pass implementation to start testing immediately rather than waiting for the entire wave to finish implementation. This would overlap stages and cut wave time significantly.
3. **Parallel quality gates**: Quality gate is pure evaluation (no side effects). Run all quality gates concurrently instead of sequentially.

---

## Pattern 5: Wave Progression Logic Starts Waves Prematurely

### Evidence
- Wave 4 quality_gate failures started at 22:09:33
- Wave 5 implementation entries started at 22:10:14 — **41 seconds later**
- Wave 5 then failed because the server was down
- Waves 6 and 7 were "run" immediately after (22:10:15 → 22:10:23) but had 0 units to process

### Problem
The wave runner doesn't check for infrastructure health between waves. It also doesn't distinguish between "wave completed with some failures" vs "wave collapsed due to infrastructure failure." The former is fine to continue from; the latter should halt the runner.

### Recommendation
Add an **infrastructure health gate** between waves. Before starting wave N+1:
- Verify llama-server is responsive
- Check that wave N's failure mode was code-quality (GATE_FAIL) not infrastructure (connection refused)
- If infrastructure failure, pause and alert rather than burning through remaining waves

---

## Pattern 6: human_review Stage is Ceremonial

### Evidence
Every wave hits `human_review` stage, every unit gets "no agent for 'human_review', skip", then auto-advance runs separately. This means:
- 293 units × 1 skip event = 293 no-op stage transitions logged
- Auto-advance runs as a separate pass after the skip

### Recommendation
Merge the auto-advance decision into the quality_gate → human_review transition. If `GATE_PASS`, advance immediately. If `GATE_FAIL`, hold for review. The current two-step (skip + auto-advance) adds latency and log noise without providing value.

---

## Pattern 7: Feature Domain Concentration Risk

### Observation
LOGIN units dominate waves 0–4 (18 unique LOGIN features × up to 4 layers each = 72 units). LOGIN alone accounts for ~25% of all work units. Meanwhile:
- AUDIOBOOK: only 2 units completed (wave 2–3 BFF), KMP/CMP not started
- MUSIC: only 1 unit completed (wave 2 BFF)
- TITLE: only 1 unit completed (wave 2 BFF), 12+ units pending

The pipeline's wave ordering front-loads LOGIN and MAIN_CONTAINER while deferring content-type features (AUDIOBOOK, MUSIC, TITLE) to later waves that never ran.

### Risk
If the pipeline consistently crashes around wave 4, the content-type features will never get processed. The wave ordering should consider **feature coverage breadth**, not just dependency depth.

### Recommendation
Consider interleaving a "canary" unit from each feature domain into earlier waves. If LOGIN-001-bff is wave 0, put AUDIOBOOK-001-bff and MUSIC-001-bff in wave 1 rather than wave 2+. This ensures at least one unit per feature domain completes even if later waves fail.

---

## Summary: Priority-Ordered Improvements

| # | Pattern | Impact | Effort | Priority |
|---|---------|--------|--------|----------|
| 1 | llama-server crash + no retry | Blocked 73% of units | Medium | **P0** |
| 2 | No verdict explanations on GATE_FAIL | 21 units need blind manual review | Low | **P1** |
| 3 | File path routing gaps (test dirs, root .kt) | GATE_FAIL for otherwise valid code | Medium | **P1** |
| 4 | No inter-wave health check | Cascading waste across waves 5-7 | Low | **P1** |
| 5 | KMP layer gate tuning | 35% hold rate vs 14-18% for others | Medium | **P2** |
| 6 | Serial stage execution within waves | ~25h projected for full run | High | **P2** |
| 7 | Feature domain concentration in late waves | Content features never processed | Low | **P2** |
| 8 | Ceremonial human_review skip step | Log noise, minor latency | Low | **P3** |

---

## Appendix: Key Metrics

- **Effective throughput**: 78 / 293 = 26.6%
- **Infrastructure-caused failures**: 13 (wave 4) + all waves 5-7 = ~187 units blocked
- **Genuine quality failures**: 21 units (GATE_FAIL at auto-advance)
- **Total runtime**: ~5h50m (16:24:17 → 22:10:23)
- **Avg time per completed unit (all stages)**: ~4.5 min
- **Server crash point**: ~5h30m into continuous operation

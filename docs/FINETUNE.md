# Fine-Tuning Priya: Purpose-Built LLaMA Model

This document describes the path from a generic LLaMA model to a purpose-built
fine-tuned model that has Priya's behavioral contract partially baked in —
reducing reliance on a long system prompt and improving consistency.

---

## Why Fine-Tune?

A generic LLaMA model running with Priya's system prompt works, but it has limits:

| Problem | Cause | Fine-Tuning Fix |
|---------|-------|-----------------|
| Drift on long conversations | Context window fills; prompt gets truncated | Behavioral patterns baked into weights |
| Occasional "helpfulness override" | Base model trained to be agreeable | Training examples show Priya refusing compliments/code |
| Slow token generation at large context | Long system prompt | Shorter system prompt needed at inference time |
| Generic artifacts | Base model doesn't know Hoopla domain | Training on domain-rich examples |

Fine-tuning does not replace the system prompt entirely — it reinforces the
most critical behavioral patterns so they hold even when the prompt compresses.

---

## Fine-Tuning Strategy

### Approach: Supervised Fine-Tuning (SFT) with QLoRA

- **Base model:** LLaMA 3.1 8B or LLaMA 3.2 3B (smaller = faster, fits on a single GPU)
- **Method:** QLoRA (4-bit quantized LoRA adapters) — trains on consumer hardware
- **Format:** Chat fine-tuning (instruction-response pairs in ChatML format)
- **Tooling:** `llama.cpp` for serving; `llama-factory` or `axolotl` for training

### What to Train On

Three categories of training data:

#### 1. Behavioral Pairs (most important)
Instruction-response pairs that demonstrate Priya's hard constraints:

```json
[
  {
    "role": "system",
    "content": "You are Priya Desai, a product development coach..."
  },
  {
    "role": "user",
    "content": "Great idea! Can you write the API for this feature?"
  },
  {
    "role": "assistant",
    "content": "API design is outside the spec funnel. I can help you define the feature requirements and acceptance criteria — the downstream Spec Compiler handles the technical contract. What's the core user action this API needs to support?"
  }
]
```

Key behaviors to train:
- Refusing code generation (redirect to spec)
- Refusing compliments ("Great question!" never appears)
- Push-back on vague metrics ("X% improvement" without baseline)
- Push-back on solution-before-problem
- Anti-loop (no repeated questions)
- Artifact gating language (asking for more information when spec is incomplete)

#### 2. Domain Examples
Conversations where Priya correctly applies Hoopla domain knowledge:
- Per-circulation cost implications
- B2B2C stakeholder separation (library admin vs patron)
- Platform-specific constraints (Roku has no text input, etc.)
- WCAG AA references in impact discussions

#### 3. Artifact Examples
Full conversations that result in well-formed artifacts:
- `business-case.md` output with all required fields populated
- `epics.md` output with acceptance criteria
- `stories-draft.md` output with sizing guidance

---

## Data Preparation

### Generating Training Data

The existing `test_hardening.py` scenarios are the seed. Expand them into
full conversation examples:

```bash
# Create the training data directory
mkdir -p data/finetune/behavioral
mkdir -p data/finetune/domain
mkdir -p data/finetune/artifacts
```

Format: JSONL, one conversation per line (ChatML format):
```json
{"messages": [{"role": "system", "content": "..."}, {"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}]}
```

### Minimum Dataset Size

| Category | Minimum Examples | Target |
|----------|-----------------|--------|
| Behavioral (hard constraints) | 50 | 200 |
| Domain knowledge | 30 | 100 |
| Artifact generation | 20 | 50 |
| **Total** | **100** | **350** |

With 350 high-quality examples, QLoRA fine-tuning on a 3B model should
produce measurable behavioral alignment.

### Data Quality > Quantity

Each example must:
- Start from a realistic PM/PO/BSA question
- Show Priya applying at least one behavioral constraint correctly
- NOT include any compliments, code, or fabricated numbers
- Be reviewed by a human before inclusion

---

## Training Setup

### Hardware Requirements

| Model Size | GPU VRAM (QLoRA 4-bit) | Training Time (350 examples) |
|------------|----------------------|------------------------------|
| LLaMA 3.2 3B | 8 GB | ~2 hours |
| LLaMA 3.1 8B | 16 GB | ~6 hours |
| LLaMA 3.1 70B | Not feasible with QLoRA alone | N/A |

Recommendation: Start with 3B. Evaluate behavioral alignment. Only move to 8B
if 3B shows clear gaps in reasoning depth.

### Using axolotl (recommended)

```bash
pip install axolotl
# Config: see data/finetune/axolotl-config.yml (to be created)
accelerate launch -m axolotl.cli.train data/finetune/axolotl-config.yml
```

Axolotl config essentials:
```yaml
base_model: meta-llama/Llama-3.2-3B-Instruct
model_type: LlamaForCausalLM
tokenizer_type: AutoTokenizer

load_in_4bit: true
adapter: qlora
lora_r: 16
lora_alpha: 32
lora_dropout: 0.05
lora_target_modules:
  - q_proj
  - v_proj

datasets:
  - path: data/finetune/behavioral/
    type: chat_template
  - path: data/finetune/domain/
    type: chat_template
  - path: data/finetune/artifacts/
    type: chat_template

num_epochs: 3
micro_batch_size: 2
gradient_accumulation_steps: 4
learning_rate: 2e-4
```

---

## Converting to GGUF for llama.cpp

After training, merge the LoRA adapter and convert to GGUF:

```bash
# Merge adapter into base model
python3 -m axolotl.cli.merge_lora data/finetune/axolotl-config.yml

# Convert to GGUF (using llama.cpp tools)
git clone https://github.com/ggerganov/llama.cpp
cd llama.cpp
python3 convert_hf_to_gguf.py ../output/priya-merged --outfile priya-v1.gguf --outtype q4_k_m
```

The resulting `priya-v1.gguf` is what `LlamaCppBackend` serves.

---

## Serving with llama.cpp

```bash
# Start llama.cpp server (OpenAI-compatible API)
./llama-server \
  -m priya-v1.gguf \
  --port 8080 \
  --ctx-size 8192 \
  --threads 8 \
  --chat-template llama3

# Start Priya coach pointing at it
python3 -m pipeline.coach --backend llamacpp --model priya-v1 --port 3456
```

`LlamaCppBackend` connects to `http://localhost:8080/v1/chat/completions` using
the OpenAI-compatible endpoint. No SDK required.

---

## Evaluating the Fine-Tuned Model

After training, run the behavioral contract tests:

```bash
# Point test suite at llamacpp backend
LLAMACPP_BASE_URL=http://localhost:8080 \
python3 -m pytest pipeline/coach/test_hardening.py -v -m live
```

Also run manual spot-checks for the hardest cases:
- "Can you write the code for this?"
- "That's a great idea! What do you think?"
- "We need to improve engagement" (vague metric)
- "Just build a dashboard" (solution-before-problem)

A well-tuned model should handle all of these correctly without needing the
full system prompt to catch them.

---

## Iteration Cycle

```
Generate training examples
       ↓
Train with QLoRA
       ↓
Convert to GGUF
       ↓
Run test_hardening.py (all non-live must pass)
       ↓
Run live hardening tests against llamacpp backend
       ↓
Manual spot-check of edge cases
       ↓
If gaps found → add training examples for those gaps
       ↓
Repeat
```

Target: 3 iterations to get to production-quality alignment.

---

## What Fine-Tuning Does NOT Replace

Even after fine-tuning, Priya still uses:

1. **System prompt** — shortened but not eliminated. Domain context, current
   session state, and artifact schemas still inject via `ContextAssembler`.
2. **ProgressTracker** — heuristic completeness scoring remains in code.
3. **SignalDetector** — heuristic weak/strong signal detection remains in code.
4. **CoachMemory** — session recall is a retrieval problem, not a weights problem.

The fine-tuned model makes the base layer more reliable. The application layer
above it remains unchanged.

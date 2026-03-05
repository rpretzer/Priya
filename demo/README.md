# Hoopla Digital — Priya (Product Development Coach)

Browser-based chat interface for the Product Development Coach. Streams responses
token-by-token from the Coach server. No build step, no npm, no framework.

---

## What this is

Priya is a product thinking partner tuned to Hoopla Digital's business model,
technical platform, and constraints. She:

- Pushes back on vague problem statements, unmeasured success criteria, and
  solutions presented before the problem is defined.
- Amplifies strong ideas by framing them as quantified problem statements,
  competitive gaps, and falsifiable hypotheses.
- Tracks session completeness across 9 fields and shows progress in real time.
- Generates structured artifacts — business cases, epics, draft user stories —
  when the spec is solid enough.
- Redirects implementation questions to the Spec Compiler (separate tool).

---

## How to run

### Prerequisites

1. A running Coach server (choose a backend):

   **llama.cpp (Phase 1 — preferred):**
   ```bash
   ./llama-server -m priya-v1.gguf --port 8080
   python3 -m pipeline.coach --backend llamacpp --port 3456 --demo-dir demo/
   ```

   **Anthropic API (development):**
   ```bash
   export ANTHROPIC_API_KEY=sk-ant-...
   python3 -m pipeline.coach --backend assisted --port 3456 --demo-dir demo/
   ```

   **Ollama (fallback):**
   ```bash
   ollama serve && ollama pull llama3.1
   python3 -m pipeline.coach --backend ollama --port 3456 --demo-dir demo/
   ```

2. Open `http://localhost:3456/demo` in your browser.

---

## Features

| Feature | Description |
|---------|-------------|
| Session persistence | Session ID stored in `localStorage`; survives page reload |
| Progress bar | Thin strip below header shows spec completeness (0–100%) |
| Missing fields | Chips above the input show what Priya still needs |
| Slash commands | Type `/` for autocomplete; `/help /status /generate /reset` |
| File attachments | Drag-and-drop, paste, or click the paperclip to attach files |
| Image support | Paste screenshots or drag image files; sent to backend as base64 |
| Export | Downloads full conversation as Markdown |
| Reset | Clears server session and starts fresh |
| Backend status | Header shows connected backend name and online/offline indicator |

---

## API endpoints used

| Endpoint | Purpose |
|----------|---------|
| `POST /api/coach` | Send message; returns NDJSON stream of `{type:"token",text}` events |
| `GET /api/coach/commands` | Slash command list for autocomplete |
| `GET /api/coach/status` | Session completeness for progress bar |
| `POST /api/coach/reset` | Clear server-side session state |
| `GET /health` | Backend health for online indicator |

---

## File structure

```
demo/
  index.html    — Single-page app shell (no JS framework)
  style.css     — Dark theme, responsive, zero dependencies
  app.js        — Chat logic, NDJSON streaming, progress bar, attachments
  README.md     — This file
```

---

## Keyboard shortcuts

| Key | Action |
|-----|--------|
| Enter | Send message |
| Shift + Enter | New line in message |
| Tab | Autocomplete slash command |
| Esc | Dismiss command popup |

---

## Demo script (leadership presentation)

**Act 1 — Show push-back behavior (5 min)**

Start with a vague idea:
> "We should add a social reading feature to Hoopla so patrons can share what they're reading."

Priya will ask: who is the user? what problem are we solving? what does success look like?
She will not jump to stories. The progress bar stays low.

**Act 2 — Fill in the gaps (8 min)**

Answer with specifics:
- "22% of patrons aged 18–34 say social discovery would increase their usage — from our Q3 patron survey."
- "New patrons don't know what to borrow first. The catalog is too large."
- "Success is a 12% increase in borrows by new patrons within 60 days."
- "We considered staff picks and an algorithmic feed, but both need more metadata work first."

Watch the progress bar fill. Ask Priya to `/generate` a business case.

**Act 3 — Feature flag (2 min)**

Ask Priya to generate user stories. She will ask about rollout strategy and
kill-switch criteria before writing acceptance criteria. This is by design.

**Act 4 — Export (1 min)**

Click `↓ Export`. Show the downloaded Markdown file. Explain it feeds into
the Spec Compiler → Jira pipeline.

---

## Troubleshooting

**"connecting…" stays forever:**
Check the Coach server is running on port 3456 and `--demo-dir demo/` is set.

**Responses appear all at once (not streaming):**
The server must return `Content-Type: application/x-ndjson`. Check the backend is running.

**Slash command popup doesn't appear:**
The server must respond to `GET /api/coach/commands`. Start the full Coach server, not just the backend.

**Attachments don't seem to do anything:**
The backend must support multimodal input. LlamaCppBackend and AssistedBackend do.
OllamaBackend extracts text only.

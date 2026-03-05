'use strict';

// ============================================================
// app.js — Priya / Hoopla Coach demo frontend
//
// API contract:
//   POST /api/v1/coach        body: {message, session_token, attachments}
//                             response headers: X-Session-Token
//                             response: NDJSON stream of {type,...} objects
//   GET  /api/v1/coach/commands → {commands:[{command,description,usage}]}
//   GET  /api/v1/coach/status?session_token= → {completeness, ready_for_artifacts, missing:[]}
//   POST /api/v1/coach/reset  body: {session_token}
//                             response: {status, session_token}
//   GET  /health              → {backend, ...}
// ============================================================

// ---- Session token (server-minted, persisted across page loads) ----
// Tokens are HMAC-signed by the server. We store whatever the server gives us.
// On first visit (no stored token), we send null and the server mints a new one.
const _SESSION_KEY = 'priya_session_token';

function getSessionToken() {
  return localStorage.getItem(_SESSION_KEY) || null;
}

function setSessionToken(token) {
  if (token) localStorage.setItem(_SESSION_KEY, token);
}

function clearSessionToken() {
  localStorage.removeItem(_SESSION_KEY);
}

// ---- Module-level state ----
let sessionToken = getSessionToken(); // may be null on first visit
let commands = [];          // slash-command list from /api/coach/commands
let pendingFiles = [];      // attachments staged for the next send
let isStreaming = false;    // true while an LLC response is in-flight
let autocompleteIndex = -1; // keyboard cursor inside the command popup

// ============================================================
// Init
// ============================================================
async function init() {
  await Promise.all([fetchHealth(), fetchCommands()]);
  setupInput();
  setupDragDrop();
  setupPaste();
  // Fetch status to restore progress bar if session already existed
  fetchStatus();
}

// ---- Health / online state ----
async function fetchHealth() {
  try {
    const r = await fetch('/api/health');
    if (r.ok) {
      const d = await r.json();
      setOnline(true, d.backend || 'connected');
    } else {
      setOnline(false, 'offline');
    }
  } catch {
    setOnline(false, 'offline');
  }
}

function setOnline(online, label) {
  const dot = document.getElementById('status-dot');
  const lbl = document.getElementById('status-label');
  const sub = document.getElementById('backend-label');
  dot.className = 'status-dot' + (online ? ' online' : '');
  lbl.textContent = label;
  if (online && sub) sub.textContent = label;
}

// ---- Command list ----
async function fetchCommands() {
  try {
    const r = await fetch('/api/coach/commands');
    if (r.ok) {
      const d = await r.json();
      commands = d.commands || [];
    }
  } catch { /* non-fatal */ }
}

// ============================================================
// Status / progress bar
// ============================================================
async function fetchStatus() {
  try {
    const params = sessionToken ? `?session_token=${encodeURIComponent(sessionToken)}` : '';
    const r = await fetch(`/api/v1/coach/status${params}`);
    if (!r.ok) return;
    const d = await r.json();
    // Server may return an updated token even on status calls
    if (d.session_token) { sessionToken = d.session_token; setSessionToken(sessionToken); }
    renderStatus(d);
  } catch { /* non-fatal */ }
}

/**
 * Render the thin progress bar and missing-field chips.
 *
 * @param {object} status  { completeness: 0–1, ready_for_artifacts: bool, missing: string[] }
 */
function renderStatus(status) {
  if (!status) return;

  const completeness = status.completeness ?? 0;
  const pct = Math.round(completeness * 100);
  const missing = status.missing || [];

  // Thin progress bar in the header strip
  const fill = document.getElementById('progress-bar-fill');
  if (fill) fill.style.width = pct + '%';

  // Missing-field chips below the input
  const chipsEl = document.getElementById('progress-missing-chips');
  if (chipsEl) {
    if (missing.length > 0) {
      chipsEl.innerHTML =
        '<span class="progress-chip-label">Needs:</span>' +
        missing.map((f) => `<span class="progress-chip">${escapeHtml(f)}</span>`).join('');
      chipsEl.style.display = 'flex';
    } else {
      chipsEl.innerHTML = '';
      chipsEl.style.display = 'none';
    }
  }
}

// ============================================================
// Input — keyboard handling, auto-resize, command autocomplete
// ============================================================
function setupInput() {
  const input = document.getElementById('input');

  input.addEventListener('keydown', (e) => {
    const ac = document.getElementById('autocomplete');
    const acVisible = ac.classList.contains('visible');

    if (e.key === 'Enter' && !e.shiftKey) {
      if (acVisible) {
        // If an autocomplete item is keyboard-selected, fill it
        const sel = ac.querySelector('.autocomplete-item.selected');
        if (sel) {
          input.value = sel.dataset.cmd + ' ';
          hideAutocomplete();
          e.preventDefault();
          return;
        }
      }
      e.preventDefault();
      submitMessage();
      return;
    }

    if (e.key === 'Escape') {
      hideAutocomplete();
      return;
    }

    if (e.key === 'ArrowDown') { navigateAutocomplete(1); e.preventDefault(); return; }
    if (e.key === 'ArrowUp')   { navigateAutocomplete(-1); e.preventDefault(); return; }
  });

  input.addEventListener('input', () => {
    autoResize(input);
    const val = input.value;
    if (val.startsWith('/')) {
      showAutocomplete(val);
    } else {
      hideAutocomplete();
    }
  });
}

function autoResize(el) {
  el.style.height = 'auto';
  el.style.height = Math.min(el.scrollHeight, 160) + 'px';
}

// ---- Command autocomplete popup ----
function showAutocomplete(query) {
  const ac = document.getElementById('autocomplete');
  const prefix = query.split(' ')[0].toLowerCase();
  const filtered = commands.filter((c) => c.command.startsWith(prefix));
  if (!filtered.length) { hideAutocomplete(); return; }

  ac.innerHTML = filtered.map((c) =>
    `<div class="autocomplete-item" data-cmd="${escapeHtml(c.command)}"
          onclick="selectCmd('${escapeHtml(c.command)}')">
       <span class="autocomplete-cmd">${escapeHtml(c.command)}</span>
       <span class="autocomplete-desc">${escapeHtml(c.description || '')}</span>
     </div>`
  ).join('');
  ac.classList.add('visible');
  autocompleteIndex = -1;
}

function hideAutocomplete() {
  const ac = document.getElementById('autocomplete');
  ac.classList.remove('visible');
  autocompleteIndex = -1;
}

function navigateAutocomplete(dir) {
  const items = document.querySelectorAll('.autocomplete-item');
  if (!items.length) return;
  items.forEach((i) => i.classList.remove('selected'));
  autocompleteIndex = (autocompleteIndex + dir + items.length) % items.length;
  items[autocompleteIndex].classList.add('selected');
}

function selectCmd(cmd) {
  const input = document.getElementById('input');
  input.value = cmd + ' ';
  hideAutocomplete();
  input.focus();
}

// ============================================================
// File handling — drag-drop, paste, pending-file list
// ============================================================
function setupDragDrop() {
  const area = document.getElementById('input-area');
  area.addEventListener('dragover', (e) => {
    e.preventDefault();
    area.classList.add('drag-over');
  });
  area.addEventListener('dragleave', () => area.classList.remove('drag-over'));
  area.addEventListener('drop', async (e) => {
    e.preventDefault();
    area.classList.remove('drag-over');
    const files = Array.from(e.dataTransfer.files);
    for (const f of files) await stageFile(f);
  });
}

function setupPaste() {
  // Allow pasting files/images anywhere in the page
  document.addEventListener('paste', async (e) => {
    const items = Array.from(e.clipboardData?.items || []);
    const fileItems = items.filter((i) => i.kind === 'file');
    for (const item of fileItems) {
      const f = item.getAsFile();
      if (f) await stageFile(f);
    }
  });
}

/**
 * Read a File object into base64 and add it to pendingFiles.
 */
async function stageFile(file) {
  return new Promise((resolve) => {
    const reader = new FileReader();
    reader.onload = () => {
      // result is "data:<mime>;base64,<data>"
      const b64 = reader.result.split(',')[1];
      pendingFiles.push({
        filename: file.name,
        content_type: file.type || 'application/octet-stream',
        data: b64,
      });
      renderPendingFiles();
      resolve();
    };
    reader.readAsDataURL(file);
  });
}

function renderPendingFiles() {
  const container = document.getElementById('pending-files');
  container.innerHTML = pendingFiles.map((f, i) =>
    `<div class="file-chip">
       <svg viewBox="0 0 16 16" fill="currentColor" width="12" height="12" aria-hidden="true">
         <path d="M4 0h8l4 4v11a1 1 0 01-1 1H1a1 1 0 01-1-1V1a1 1 0 011-1h3zm8 0v4h4l-4-4z"/>
       </svg>
       <span>${escapeHtml(f.filename)}</span>
       <span class="remove" onclick="removeFile(${i})" title="Remove attachment" aria-label="Remove ${escapeHtml(f.filename)}">×</span>
     </div>`
  ).join('');
}

function removeFile(i) {
  pendingFiles.splice(i, 1);
  renderPendingFiles();
}

// ============================================================
// Core send function
// ============================================================

/**
 * Called by the send button and Enter-key handler.
 * Reads the textarea, stages any pending attachments, sends to /api/coach,
 * streams the NDJSON response, and updates the progress bar on completion.
 */
async function submitMessage() {
  if (isStreaming) return;

  const input = document.getElementById('input');
  const text = input.value.trim();
  if (!text && !pendingFiles.length) return;

  // Dismiss the welcome splash on first real send
  const welcome = document.getElementById('welcome');
  if (welcome) welcome.remove();

  // Snapshot attachments and clear pending list before the async call
  const attachments = pendingFiles.length ? [...pendingFiles] : [];
  pendingFiles = [];
  renderPendingFiles();

  // Render the user bubble immediately
  appendMessage('user', text, attachments.map((a) => a.filename));

  // Clear textarea
  input.value = '';
  autoResize(input);
  hideAutocomplete();

  // Create the streaming assistant bubble
  const bubbleId = 'msg-' + Date.now();
  appendStreamingBubble(bubbleId);
  setStreaming(true);

  await sendToCoach(text, attachments, bubbleId);

  setStreaming(false);
}

/**
 * POST to /api/coach and stream the NDJSON response into the bubble identified
 * by bubbleId. Calls fetchStatus() after {type:"done"}.
 *
 * @param {string}   text        User message text
 * @param {object[]} attachments Array of {filename, content_type, data} objects
 * @param {string}   bubbleId    DOM id of the streaming bubble to update
 */
async function sendToCoach(text, attachments, bubbleId) {
  const body = {
    message: text,
    session_token: sessionToken,
  };
  if (attachments.length) body.attachments = attachments;

  let resp;
  try {
    resp = await fetch('/api/v1/coach', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
  } catch (err) {
    updateBubble(bubbleId, `Connection error: ${escapeHtml(err.message)}`, false);
    return;
  }

  if (!resp.ok) {
    updateBubble(bubbleId, `Server error: ${resp.status} ${resp.statusText}`, false);
    return;
  }

  // Capture server-minted session token from response headers
  const newToken = resp.headers.get('X-Session-Token');
  if (newToken) { sessionToken = newToken; setSessionToken(sessionToken); }

  // Parse NDJSON stream: each line is a complete JSON object
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let lineBuffer = ''; // accumulates incomplete lines across chunks
  let fullText = '';

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      lineBuffer += decoder.decode(value, { stream: true });

      // Split on newlines; last element may be an incomplete line
      const lines = lineBuffer.split('\n');
      lineBuffer = lines.pop(); // keep the (possibly empty) tail

      for (const line of lines) {
        if (!line.trim()) continue; // skip blank separator lines

        let event;
        try {
          event = JSON.parse(line);
        } catch {
          // Malformed line — skip silently
          continue;
        }

        if (event.type === 'token') {
          // Incremental text chunk
          fullText += event.text || '';
          updateBubble(bubbleId, fullText, true /* streaming */);
        } else if (event.type === 'done') {
          // Final event — finalise the bubble and update progress
          updateBubble(bubbleId, fullText, false /* done */);
          fetchStatus(); // async — non-blocking
        } else if (event.type === 'error') {
          const errId = event.error_id ? ` [${event.error_id}]` : '';
          updateBubble(bubbleId, `Something went wrong${errId}. Please try again.`, false);
        }
      }
    }

    // Flush any remaining buffer content after the stream closes
    if (lineBuffer.trim()) {
      try {
        const event = JSON.parse(lineBuffer);
        if (event.type === 'token') fullText += event.text || '';
        if (event.type === 'done' || event.type === 'token') {
          updateBubble(bubbleId, fullText, false);
          fetchStatus();
        }
      } catch { /* ignore */ }
    }
  } catch (err) {
    // ReadableStream read error (network drop, etc.)
    if (fullText) {
      // Keep whatever we received
      updateBubble(bubbleId, fullText, false);
    } else {
      updateBubble(bubbleId, `Stream interrupted: ${escapeHtml(err.message)}`, false);
    }
  }
}

function setStreaming(v) {
  isStreaming = v;
  const btn = document.getElementById('btn-send');
  if (btn) btn.disabled = v;
}

// ============================================================
// Quick-start chips
// ============================================================
function quickStart(text) {
  const input = document.getElementById('input');
  input.value = text;
  submitMessage();
}

// ============================================================
// Message rendering
// ============================================================

/**
 * Append a finalised user or coach bubble to the message list.
 *
 * @param {'user'|'coach'} role
 * @param {string}         text
 * @param {string[]}       filenames  Attachment names to show as chips
 */
function appendMessage(role, text, filenames = []) {
  const container = document.getElementById('messages');
  const div = document.createElement('div');
  div.className = 'message ' + role;

  const chips = filenames.map((f) =>
    `<div class="attachment-chip">
       <svg viewBox="0 0 16 16" fill="currentColor" width="12" height="12" aria-hidden="true">
         <path d="M4 0h8l4 4v11a1 1 0 01-1 1H1a1 1 0 01-1-1V1a1 1 0 011-1h3zm8 0v4h4l-4-4z"/>
       </svg>
       ${escapeHtml(f)}
     </div>`
  ).join('');

  div.innerHTML = `
    <div class="message-meta">${role === 'user' ? 'You' : 'Priya'}</div>
    ${chips}
    <div class="bubble">${renderMarkdown(text)}</div>
  `;
  container.appendChild(div);
  maybeScrollBottom();
}

/**
 * Insert a placeholder coach bubble that shows a blinking cursor while
 * streaming. Its id is used by updateBubble() to fill in tokens.
 */
function appendStreamingBubble(id) {
  const container = document.getElementById('messages');
  const div = document.createElement('div');
  div.className = 'message coach';
  div.id = id;
  div.innerHTML = `
    <div class="message-meta">Priya</div>
    <div class="bubble"><span class="typing-cursor"></span></div>
  `;
  container.appendChild(div);
  maybeScrollBottom();
}

/**
 * Update the content of an existing streaming bubble.
 *
 * @param {string}  id         DOM id of the bubble wrapper
 * @param {string}  text       Full accumulated text so far
 * @param {boolean} streaming  If true, append the blinking cursor
 */
function updateBubble(id, text, streaming) {
  const div = document.getElementById(id);
  if (!div) return;
  const bubble = div.querySelector('.bubble');
  if (!bubble) return;
  bubble.innerHTML =
    renderMarkdown(text) +
    (streaming ? '<span class="typing-cursor"></span>' : '');
  maybeScrollBottom();
}

// ---- Auto-scroll ----
// Only auto-scroll when the user is already near the bottom (within 100px).
// This lets users scroll up to re-read without being snapped back down.
function maybeScrollBottom() {
  const c = document.getElementById('messages');
  if (!c) return;
  const distanceFromBottom = c.scrollHeight - c.scrollTop - c.clientHeight;
  if (distanceFromBottom < 100) {
    c.scrollTop = c.scrollHeight;
  }
}

// ============================================================
// Reset
// ============================================================
async function resetSession() {
  try {
    const r = await fetch('/api/v1/coach/reset', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_token: sessionToken }),
    });
    if (r.ok) {
      const d = await r.json();
      if (d.session_token) { sessionToken = d.session_token; setSessionToken(sessionToken); }
    }
  } catch { /* non-fatal if server is unreachable */ }

  // Clear stored token — server already gave us a new one above
  if (!sessionToken) { clearSessionToken(); sessionToken = null; }

  // Clear local state
  pendingFiles = [];
  renderPendingFiles();

  // Reset the message pane
  const container = document.getElementById('messages');
  container.innerHTML = `
    <div class="welcome" id="welcome">
      <h2>Hi, I'm Priya.</h2>
      <p>I'm your product development coach. Tell me about the feature or problem you're working on — or drop a doc, PRD, or Slack thread and I'll read it.</p>
      <div class="welcome-chips">
        <div class="welcome-chip" onclick="quickStart('I want to build a business case for a new feature.')">Build a business case</div>
        <div class="welcome-chip" onclick="quickStart('We have an idea for a new feature. Can you help me scope it?')">Scope a feature</div>
        <div class="welcome-chip" onclick="quickStart('/help')">See commands</div>
      </div>
    </div>
  `;

  // Reset progress bar and chips
  const fill = document.getElementById('progress-bar-fill');
  if (fill) fill.style.width = '0%';
  const chips = document.getElementById('progress-missing-chips');
  if (chips) { chips.innerHTML = ''; chips.style.display = 'none'; }
}

// ============================================================
// Export
// ============================================================
function exportConversation() {
  const messages = document.querySelectorAll('.message');
  if (!messages.length) return;

  const lines = ['# Priya — Coaching Session Export\n'];
  messages.forEach((msg) => {
    const role = msg.classList.contains('user') ? 'You' : 'Priya';
    const bubble = msg.querySelector('.bubble');
    const text = bubble ? bubble.innerText : '';
    lines.push(`**${role}:**\n${text}\n`);
  });

  const blob = new Blob([lines.join('\n')], { type: 'text/markdown' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `priya-session-${new Date().toISOString().slice(0, 10)}.md`;
  a.click();
  URL.revokeObjectURL(url);
}

// ============================================================
// Markdown renderer (kept verbatim from original)
// ============================================================
function renderMarkdown(text) {
  if (!text) return '';
  let html = escapeHtml(text);
  // Code blocks
  html = html.replace(/```[\w]*\n([\s\S]*?)```/g, (_, c) => `<pre><code>${c}</code></pre>`);
  // Inline code
  html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
  // Bold
  html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  // HR
  html = html.replace(/^---$/gm, '<hr>');
  // Headers
  html = html.replace(/^### (.+)$/gm, '<h3>$1</h3>');
  html = html.replace(/^## (.+)$/gm, '<h2>$1</h2>');
  html = html.replace(/^# (.+)$/gm, '<h1>$1</h1>');
  // Bullets
  html = html.replace(/^[•\-\*] (.+)$/gm, '<li>$1</li>');
  html = html.replace(/(<li>.*<\/li>)/s, '<ul>$1</ul>');
  // Numbered lists
  html = html.replace(/^\d+\. (.+)$/gm, '<li>$1</li>');
  // Paragraphs
  html = html.replace(/\n\n/g, '</p><p>');
  return '<p>' + html + '</p>';
}

// ============================================================
// Utility
// ============================================================
function escapeHtml(text) {
  return (text || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// ============================================================
// Boot
// ============================================================
init();

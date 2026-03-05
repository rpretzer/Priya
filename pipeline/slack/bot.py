"""Hoopla Coach — Slack bot frontend.

A thin adapter that connects Slack events to the Coach HTTP server (/api/coach).
Runs via Socket Mode — no public URL needed, works behind corporate firewalls.

Session model: one Coach session per Slack channel (or DM thread).
The Coach server maintains conversation history; the bot only sends the
current user message each turn.

Setup:
    1. Create a Slack app at https://api.slack.com/apps
    2. Enable Socket Mode and generate an App-Level Token (xapp-...)
    3. Add Bot Token Scopes: app_mentions:read, chat:write, channels:history,
       im:history, im:write, files:read
    4. Subscribe to events: app_mention, message.im
    5. Install to workspace → copy Bot Token (xoxb-...)

Environment variables:
    SLACK_BOT_TOKEN     — xoxb-... (bot OAuth token)
    SLACK_APP_TOKEN     — xapp-... (socket mode app token)
    COACH_SERVER_URL    — http://localhost:3456 (default)

Usage:
    pip install slack-bolt requests
    python3 -m pipeline.slack.bot
    # or:
    python3 pipeline/slack/bot.py
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
import urllib.request
import urllib.error
from typing import Any

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("priya.slack")


# ---------------------------------------------------------------------------
# Coach server client (stdlib only — no requests dependency)
# ---------------------------------------------------------------------------

COACH_SERVER_URL = os.environ.get("COACH_SERVER_URL", "http://localhost:3456")


def _session_id_for(team_id: str, channel_id: str) -> str:
    """Stable session ID from team + channel (deterministic, no state needed)."""
    key = f"{team_id}/{channel_id}"
    return "slack-" + hashlib.sha256(key.encode()).hexdigest()[:16]


def _coach_chat(session_id: str, message: str, attachments: list[dict] | None = None) -> str:
    """Send a message to the coach server, collect full streamed response."""
    url = f"{COACH_SERVER_URL}/api/coach"
    payload = {"message": message, "session_id": session_id}
    if attachments:
        payload["attachments"] = attachments

    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    chunks: list[str] = []
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            for raw_line in resp:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if event.get("type") == "token":
                    chunks.append(event.get("text", ""))
                elif event.get("type") == "done":
                    break
                elif event.get("type") == "error":
                    return f"[Coach error: {event.get('text', 'unknown')}]"
    except urllib.error.URLError as e:
        return f"[Cannot reach coach server at {COACH_SERVER_URL}: {e}]"

    return "".join(chunks).strip()


def _coach_reset(session_id: str) -> None:
    url = f"{COACH_SERVER_URL}/api/coach/reset"
    body = json.dumps({"session_id": session_id}).encode()
    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=10)
    except urllib.error.URLError:
        pass  # best-effort


def _coach_status(session_id: str) -> dict:
    url = f"{COACH_SERVER_URL}/api/coach/status?session_id={session_id}"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            return json.loads(resp.read())
    except (urllib.error.URLError, json.JSONDecodeError):
        return {}


# ---------------------------------------------------------------------------
# Slack message helpers
# ---------------------------------------------------------------------------

def _strip_mention(text: str, bot_user_id: str) -> str:
    """Remove @mention prefix from a message."""
    mention = f"<@{bot_user_id}>"
    return text.replace(mention, "").strip()


def _format_status(status: dict) -> str:
    """Format a /status response into Slack mrkdwn."""
    if not status:
        return "_No active session._"
    pct = int(status.get("completeness", 0) * 100)
    missing = status.get("missing", [])
    ready = status.get("ready_for_artifacts", False)
    bar = "█" * (pct // 10) + "░" * (10 - pct // 10)
    lines = [f"*Session completeness:* `{bar}` {pct}%"]
    if ready:
        lines.append("✅ Ready to generate artifacts — type `/generate`")
    elif missing:
        lines.append(f"*Still need:* {', '.join(f'`{f}`' for f in missing)}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Bot application
# ---------------------------------------------------------------------------

def _make_app():
    """Build and return the Bolt App. Import slack_bolt lazily."""
    try:
        from slack_bolt import App
        from slack_bolt.adapter.socket_mode import SocketModeHandler
    except ImportError:
        log.error(
            "slack-bolt is not installed. Run: pip install slack-bolt"
        )
        sys.exit(1)

    bot_token = os.environ.get("SLACK_BOT_TOKEN", "")
    app_token = os.environ.get("SLACK_APP_TOKEN", "")

    if not bot_token:
        log.error("SLACK_BOT_TOKEN environment variable is not set.")
        sys.exit(1)
    if not app_token:
        log.error("SLACK_APP_TOKEN environment variable is not set.")
        sys.exit(1)

    app = App(token=bot_token)

    # ------------------------------------------------------------------
    # Helper: get bot user ID (cached)
    # ------------------------------------------------------------------
    _bot_user_id: list[str] = []

    def _get_bot_user_id(client: Any) -> str:
        if not _bot_user_id:
            info = client.auth_test()
            _bot_user_id.append(info["user_id"])
        return _bot_user_id[0]

    # ------------------------------------------------------------------
    # Helper: handle a coach turn
    # ------------------------------------------------------------------
    def _handle_turn(client: Any, channel: str, team_id: str, text: str,
                     thread_ts: str | None = None, files: list[dict] | None = None) -> None:
        session_id = _session_id_for(team_id, channel)

        # Check for slash commands within the message
        stripped = text.strip()
        if stripped == "/reset":
            _coach_reset(session_id)
            client.chat_postMessage(
                channel=channel,
                thread_ts=thread_ts,
                text="_Session reset. Start fresh with a new product idea._",
            )
            return
        if stripped == "/status":
            status = _coach_status(session_id)
            client.chat_postMessage(
                channel=channel,
                thread_ts=thread_ts,
                text=_format_status(status),
                mrkdwn=True,
            )
            return

        # Post a placeholder message, then stream into it
        placeholder = client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text="_Priya is thinking…_",
            mrkdwn=True,
        )
        ts = placeholder["ts"]

        # Build attachments list for images/files
        attachments: list[dict] = []
        if files:
            for f in files:
                url = f.get("url_private_download") or f.get("url_private")
                if not url:
                    continue
                # Download file content using the bot token
                headers = {"Authorization": f"Bearer {bot_token}"}
                try:
                    req = urllib.request.Request(url, headers=headers)
                    with urllib.request.urlopen(req, timeout=30) as resp:
                        content_type = resp.headers.get("Content-Type", "application/octet-stream")
                        raw = resp.read()
                except urllib.error.URLError:
                    continue

                if content_type.startswith("image/"):
                    import base64
                    attachments.append({
                        "filename": f.get("name", "image"),
                        "data": base64.b64encode(raw).decode(),
                        "content_type": content_type,
                    })
                else:
                    # Text file — send as text content
                    try:
                        text_content = raw.decode("utf-8", errors="replace")[:50_000]
                    except Exception:
                        text_content = "[binary file]"
                    attachments.append({
                        "filename": f.get("name", "file"),
                        "content": text_content,
                        "content_type": content_type,
                    })

        response = _coach_chat(session_id, stripped, attachments or None)

        # Slack blocks for markdown don't support all markdown — use mrkdwn text
        # Convert minimal markdown: **bold** → *bold*, # heading → *heading*
        slack_text = (response
                      .replace("**", "*")
                      .replace("```", "\n```\n"))

        # Slack message length limit is ~4000 chars per block; split if needed
        MAX_LEN = 3800
        if len(slack_text) <= MAX_LEN:
            client.chat_update(channel=channel, ts=ts, text=slack_text, mrkdwn=True)
        else:
            # Update placeholder, post continuation as follow-up
            client.chat_update(channel=channel, ts=ts, text=slack_text[:MAX_LEN] + "…", mrkdwn=True)
            remainder = slack_text[MAX_LEN:]
            while remainder:
                client.chat_postMessage(
                    channel=channel,
                    thread_ts=thread_ts or ts,
                    text=remainder[:MAX_LEN],
                    mrkdwn=True,
                )
                remainder = remainder[MAX_LEN:]

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    @app.event("app_mention")
    def handle_mention(event: dict, client: Any, say: Any) -> None:
        """Handle @priya mentions in channels."""
        bot_user_id = _get_bot_user_id(client)
        text = _strip_mention(event.get("text", ""), bot_user_id)
        if not text:
            return

        channel = event["channel"]
        team_id = event.get("team", "default")
        thread_ts = event.get("thread_ts") or event.get("ts")
        files = event.get("files", [])

        log.info("Mention in %s: %r", channel, text[:80])
        _handle_turn(client, channel, team_id, text, thread_ts=thread_ts, files=files)

    @app.event("message")
    def handle_dm(event: dict, client: Any) -> None:
        """Handle direct messages."""
        # Only respond to DMs (channel_type == 'im'), ignore bot messages
        if event.get("channel_type") != "im":
            return
        if event.get("subtype") in ("bot_message", "message_changed", "message_deleted"):
            return
        if event.get("bot_id"):
            return

        text = event.get("text", "").strip()
        files = event.get("files", [])
        if not text and not files:
            return

        channel = event["channel"]
        team_id = event.get("team", "default")

        log.info("DM from %s: %r", event.get("user"), text[:80])
        _handle_turn(client, channel, team_id, text, files=files)

    return app, SocketModeHandler


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    app, SocketModeHandler = _make_app()
    app_token = os.environ["SLACK_APP_TOKEN"]

    log.info("Starting Priya Slack bot (Socket Mode)…")
    log.info("Coach server: %s", COACH_SERVER_URL)

    handler = SocketModeHandler(app, app_token)
    handler.start()


if __name__ == "__main__":
    main()

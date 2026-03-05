"""ModelServer — manages the llama.cpp server process lifecycle.

Starts, monitors, and restarts the llama-server process. Provides health
checks that LlamaCppBackend polls before sending requests.

Usage (programmatic):
    server = ModelServer(model_path="/models/llama3.gguf", port=8080)
    handle = server.start()
    if server.health():
        # ready for requests
    server.stop()

Usage (CLI, for testing):
    python3 -m pipeline.coach.model_server \\
        --model /models/llama3.gguf --port 8080 --ctx-size 4096

Environment variables:
    LLAMACPP_SERVER_BIN   Path to llama-server binary (default: llama-server)
    LLAMACPP_BASE_URL     Server base URL (default: http://localhost:8080)
    LLAMACPP_MODEL        Model path (required if not passed as arg)
"""
from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class ServerConfig:
    """Configuration for the llama.cpp server process."""
    model_path: str
    port: int = 8080
    host: str = "0.0.0.0"
    ctx_size: int = 4096
    gpu_layers: int = 0          # 0 = CPU-only
    threads: int = 0             # 0 = auto-detect
    chat_template: str = ""      # e.g. "llama3", "chatml" — empty = model default
    extra_args: list[str] = field(default_factory=list)
    server_bin: str = ""         # path to llama-server binary

    def __post_init__(self):
        if not self.server_bin:
            self.server_bin = os.environ.get("LLAMACPP_SERVER_BIN", "llama-server")


@dataclass
class ServerHandle:
    """Live handle returned by ModelServer.start()."""
    pid: int
    port: int
    base_url: str
    model_path: str
    started_at: float = field(default_factory=time.monotonic)

    @property
    def uptime_seconds(self) -> float:
        return time.monotonic() - self.started_at


class ModelServerError(RuntimeError):
    """Raised when the server fails to start or crashes unrecoverably."""


class ModelServer:
    """Manages the llama.cpp server process lifecycle.

    Responsibilities:
    - Start the server with the configured model and parameters
    - Poll health endpoint until the server is ready
    - Restart automatically on crash (up to max_restarts)
    - Provide health() for LlamaCppBackend to poll before requests
    - Log model loading time and memory usage

    This class does NOT know about CoachEngine, ProgressTracker, or any
    coaching logic. It is purely infrastructure.
    """

    # How long to wait for the server to become healthy after starting
    STARTUP_TIMEOUT_S = 120
    # Interval between health poll attempts during startup
    STARTUP_POLL_INTERVAL_S = 1.0
    # Maximum automatic restart attempts before giving up
    MAX_RESTARTS = 3
    # Delay between restart attempts
    RESTART_DELAY_S = 3.0

    def __init__(self, config: ServerConfig):
        self._config = config
        self._process: Optional[subprocess.Popen] = None
        self._handle: Optional[ServerHandle] = None
        self._restart_count = 0
        self._base_url = f"http://localhost:{config.port}"

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def start(self) -> ServerHandle:
        """Start the llama.cpp server. Block until healthy or timeout.

        Returns a ServerHandle on success. Raises ModelServerError on failure.
        """
        if self._process and self._process.poll() is None:
            logger.info("ModelServer: already running (pid=%d)", self._process.pid)
            return self._handle

        logger.info(
            "ModelServer: starting llama-server — model=%s port=%d ctx=%d gpu_layers=%d",
            self._config.model_path,
            self._config.port,
            self._config.ctx_size,
            self._config.gpu_layers,
        )
        t_start = time.monotonic()
        self._process = self._spawn()
        self._wait_for_healthy()
        load_time = time.monotonic() - t_start

        logger.info(
            "ModelServer: ready — pid=%d load_time=%.1fs",
            self._process.pid,
            load_time,
        )

        self._handle = ServerHandle(
            pid=self._process.pid,
            port=self._config.port,
            base_url=self._base_url,
            model_path=self._config.model_path,
        )
        return self._handle

    def stop(self) -> None:
        """Gracefully stop the server process."""
        if not self._process:
            return
        pid = self._process.pid
        logger.info("ModelServer: stopping pid=%d", pid)
        try:
            self._process.send_signal(signal.SIGTERM)
            self._process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            logger.warning("ModelServer: SIGTERM timed out, sending SIGKILL to pid=%d", pid)
            self._process.kill()
            self._process.wait()
        except ProcessLookupError:
            pass  # already dead
        finally:
            self._process = None
            self._handle = None
            self._restart_count = 0
        logger.info("ModelServer: stopped (was pid=%d)", pid)

    def health(self) -> bool:
        """Return True if the server is reachable and responding to health checks."""
        if self._process and self._process.poll() is not None:
            # Process has exited — attempt restart
            logger.warning("ModelServer: process exited unexpectedly, attempting restart")
            self._attempt_restart()
        return self._ping_health()

    def ensure_running(self) -> None:
        """Start the server if not already running. No-op if healthy."""
        if not self.health():
            self.start()

    @property
    def handle(self) -> Optional[ServerHandle]:
        return self._handle

    @property
    def base_url(self) -> str:
        return self._base_url

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _spawn(self) -> subprocess.Popen:
        """Build the command and spawn the subprocess."""
        cmd = [
            self._config.server_bin,
            "--model", self._config.model_path,
            "--port", str(self._config.port),
            "--host", self._config.host,
            "--ctx-size", str(self._config.ctx_size),
            "--n-gpu-layers", str(self._config.gpu_layers),
        ]
        if self._config.threads > 0:
            cmd += ["--threads", str(self._config.threads)]
        if self._config.chat_template:
            cmd += ["--chat-template", self._config.chat_template]
        cmd += self._config.extra_args

        logger.debug("ModelServer: cmd=%s", " ".join(cmd))

        # stdout/stderr piped so we can log model loading output without
        # polluting the coach server stdout
        return subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )

    def _wait_for_healthy(self) -> None:
        """Poll health endpoint until ready or timeout. Raises on failure."""
        deadline = time.monotonic() + self.STARTUP_TIMEOUT_S
        last_log = 0.0

        while time.monotonic() < deadline:
            # Check if the process crashed before becoming healthy
            if self._process.poll() is not None:
                stdout = ""
                try:
                    stdout = self._process.stdout.read()
                except Exception:
                    pass
                raise ModelServerError(
                    f"llama-server exited before becoming healthy "
                    f"(exit={self._process.returncode}). Output:\n{stdout[:2000]}"
                )

            if self._ping_health():
                return

            now = time.monotonic()
            if now - last_log >= 10:
                elapsed = now - (deadline - self.STARTUP_TIMEOUT_S)
                logger.info("ModelServer: waiting for server to become healthy (%.0fs elapsed)...", elapsed)
                last_log = now

            time.sleep(self.STARTUP_POLL_INTERVAL_S)

        raise ModelServerError(
            f"llama-server did not become healthy within {self.STARTUP_TIMEOUT_S}s"
        )

    def _ping_health(self) -> bool:
        """Single health probe. Returns True if server responds 200."""
        for path in ("/health", "/v1/models"):
            try:
                req = urllib.request.Request(
                    f"{self._base_url}{path}", method="GET"
                )
                with urllib.request.urlopen(req, timeout=3) as resp:
                    if resp.status == 200:
                        return True
            except Exception:
                continue
        return False

    def _attempt_restart(self) -> None:
        """Try to restart after an unexpected crash."""
        if self._restart_count >= self.MAX_RESTARTS:
            raise ModelServerError(
                f"llama-server crashed {self._restart_count} times — giving up"
            )
        self._restart_count += 1
        logger.warning(
            "ModelServer: restarting (attempt %d/%d) after %.1fs delay",
            self._restart_count,
            self.MAX_RESTARTS,
            self.RESTART_DELAY_S,
        )
        time.sleep(self.RESTART_DELAY_S)
        self._process = self._spawn()
        self._wait_for_healthy()
        self._handle = ServerHandle(
            pid=self._process.pid,
            port=self._config.port,
            base_url=self._base_url,
            model_path=self._config.model_path,
        )
        logger.info("ModelServer: restart succeeded (pid=%d)", self._process.pid)


# ------------------------------------------------------------------
# CLI shim for manual testing
# ------------------------------------------------------------------

def _cli() -> None:
    import argparse
    p = argparse.ArgumentParser(
        prog="python3 -m pipeline.coach.model_server",
        description="Start and manage a llama.cpp server process",
    )
    p.add_argument("--model", required=True, help="Path to GGUF model file")
    p.add_argument("--port", type=int, default=8080)
    p.add_argument("--ctx-size", type=int, default=4096, dest="ctx_size")
    p.add_argument("--gpu-layers", type=int, default=0, dest="gpu_layers")
    p.add_argument("--threads", type=int, default=0)
    p.add_argument("--chat-template", default="", dest="chat_template")
    p.add_argument("--server-bin", default="", dest="server_bin",
                   help="Path to llama-server binary (default: llama-server from PATH)")
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    config = ServerConfig(
        model_path=args.model,
        port=args.port,
        ctx_size=args.ctx_size,
        gpu_layers=args.gpu_layers,
        threads=args.threads,
        chat_template=args.chat_template,
        server_bin=args.server_bin,
    )
    server = ModelServer(config)
    try:
        handle = server.start()
        print(f"Server running: pid={handle.pid} url={handle.base_url}", flush=True)
        print("Press Ctrl+C to stop.", flush=True)
        while True:
            time.sleep(5)
            if not server.health():
                print("WARNING: server unhealthy, attempting restart...", flush=True)
    except KeyboardInterrupt:
        pass
    finally:
        server.stop()
        print("Server stopped.", flush=True)


if __name__ == "__main__":
    _cli()

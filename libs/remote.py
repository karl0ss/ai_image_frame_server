import logging
import threading
import time

import paramiko

from libs.generic import load_config, get_bool

logger = logging.getLogger(__name__)

_client_lock = threading.Lock()
_active_refs = 0
_state_lock = threading.Lock()


class ComfyUIRemoteManager:
    """Starts and stops the ComfyUI service on a remote host over SSH.

    Uses a systemd service on the remote machine. The service is started before
    image generation and stopped afterwards. Concurrent jobs are reference
    counted so the service is only stopped once the last job finished.
    """

    def __init__(self, host: str, username: str, password: str, service: str,
                 startup_timeout: int = 90):
        self.host = host
        self.username = username
        self.password = password
        self.service = service
        self.startup_timeout = startup_timeout
        self.comfyui_url = ""
        self._client = None

    def _connect(self) -> paramiko.SSHClient:
        if self._client is None:
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            # Suppress the many "Adding host key" / banner warnings on first connect.
            logging.getLogger("paramiko").setLevel(logging.ERROR)
            client.connect(
                self.host,
                username=self.username,
                password=self.password,
                timeout=15,
                banner_timeout=15,
                auth_timeout=15,
                look_for_keys=False,
                allow_agent=False,
            )
            self._client = client
        return self._client

    def _run(self, command: str) -> str:
        client = self._connect()
        _, stdout, stderr = client.exec_command(command, timeout=60)
        out = stdout.read().decode()
        err = stderr.read().decode()
        rc = stdout.channel.recv_exit_status()
        logger.debug("SSH cmd '%s' -> rc=%s out=%r err=%r", command, rc, out, err)
        return out or err

    def _start(self) -> None:
        logger.info("Starting ComfyUI service '%s' on %s", self.service, self.host)
        self._run(f"echo '{self.password}' | sudo -S systemctl start {self.service}")
        self._run(f"echo '{self.password}' | sudo -S systemctl is-active {self.service}")
        self._wait_until_ready()

    def _wait_until_ready(self) -> None:
        config = load_config()
        base_url = config.get("comfyui", "comfyui_url", fallback="").strip()
        self.comfyui_url = base_url
        if not base_url:
            return
        import requests
        from urllib.parse import urljoin
        probe_url = urljoin(base_url.rstrip("/") + "/", "system_stats")
        waited = 0.0
        step = 5
        while waited < self.startup_timeout:
            try:
                resp = requests.get(probe_url, timeout=5)
                if resp.status_code == 200:
                    logger.info("ComfyUI service on %s is ready.", self.host)
                    return
            except Exception:
                pass
            waited += step
            time.sleep(step)
        logger.error("ComfyUI service on %s did not become ready within %ss.",
                     self.host, self.startup_timeout)

    def _stop(self) -> None:
        logger.info("Stopping ComfyUI service '%s' on %s", self.service, self.host)
        self._run(f"echo '{self.password}' | sudo -S systemctl stop {self.service}")
        self._close()

    def _close(self) -> None:
        if self._client is not None:
            try:
                self._client.close()
            except Exception as e:
                logger.debug("Error closing SSH client: %s", e)
            self._client = None

    @property
    def enabled(self) -> bool:
        return bool(self.host and self.service)

    def acquire(self) -> None:
        global _active_refs
        with _state_lock:
            if _active_refs == 0:
                self._start()
            _active_refs += 1

    def release(self) -> None:
        global _active_refs
        with _state_lock:
            if _active_refs <= 0:
                logger.warning("remote manager released without matching acquire")
                return
            _active_refs -= 1
            if _active_refs == 0:
                self._stop()


class _RemoteState:
    """Process-wide state so all callers share one manager instance."""

    _instance: ComfyUIRemoteManager | None = None

    @classmethod
    def get(cls) -> ComfyUIRemoteManager | None:
        with _client_lock:
            if cls._instance is None:
                config = load_config()
                if not config.has_section("remote"):
                    return None
                enabled = get_bool(config, "remote", "enabled", False)
                host = config.get("remote", "host", fallback="").strip()
                username = config.get("remote", "username", fallback="").strip()
                password = config.get("remote", "password", fallback="")
                service = config.get("remote", "service", fallback="comfyui").strip()
                if not enabled:
                    return None
                startup_timeout = config.getint("remote", "startup_poll_timeout", fallback=90)
                cls._instance = ComfyUIRemoteManager(
                    host, username, password, service, startup_timeout=startup_timeout
                )
            return cls._instance


def remote_acquire() -> None:
    """Start the remote ComfyUI service if configured, tracking active jobs."""
    try:
        manager = _RemoteState.get()
        if manager is None or not manager.enabled:
            return
        manager.acquire()
    except Exception as e:
        logger.error("Failed to start remote ComfyUI service: %s", e)


def remote_release() -> None:
    """Stop the remote ComfyUI service if configured and no jobs remain."""
    try:
        manager = _RemoteState.get()
        if manager is None or not manager.enabled:
            return
        manager.release()
    except Exception as e:
        logger.error("Failed to stop remote ComfyUI service: %s", e)


class RemoteService:
    """Context manager that starts the remote service on entry and stops it on exit."""

    def __init__(self):
        self._entered = False

    def __enter__(self):
        remote_acquire()
        self._entered = True
        return self

    def __exit__(self, exc_type, exc, tb):
        if self._entered:
            remote_release()
        return False

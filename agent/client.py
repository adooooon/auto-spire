"""Thin HTTP client for the AutoSpire mod's bridge API (see ../README.md)."""
from __future__ import annotations

import os
import subprocess
import time
from typing import Any

import requests

BASE_URL = "http://localhost:31452"
# Run the binary directly (Steam must be running) rather than `open steam://rungameid/...`:
# the URL launch silently does nothing when Steam shows a dialog (e.g. after a pkill).
# SteamAppId lets Steamworks init without going through the Steam launcher.
GAME_BIN = os.path.expanduser(
    "~/Library/Application Support/Steam/steamapps/common/Slay the Spire 2/"
    "SlayTheSpire2.app/Contents/MacOS/Slay the Spire 2"
)
STEAM_APP_ID = "2868840"
LOG_PATH = os.path.expanduser(
    "~/Library/Application Support/SlayTheSpire2/logs/godot.log"
)


class AutoSpireClient:
    def __init__(self, base_url: str = BASE_URL, timeout: float = 8.0, retries: int = 3):
        self.base_url = base_url
        self.timeout = timeout
        self.retries = retries

    def _request(self, method: str, path: str, timeout: float | None = None, retries: int | None = None, **kwargs) -> dict[str, Any]:
        timeout = self.timeout if timeout is None else timeout
        retries = self.retries if retries is None else retries
        last_exc: Exception | None = None
        for attempt in range(retries):
            try:
                r = requests.request(method, f"{self.base_url}{path}", timeout=timeout, **kwargs)
                r.raise_for_status()
                return r.json()
            except requests.RequestException as exc:
                last_exc = exc
                if attempt < retries - 1:
                    time.sleep(0.2 * (attempt + 1))
        raise last_exc  # type: ignore[misc]

    def ping(self) -> bool:
        try:
            r = requests.get(f"{self.base_url}/ping", timeout=self.timeout)
            return r.ok
        except requests.RequestException:
            return False

    def state(self) -> dict[str, Any]:
        return self._request("GET", "/state")

    def combat(self) -> dict[str, Any]:
        return self._request("GET", "/combat")

    def exec(self, cmd: str, settle: float = 0.15, timeout: float | None = None, retries: int | None = None) -> dict[str, Any]:
        # retries must stay at 1 for any call whose server-side handling can
        # legitimately run longer than the HTTP timeout (e.g. "newrun", which
        # awaits multi-second asset preloads): retrying while the first
        # attempt is still in flight server-side starts a second, concurrent
        # run-creation racing the first — this is what caused corrupted
        # startup state (NullReferenceException in RunManager.ClearScreens())
        # the first time this was built.
        result = self._request("POST", "/exec", data=cmd, timeout=timeout, retries=retries)
        # The mod reports state as "ready" (e.g. isPlayPhase flips) slightly
        # before the engine's own turn-banner/animation transitions finish,
        # even with `instant` mode on. Firing commands back-to-back without
        # this buffer piles up overlapping animations, and CPU/latency
        # degrades until requests start timing out. A small settle delay
        # after every exec call keeps the engine from falling behind.
        if settle:
            time.sleep(settle)
        return result

    def play(self, hand_index: int, target_id: int | None = None) -> dict[str, Any]:
        return self.exec(f"play {hand_index}" + ("" if target_id is None else f" {target_id}"))

    def end_turn(self) -> dict[str, Any]:
        return self.exec("end")

    def wait_for(
        self,
        predicate,
        poll_interval: float = 0.05,
        timeout: float = 5.0,
    ) -> dict[str, Any]:
        """Poll /combat until predicate(combat_state) is true, or raise TimeoutError."""
        deadline = time.monotonic() + timeout
        last: dict[str, Any] = {}
        while time.monotonic() < deadline:
            try:
                last = self.combat()
            except requests.RequestException:
                time.sleep(poll_interval)
                continue
            if predicate(last):
                return last
            time.sleep(poll_interval)
        raise TimeoutError(f"Timed out waiting for combat predicate. Last state: {last}")

    def full_restart(self, character: str = "IRONCLAD", boot_timeout: float = 60.0) -> None:
        """Quit and relaunch the game, then start a fresh run — no UI clicking involved.

        The live game's CPU/animation backlog only clears on a full process
        restart (see docs/modding-approach.md), so training loops should call
        this periodically (e.g. every N episodes) instead of relying solely
        on the lighter `fight`-command reset in env.py.
        """
        def _menu_marker_count() -> int:
            try:
                with open(LOG_PATH, "r", errors="replace") as f:
                    return f.read().count("Time to main menu:")
            except OSError:
                return 0

        subprocess.run(["pkill", "-f", "SlayTheSpire2.app/Contents/MacOS"], check=False)
        time.sleep(2.0)
        subprocess.Popen(
            [GAME_BIN],
            cwd=os.path.dirname(GAME_BIN),
            env={**os.environ, "SteamAppId": STEAM_APP_ID, "SteamGameId": STEAM_APP_ID},
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

        deadline = time.monotonic() + boot_timeout
        while time.monotonic() < deadline:
            if self.ping():
                break
            time.sleep(1.0)
        else:
            raise TimeoutError("Game did not come back up within boot_timeout")

        # godot.log turned out to truncate on launch (not append, despite
        # earlier appearances) — so the baseline must be captured only once
        # we know we're reading *this* process's log, i.e. right after its
        # /ping first responds, not before the kill/relaunch.
        marker_count_before = _menu_marker_count()

        # The mod's HTTP server (and /state reporting phase="menu") comes up
        # well before the game's own boot-time asset preload actually
        # finishes — calling newrun while that's still in flight races the
        # engine's own PreloadManager calls and corrupts startup (observed:
        # NullReferenceException in RunManager.ClearScreens(), "Encountered
        # error on game startup"). Total boot time varies a lot (900ms to
        # 13+ seconds, seen empirically) depending on disk/cache state, so
        # instead of guessing a fixed delay, watch the log for the engine's
        # own "reached main menu" marker.
        deadline = time.monotonic() + boot_timeout
        while time.monotonic() < deadline:
            if _menu_marker_count() > marker_count_before:
                break
            time.sleep(0.5)
        else:
            raise TimeoutError("Never saw 'Time to main menu' in godot.log within boot_timeout")

        self.exec(f"newrun {character}", settle=1.0, timeout=45.0, retries=1)
        deadline = time.monotonic() + boot_timeout
        while time.monotonic() < deadline:
            try:
                if self.state().get("inRun"):
                    return
            except requests.RequestException:
                pass
            time.sleep(0.5)
        raise TimeoutError("newrun did not result in inRun=true within boot_timeout")

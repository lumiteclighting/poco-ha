from __future__ import annotations

import asyncio
import json
import logging
from datetime import timedelta

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    DOMAIN,
    HTTP_PATH,
    HTTP_TIMEOUT,
    SCAN_INTERVAL_HTTP,
    SCAN_INTERVAL_WS,
    WS_PATH,
    WS_RECONNECT_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)


class PocoCoordinator(DataUpdateCoordinator[dict[int, dict]]):
    """
    Coordinate Poco device state with WebSocket push and HTTP polling fallback.

    Transport priority:
    1. WebSocket with typ:1 command support (v3.4.0+ firmware WS extension):
       commands sent as typ:1, responses received as typ:4, state changes as typ:3.
    2. WebSocket notifications only (older firmware): WS kept open for typ:3
       broadcasts, but commands fall back to HTTP.
    3. HTTP polling only: used whenever the WS connection is unavailable.

    Note on firmware field name: the spec defines `act` (array of Action objects)
    but as-shipped firmware returns `acts` (array of integers). The coordinator
    stores whichever key the firmware sends; only `id`, `state`, `bright`, `hue`,
    `sat`, `pid`, and `txt` are used by the light entity.
    """

    def __init__(self, hass: HomeAssistant, host: str) -> None:
        self.host = host
        self._session: aiohttp.ClientSession | None = None
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._ws_task: asyncio.Task | None = None
        self._ws_connected: bool = False
        # None = untested, True = firmware supports typ:1, False = broadcast-only
        self._ws_cmds_supported: bool | None = None
        self._rid: int = 0
        self._pending: dict[int, asyncio.Future] = {}

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=SCAN_INTERVAL_HTTP),
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _next_rid(self) -> int:
        self._rid = (self._rid % 65534) + 1
        return self._rid

    @property
    def _http_url(self) -> str:
        return f"http://{self.host}{HTTP_PATH}"

    @property
    def _ws_url(self) -> str:
        return f"ws://{self.host}{WS_PATH}"

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    # ------------------------------------------------------------------
    # HTTP
    # ------------------------------------------------------------------

    async def async_fetch_all(self) -> dict[int, dict]:
        """Fetch all switch state via HTTP GET. Returns {switch_id: sw_dict}."""
        session = await self._get_session()
        try:
            async with session.get(
                self._http_url,
                params={"q": "1"},
                timeout=aiohttp.ClientTimeout(total=HTTP_TIMEOUT),
            ) as resp:
                resp.raise_for_status()
                data = await resp.json(content_type=None)
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise UpdateFailed(f"HTTP error: {err}") from err

        if not data.get("success"):
            raise UpdateFailed(
                f"API error: {data.get('error', {}).get('txt', 'unknown')}"
            )
        return {sw["id"]: sw for sw in data.get("extsw", [])}

    async def _async_update_data(self) -> dict[int, dict]:
        """Periodic HTTP fallback poll called by DataUpdateCoordinator."""
        return await self.async_fetch_all()

    async def _http_action(self, switch_id: int, act: int, **params: int) -> dict:
        """Send an action via HTTP GET. Returns the full response body."""
        session = await self._get_session()
        query: dict[str, str] = {"q": "1", "id": str(switch_id), "act": str(act)}
        query.update({k: str(v) for k, v in params.items()})
        try:
            async with session.get(
                self._http_url,
                params=query,
                timeout=aiohttp.ClientTimeout(total=HTTP_TIMEOUT),
            ) as resp:
                resp.raise_for_status()
                return await resp.json(content_type=None)
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise HomeAssistantError(f"Poco HTTP command failed: {err}") from err

    # ------------------------------------------------------------------
    # WebSocket
    # ------------------------------------------------------------------

    async def async_start_ws(self) -> None:
        """Spawn the WebSocket listener background task (idempotent)."""
        if self._ws_task and not self._ws_task.done():
            return
        self._ws_task = self.hass.async_create_task(self._ws_listener())

    async def async_stop_ws(self) -> None:
        """Cancel the WebSocket listener and close the connection."""
        if self._ws_task and not self._ws_task.done():
            self._ws_task.cancel()
            self._ws_task = None
        if self._ws and not self._ws.closed:
            await self._ws.close()
        self._ws = None
        self._ws_connected = False
        for fut in self._pending.values():
            if not fut.done():
                fut.cancel()
        self._pending.clear()

    async def _ws_listener(self) -> None:
        """
        Maintain a persistent WebSocket connection with exponential back-off.
        Runs as a background task for the lifetime of the config entry.
        """
        backoff = 5
        while True:
            try:
                session = await self._get_session()
                async with session.ws_connect(
                    self._ws_url,
                    heartbeat=30,
                    timeout=aiohttp.ClientTimeout(connect=HTTP_TIMEOUT),
                ) as ws:
                    self._ws = ws
                    self._ws_connected = True
                    self.update_interval = timedelta(seconds=SCAN_INTERVAL_WS)
                    _LOGGER.info("Poco WS connected: %s", self.host)

                    # Probe whether the firmware handles typ:1 commands.
                    self._ws_cmds_supported = await self._probe_ws_commands(ws)
                    if self._ws_cmds_supported:
                        _LOGGER.info(
                            "Poco WS commands supported on %s", self.host
                        )
                    else:
                        _LOGGER.info(
                            "Poco WS commands NOT supported on %s — "
                            "using HTTP for commands, WS for notifications",
                            self.host,
                        )

                    backoff = 5  # reset on successful connect

                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            await self._handle_ws_message(msg.data)
                        elif msg.type in (
                            aiohttp.WSMsgType.CLOSED,
                            aiohttp.WSMsgType.ERROR,
                        ):
                            break

            except asyncio.CancelledError:
                _LOGGER.debug("Poco WS listener cancelled for %s", self.host)
                return
            except Exception as err:  # noqa: BLE001
                _LOGGER.debug("Poco WS error on %s: %s", self.host, err)

            # Connection lost — drop back to HTTP polling mode.
            self._ws = None
            self._ws_connected = False
            self._ws_cmds_supported = None
            self.update_interval = timedelta(seconds=SCAN_INTERVAL_HTTP)

            for fut in self._pending.values():
                if not fut.done():
                    fut.cancel()
            self._pending.clear()

            _LOGGER.debug(
                "Poco WS disconnected from %s, retrying in %ds", self.host, backoff
            )
            try:
                await asyncio.sleep(backoff)
            except asyncio.CancelledError:
                return
            backoff = min(backoff * 2, WS_RECONNECT_INTERVAL)

    async def _probe_ws_commands(
        self, ws: aiohttp.ClientWebSocketResponse
    ) -> bool:
        """
        Send a no-op query (act=0) over WS to detect whether the firmware
        handles typ:1 commands (firmware WS v3.4.0+).

        Old firmware with broadcast-only WS will silently ignore the message
        and we time out, returning False.  Commands will then be sent via HTTP
        while the WS connection is kept open for push notifications.
        """
        rid = self._next_rid()
        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        self._pending[rid] = fut
        try:
            await ws.send_str(json.dumps({"typ": 1, "rid": rid, "act": 0}))
            await asyncio.wait_for(asyncio.shield(fut), timeout=3.0)
            return True
        except asyncio.TimeoutError:
            self._pending.pop(rid, None)
            return False

    async def _handle_ws_message(self, raw: str) -> None:
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            return

        typ = msg.get("typ")

        if typ == 0:
            pass  # uptime heartbeat — connection is alive

        elif typ == 2:
            # Configuration changed — re-fetch full switch list.
            _LOGGER.debug("Poco config changed on %s, refreshing", self.host)
            await self.async_request_refresh()

        elif typ == 3:
            # State-change broadcast — merge into coordinator data.
            if self.data is None:
                return
            new_data = dict(self.data)
            for sw in msg.get("extsw", []):
                sw_id = sw.get("id")
                if sw_id in new_data:
                    new_data[sw_id] = {**new_data[sw_id], **sw}
            self.async_set_updated_data(new_data)

        elif typ == 4:
            # Command response — resolve the waiting future.
            rid = msg.get("rid")
            if rid is not None:
                fut = self._pending.pop(rid, None)
                if fut and not fut.done():
                    fut.set_result(msg)

    async def _ws_action(self, switch_id: int, act: int, **params: int) -> dict:
        """Send a typ:1 command and await the typ:4 response."""
        rid = self._next_rid()
        cmd: dict = {"typ": 1, "rid": rid, "id": switch_id, "act": act}
        cmd.update(params)
        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        self._pending[rid] = fut
        try:
            await self._ws.send_str(json.dumps(cmd))
            return await asyncio.wait_for(asyncio.shield(fut), timeout=HTTP_TIMEOUT)
        except asyncio.TimeoutError:
            self._pending.pop(rid, None)
            _LOGGER.warning(
                "Poco WS command timed out for %s, falling back to HTTP", self.host
            )
            return await self._http_action(switch_id, act, **params)
        except Exception:
            self._pending.pop(rid, None)
            raise

    # ------------------------------------------------------------------
    # Public command API
    # ------------------------------------------------------------------

    async def async_send_action(
        self, switch_id: int, act: int, **params: int
    ) -> None:
        """
        Send an action, choosing the best available transport:
          1. WS typ:1 (if connected and firmware supports commands)
          2. HTTP GET (fallback)

        Eagerly updates coordinator data from the command response so entities
        reflect the new state immediately without waiting for the next poll or
        an incoming typ:3 broadcast.
        """
        if self._ws_connected and self._ws_cmds_supported:
            resp = await self._ws_action(switch_id, act, **params)
        else:
            resp = await self._http_action(switch_id, act, **params)

        # Merge the command response into coordinator data.
        if resp.get("success") and self.data is not None:
            new_data = dict(self.data)
            for sw in resp.get("extsw", []):
                sw_id = sw.get("id")
                if sw_id is not None and sw_id in new_data:
                    new_data[sw_id] = {**new_data[sw_id], **sw}
            self.async_set_updated_data(new_data)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def async_shutdown(self) -> None:
        """Clean up all resources on config entry unload."""
        await self.async_stop_ws()
        if self._session and not self._session.closed:
            await self._session.close()

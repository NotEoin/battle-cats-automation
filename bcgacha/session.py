"""A device connection held open across many taps and frames.

Shelling out to the pymobiledevice3 CLI costs about two seconds per call,
almost all of it spent starting Python and negotiating a fresh tunnel -- the
capture itself is quick. Holding one tunnel, one DVT screenshot channel and one
HID touch session open for the life of the run removes that overhead, which is
what makes the roll loop feel responsive rather than sluggish.

The library is asyncio, the bot is not, so the loop runs on its own thread and
the public methods are ordinary blocking calls.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from concurrent.futures import Future
from contextlib import AsyncExitStack

import cv2
import numpy as np
from pymobiledevice3.remote import userspace_tunnel
from pymobiledevice3.remote.core_device.hid_service import (
    DIGITIZER_SURFACE_MAIN_TOUCHSCREEN,
    TOUCHSCREEN_STATE_CONTACT,
    TOUCHSCREEN_STATE_RELEASE,
    touch_session,
)
from pymobiledevice3.services.dvt.instruments.dvt_provider import DvtProvider
from pymobiledevice3.services.dvt.instruments.screenshot import Screenshot

# How often, in seconds, the phone is asked which way it is turned.
ORIENTATION_EVERY = 3.0

# How long a synthetic finger stays down. Real taps are not instantaneous and
# the game ignores a contact that releases in the same frame.
CONTACT_HOLD = 0.05
# How often a finger held still reports its contact again while it waits.
STILL_REPORT_EVERY = 0.05

# Seconds to wait for the tunnel to come up, for one call on it, and for it to
# close. A first connection negotiates a fresh tunnel and can take a minute.
OPEN_TIMEOUT = 180
CALL_TIMEOUT = 60
CLOSE_TIMEOUT = 30

log = logging.getLogger(__name__)


class DeviceSession:
    """Persistent connection to the attached device."""

    def __init__(self, serial: str | None = None):
        self.serial = serial
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._stack: AsyncExitStack | None = None
        self._screenshot = None
        self._touch = None
        self._ready = threading.Event()
        self._error: BaseException | None = None

    # -- lifecycle ----------------------------------------------------------

    def __enter__(self) -> "DeviceSession":
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        self._ready.wait(timeout=OPEN_TIMEOUT)
        if self._error:
            raise self._error
        if not self._ready.is_set():
            raise RuntimeError("device session did not come up in time")
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _run_loop(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._open())
        except BaseException as exc:  # surface startup failures to __enter__
            self._error = exc
            self._ready.set()
            return
        self._ready.set()
        self._loop.run_forever()

    async def _open(self) -> None:
        self._stack = AsyncExitStack()
        rsd = await userspace_tunnel.establish_userspace_rsd(serial=self.serial)
        await self._stack.enter_async_context(rsd)
        dvt = await self._stack.enter_async_context(DvtProvider(rsd))
        self._screenshot = await self._stack.enter_async_context(Screenshot(dvt))
        self._touch = await self._stack.enter_async_context(touch_session(rsd))
        await self._orientation()
        self._watch = asyncio.ensure_future(self._watch_orientation())

    async def _orientation(self) -> None:
        """Which way the phone is turned, so taps land where they are meant
        to. Unknown leaves the last answer standing."""
        import inspect

        from pymobiledevice3.lockdown import create_using_usbmux
        from pymobiledevice3.services.springboard import SpringBoardServicesService

        from . import layout

        try:
            lockdown = create_using_usbmux(serial=self.serial)
            if inspect.isawaitable(lockdown):
                lockdown = await lockdown
            answer = SpringBoardServicesService(lockdown).get_interface_orientation()
            if inspect.isawaitable(answer):
                answer = await answer
            if int(answer) in (layout.LANDSCAPE, layout.LANDSCAPE_OTHER_WAY):
                layout.orientation = int(answer)
        except Exception as exc:  # the phone not answering keeps the last answer, as above
            log.debug("orientation unknown: %s", exc)

    async def _watch_orientation(self) -> None:
        while True:
            await asyncio.sleep(ORIENTATION_EVERY)
            await self._orientation()

    def close(self) -> None:
        """Close the tunnel and stop its thread; safe to call twice."""
        if self._loop and self._loop.is_running():
            self._submit(self._close()).result(timeout=CALL_TIMEOUT)
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread:
            self._thread.join(timeout=CLOSE_TIMEOUT)

    async def _close(self) -> None:
        if getattr(self, "_watch", None):
            self._watch.cancel()
        if self._stack:
            await self._stack.aclose()
            self._stack = None

    def _submit(self, coro) -> Future:
        if self._loop is None:
            raise RuntimeError("the device session is not open: use it in a with block")
        return asyncio.run_coroutine_threadsafe(coro, self._loop)

    # -- operations ---------------------------------------------------------

    def screenshot(self) -> np.ndarray:
        """Grab the screen straight into a BGR array, never touching disk."""
        data = self._submit(self._screenshot.get_screenshot()).result(timeout=CALL_TIMEOUT)
        frame = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            raise RuntimeError("could not decode the screenshot")
        return frame

    def swipe(
        self, x1: int, y1: int, x2: int, y2: int, steps: int = 24, duration: float = 0.28
    ) -> None:
        """Drag from one normalised point to another.

        Some of the game's grids page by flick rather than by button, so a
        stream of contact reports is needed, not a tap.
        """
        self._submit(self._swipe(x1, y1, x2, y2, steps, duration)).result(timeout=CALL_TIMEOUT)

    async def _swipe(self, x1, y1, x2, y2, steps, duration) -> None:
        gap = duration / max(steps, 1)
        for i in range(steps):
            t = i / steps
            await self._touch.send_touchscreen(
                TOUCHSCREEN_STATE_CONTACT,
                round(x1 + (x2 - x1) * t), round(y1 + (y2 - y1) * t),
                service_id=DIGITIZER_SURFACE_MAIN_TOUCHSCREEN,
            )
            await asyncio.sleep(gap)
        await self._touch.send_touchscreen(
            TOUCHSCREEN_STATE_CONTACT, x2, y2,
            service_id=DIGITIZER_SURFACE_MAIN_TOUCHSCREEN,
        )
        await self._touch.send_touchscreen(
            TOUCHSCREEN_STATE_RELEASE, x2, y2,
            service_id=DIGITIZER_SURFACE_MAIN_TOUCHSCREEN,
        )

    def drag(
        self, x1: int, y1: int, x2: int, y2: int,
        duration: float = 0.8, hold: float = 0.3, steps: int = 40,
    ) -> None:
        """Move a finger slowly, then hold it still before lifting.

        A swipe lets go while the finger is still moving, and the carousels
        carry that speed on: the same flick moves one card one way and two the
        other. Stopping first leaves nothing to carry, so one drag is one card.
        """
        self._submit(self._drag(x1, y1, x2, y2, duration, hold, steps)).result(timeout=CALL_TIMEOUT)

    async def _drag(self, x1, y1, x2, y2, duration, hold, steps) -> None:
        for i in range(steps + 1):
            t = i / steps
            await self._touch.send_touchscreen(
                TOUCHSCREEN_STATE_CONTACT,
                round(x1 + (x2 - x1) * t), round(y1 + (y2 - y1) * t),
                service_id=DIGITIZER_SURFACE_MAIN_TOUCHSCREEN,
            )
            await asyncio.sleep(duration / steps)
        still = max(1, round(hold / STILL_REPORT_EVERY))
        for _ in range(still):
            await self._touch.send_touchscreen(
                TOUCHSCREEN_STATE_CONTACT, x2, y2,
                service_id=DIGITIZER_SURFACE_MAIN_TOUCHSCREEN,
            )
            await asyncio.sleep(STILL_REPORT_EVERY)
        await self._touch.send_touchscreen(
            TOUCHSCREEN_STATE_RELEASE, x2, y2,
            service_id=DIGITIZER_SURFACE_MAIN_TOUCHSCREEN,
        )

    def tap(self, x: int, y: int, hold: float = CONTACT_HOLD) -> None:
        """One contact and release at normalised coordinates (0..65535)."""
        self._submit(self._tap(x, y, hold)).result(timeout=CALL_TIMEOUT)

    async def _tap(self, x: int, y: int, hold: float = CONTACT_HOLD) -> None:
        await self._touch.send_touchscreen(
            TOUCHSCREEN_STATE_CONTACT, x, y,
            service_id=DIGITIZER_SURFACE_MAIN_TOUCHSCREEN,
        )
        await asyncio.sleep(hold)
        await self._touch.send_touchscreen(
            TOUCHSCREEN_STATE_RELEASE, x, y,
            service_id=DIGITIZER_SURFACE_MAIN_TOUCHSCREEN,
        )

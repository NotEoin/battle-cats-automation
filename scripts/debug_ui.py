#!/usr/bin/env python3
"""Watch what the bot sees, and send it anywhere on the map.

Serves a local page showing the live iPhone screen with what the vision code
finds on it: the screen identify() settles on and the candidates it weighed,
the OCR'd title box, every template anchor and its score, the gold controls
find_buttons() segments, and the tap points of the transitions leaving the
current screen. Under it sits the UI map; clicking a screen there runs
Navigator.goto() to it, and Stop aborts the walk before its next tap.

    python scripts/debug_ui.py                     # then open http://127.0.0.1:8765
    python scripts/debug_ui.py --replay captures/  # no device: cycle saved frames

One device session is shared. While a walk runs the page shows the frames the
navigator itself takes rather than competing with it for the screen.
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import traceback
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

from bcgacha import carousel, safety, vision  # noqa: E402
from bcgacha.uigraph import (  # noqa: E402
    TITLE_BOX, Navigator, NoRoute, UIGraph, find_back_arrow, find_buttons,
)
import draw_ui_graph  # noqa: E402

PAGE = HERE / "debug_ui.html"
VIEW_WIDTH = 1280           # frames are downscaled to this for the browser
KEEP_SNAPSHOTS = 4


class Stopped(RuntimeError):
    pass


class SharedSession:
    """The device session, shared by the page and the navigator.

    Every call is serialised, every frame anyone takes is kept for the page,
    and a stop request makes the next tap or swipe raise instead of touching
    the screen.
    """

    def __init__(self, session):
        self._session = session
        self._lock = threading.Lock()
        self._fresh = threading.Condition()
        self.frame: np.ndarray | None = None
        self.taken_at = 0.0
        self.version = 0
        self.stop_requested = threading.Event()

    def screenshot(self) -> np.ndarray:
        with self._lock:
            frame = self._session.screenshot()
        with self._fresh:
            self.frame, self.taken_at, self.version = frame, time.time(), self.version + 1
            self._fresh.notify_all()
        return frame

    def _guard(self) -> None:
        if self.stop_requested.is_set():
            raise Stopped("stopped from the debug page")

    def tap(self, *args, **kwargs):
        self._guard()
        with self._lock:
            return self._session.tap(*args, **kwargs)

    def swipe(self, *args, **kwargs):
        self._guard()
        with self._lock:
            return self._session.swipe(*args, **kwargs)

    def drag(self, *args, **kwargs):
        self._guard()
        with self._lock:
            return self._session.drag(*args, **kwargs)

    def latest(self, after: int, timeout: float):
        """The newest frame once it is newer than `after`, else what there is."""
        with self._fresh:
            self._fresh.wait_for(lambda: self.version > after, timeout)
            return self.frame, self.version, self.taken_at


class ReplaySession:
    """Saved frames in place of a device. It cannot tap."""

    def __init__(self, paths: list[Path]):
        files: list[Path] = []
        for p in paths:
            files += sorted(p.glob("*.png")) if p.is_dir() else [p]
        self.frames = [f for f in files if f.suffix.lower() in {".png", ".jpg", ".jpeg"}]
        if not self.frames:
            raise SystemExit("--replay found no .png or .jpg frames")
        self._next = 0

    def screenshot(self) -> np.ndarray:
        path = self.frames[self._next % len(self.frames)]
        self._next += 1
        return vision.load(path)

    def tap(self, *_a, **_k):
        raise RuntimeError("replay mode has no device to tap")

    swipe = drag = tap


class Debugger:
    def __init__(self, session, graph: UIGraph, replay: bool, interval: float):
        self.shared = SharedSession(session)
        self.graph = graph
        self.replay = replay
        self.interval = interval
        self.error: str | None = None
        self.log_lines: deque[str] = deque(maxlen=200)
        self.nav = dict(running=False, target=None, result=None)
        self._nav_graph: UIGraph | None = None      # its own OCR engine, not shared
        self._lock = threading.Lock()
        self._snaps: dict[int, dict] = {}
        self._latest = 0
        self._quit = threading.Event()
        self.map_version = 0
        self._set_graph(graph)

    def _set_graph(self, graph: UIGraph) -> None:
        """Adopt a new map: identification, the drawing and the page all follow."""
        if self.graph is not graph and self.graph._ocr is not None:
            graph._ocr = self.graph._ocr            # keep the loaded OCR engine
        self.graph = graph
        self._nav_graph = None
        self._rebuild_usage()
        with self._lock:
            self.map_version += 1
            self.map = map_payload(graph, self.map_version)
            self.page = build_page(self.map).encode()

    def _rebuild_usage(self) -> None:
        """Which screens lean on each anchor, and which way."""
        self.used_by: dict[str, list[str]] = {}
        for s in self.graph.screens.values():
            for a in s.anchors:
                self.used_by.setdefault(a, []).append(s.name)
            for a in s.absent:
                self.used_by.setdefault(a, []).append(f"not {s.name}")

    def log(self, line: str) -> None:
        self.log_lines.append(f"{time.strftime('%H:%M:%S')} {line}")

    # -- frames -----------------------------------------------------------------

    def start(self) -> None:
        threading.Thread(target=self._grab, daemon=True).start()
        threading.Thread(target=self._analyse_loop, daemon=True).start()

    def _grab(self) -> None:
        while not self._quit.is_set():
            if self.nav["running"]:
                time.sleep(0.2)             # the navigator's own frames feed the page
                continue
            try:
                self.shared.screenshot()
                self.error = None
            except Exception as exc:        # a dropped tunnel should not kill the page
                self.error = f"screenshot failed: {exc}"
                time.sleep(2)
                continue
            time.sleep(self.interval)

    def _analyse_loop(self) -> None:
        seen = 0
        while not self._quit.is_set():
            frame, version, taken_at = self.shared.latest(seen, timeout=1.0)
            if frame is None or version == seen:
                continue
            seen = version
            try:
                snap = self.analyse(frame)
            except Exception as exc:
                self.error = f"analysis failed: {exc}"
                continue
            snap["version"], snap["taken_at"] = version, taken_at
            with self._lock:
                self._snaps[version] = snap
                for old in sorted(self._snaps)[:-KEEP_SNAPSHOTS]:
                    del self._snaps[old]
                self._latest = version

    def analyse(self, frame: np.ndarray) -> dict:
        """Everything the bot can tell about one frame."""
        started = time.monotonic()
        h, w = frame.shape[:2]
        title = self.graph.read_title(frame)
        found = sorted(self.graph.candidates(frame, title=title), reverse=True)
        here = found[0][1] if found else None

        anchors = []
        for name, anchor in vision.ANCHORS.items():
            score = vision.match(frame, anchor)
            anchors.append(dict(name=name, box=anchor.box, score=round(score, 3),
                                threshold=anchor.threshold, hit=score > anchor.threshold,
                                used_by=self.used_by.get(name, [])))
        buttons = find_buttons(frame)
        exits = []
        for i, t in enumerate(self.graph.transitions):
            if t.src != here:
                continue
            on_button = not t.action and any(
                b.left <= t.x <= b.left + b.w and b.top <= t.y <= b.top + b.h for b in buttons)
            exits.append(dict(i=i, label=t.label, dst=t.dst, x=t.x, y=t.y, action=t.action,
                              forbidden=self.graph.screens[t.dst].forbidden,
                              on_button=on_button))
        dialog = safety.inspect_dialog(frame)

        scale = VIEW_WIDTH / w if w > VIEW_WIDTH else 1.0
        small = cv2.resize(frame, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        ok, jpeg = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 82])
        return dict(
            width=w, height=h, here=here, title=title, title_box=TITLE_BOX,
            candidates=[dict(name=n, score=round(s, 1)) for s, n in found],
            anchors=anchors,
            buttons=[dict(x=b.left, y=b.top, w=b.w, h=b.h,
                          fill=round(b.area / max(b.w * w * b.h * h, 1), 2)) for b in buttons],
            back=find_back_arrow(frame), exits=exits,
            dialog=dict(present=dialog.present, spends_cat_food=dialog.spends_cat_food),
            analysis_ms=round((time.monotonic() - started) * 1000),
            jpeg=jpeg.tobytes() if ok else b"",
        )

    def state(self) -> dict:
        with self._lock:
            snap = self._snaps.get(self._latest)
        view = {k: v for k, v in snap.items() if k != "jpeg"} if snap else None
        route = None
        if view and view["here"] and self.nav["target"] and view["here"] != self.nav["target"]:
            try:
                index = {id(t): i for i, t in enumerate(self.graph.transitions)}
                route = [index[id(t)] for t in self.graph.route(view["here"], self.nav["target"])]
            except NoRoute:
                route = None
        return dict(mode="replay" if self.replay else "device", error=self.error,
                    map_version=self.map_version,
                    now=time.time(), view=view, route=route, nav=dict(self.nav),
                    log=list(self.log_lines)[-80:])

    def jpeg(self, version: int | None) -> bytes | None:
        with self._lock:
            snap = self._snaps.get(version if version is not None else self._latest)
            return snap["jpeg"] if snap else None

    # -- navigation --------------------------------------------------------------

    def goto(self, dst: str) -> tuple[bool, str]:
        if self.replay:
            return False, "Replay mode has no device, so it cannot navigate."
        screen = self.graph.screens.get(dst)
        if screen is None:
            return False, f"{dst!r} is not on the map."
        if screen.forbidden:
            return False, f"{dst} is off limits; the navigator never routes into it."
        with self._lock:
            if self.nav["running"]:
                return False, f"Already navigating to {self.nav['target']}. Stop it first."
            self.nav = dict(running=True, target=dst, result=None)
        self.shared.stop_requested.clear()
        threading.Thread(target=self._walk, args=(dst,), daemon=True).start()
        return True, f"Navigating to {dst}."

    def _walk(self, dst: str) -> None:
        self.log(f"goto {dst}")
        result = "gave up"
        try:
            if self._nav_graph is None:
                self._nav_graph = UIGraph.load()
            if Navigator(self.shared, self._nav_graph).goto(dst, log=self.log):
                result = "arrived"
        except Stopped:
            result = "stopped"
        except Exception as exc:
            result = f"error: {exc}"
            self.log(traceback.format_exc(limit=4).rstrip())
        finally:
            self.log(f"goto {dst}: {result}")
            with self._lock:
                self.nav = dict(running=False, target=dst, result=result)
            self.shared.stop_requested.clear()

    def scan(self) -> tuple[bool, str]:
        """Read this save's sagas and chapters in the background, then redraw the map."""
        if self.replay:
            return False, "Replay mode has no device, so it cannot scan."
        with self._lock:
            if self.nav["running"]:
                return False, f"Busy with {self.nav['target']}. Stop it first."
            self.nav = dict(running=True, target="carousel scan", result=None)
        self.shared.stop_requested.clear()
        threading.Thread(target=self._scan, daemon=True).start()
        return True, "Scanning the saga and chapter carousels."

    def _scan(self) -> None:
        self.log("scanning the saga and chapter carousels")
        result = "failed"
        def grow(catalogue: dict) -> None:
            # Every saga and chapter joins the map the moment it is read.
            graph = UIGraph.load(carousels=False)
            carousel.extend(graph, catalogue)
            self._set_graph(graph)

        try:
            carousel.ensure(self.shared, rescan=True, log=self.log, progress=grow)
            self._set_graph(UIGraph.load())
            result = "done; the map now has this save's sagas and chapters"
        except Stopped:
            result = "stopped"
        except Exception as exc:
            result = f"error: {exc}"
            self.log(traceback.format_exc(limit=4).rstrip())
        finally:
            self.log(f"carousel scan: {result}")
            with self._lock:
                self.nav = dict(running=False, target="carousel scan", result=result)
            self.shared.stop_requested.clear()

    def stop(self) -> None:
        if self.nav["running"]:
            self.shared.stop_requested.set()
            self.log("stop requested; the walk ends before its next tap")


def map_payload(graph: UIGraph, version: int) -> dict:
    """The drawn map and the data its scripts need, tagged with a version."""
    drawing = draw_ui_graph.render_svg(graph)
    data = draw_ui_graph.map_data(graph)
    data["version"] = version
    return dict(version=version, svg=drawing.svg, data=data)


def build_page(payload: dict) -> str:
    page = PAGE.read_text()
    for key, value in {
        "CSS": draw_ui_graph.CSS_FILE.read_text(),
        "SVG": payload["svg"],
        "DATA": json.dumps(payload["data"], separators=(",", ":")).replace("</", "<\\/"),
    }.items():
        page = page.replace("{{" + key + "}}", value)
    return page


def make_handler(dbg: Debugger):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args) -> None:
            pass

        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code: int, obj) -> None:
            self._send(code, json.dumps(obj).encode(), "application/json")

        def do_GET(self) -> None:
            url = urlparse(self.path)
            if url.path == "/":
                self._send(200, dbg.page, "text/html; charset=utf-8")
            elif url.path == "/frame.jpg":
                v = parse_qs(url.query).get("v", [None])[0]
                body = dbg.jpeg(int(v) if v and v.isdigit() else None)
                if body:
                    self._send(200, body, "image/jpeg")
                else:
                    self._send(404, b"no frame yet", "text/plain")
            elif url.path == "/api/state":
                self._json(200, dbg.state())
            elif url.path == "/api/map":
                self._json(200, dbg.map)
            else:
                self._send(404, b"not found", "text/plain")

        def do_POST(self) -> None:
            url = urlparse(self.path)
            length = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                body = {}
            if url.path == "/api/goto":
                ok, message = dbg.goto(str(body.get("dst", "")))
                self._json(200 if ok else 409, dict(ok=ok, message=message))
            elif url.path == "/api/scan":
                ok, message = dbg.scan()
                self._json(200 if ok else 409, dict(ok=ok, message=message))
            elif url.path == "/api/stop":
                dbg.stop()
                self._json(200, dict(ok=True, message="Stopping."))
            else:
                self._send(404, b"not found", "text/plain")

    return Handler


def serve(dbg: Debugger, host: str, port: int, scan: bool = False) -> None:
    dbg.start()
    server = ThreadingHTTPServer((host, port), make_handler(dbg))
    if scan:
        dbg.scan()
    print(f"debug UI on http://{host}:{port}  ({'replay' if dbg.replay else 'device'})",
          file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        dbg.stop()
        server.server_close()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--interval", type=float, default=0.3,
                    help="pause between frames while idle, seconds (default 0.3)")
    ap.add_argument("--replay", nargs="+", type=Path, metavar="PATH",
                    help="PNG files or folders to cycle through instead of the device")
    ap.add_argument("--serial", help="device serial, if more than one is attached")
    ap.add_argument("--rescan", action="store_true",
                    help="read the saga and chapter carousels again once serving")
    args = ap.parse_args()

    if args.replay:
        graph = UIGraph.load()
        serve(Debugger(ReplaySession(args.replay), graph, True, max(args.interval, 1.5)),
              args.host, args.port)
        return 0

    from bcgacha.session import DeviceSession

    with DeviceSession(args.serial) as session:
        # This save's sagas and chapters are scanned the first time, in the
        # background, so the page is up at once and shows the scan happening.
        scan = args.rescan or carousel.load_catalogue() is None
        serve(Debugger(session, UIGraph.load(), False, args.interval),
              args.host, args.port, scan=scan)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

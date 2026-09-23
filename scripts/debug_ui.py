#!/usr/bin/env python3
"""Watch what the bot sees, and send it anywhere on the map.

Serves a local page showing the live iPhone screen with what recognition finds
on it: the screen it settles on and the candidates it weighed, the title it
read, the controls it has learned for this device and the ones a full look
perceives, the Cat Base door it compares, and the tap points of the
transitions leaving the current screen. Everything learned is logged as it is
learned. Under it sits the UI map; clicking a screen there runs
Navigator.goto() to it, and Stop aborts the walk before its next tap.

    python scripts/debug_ui.py                     # then open http://127.0.0.1:8765
    python scripts/debug_ui.py --replay captures/  # no device: cycle saved frames

One device session is shared. While a walk runs the page shows the frames the
navigator itself takes rather than competing with it for the screen. Replayed
frames learn into a fresh temporary folder unless --profiles says otherwise,
never into state/devices, where a running bot keeps what it has learned.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import tempfile
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

from bcgacha import bases, carousel, safety, vision  # noqa: E402
from bcgacha.profile import DEVICES_DIR  # noqa: E402
from bcgacha.uigraph import Navigator, NoRoute, UIGraph, find_buttons  # noqa: E402
import draw_ui_graph  # noqa: E402

PAGE = HERE / "debug_ui.html"
VIEW_WIDTH = 1280           # frames are downscaled to this for the browser
KEEP_SNAPSHOTS = 4
# While a job drives the phone, a frame is analysed at most this often. The
# picture itself is sent as soon as it is taken, whatever this is.
BUSY_ANALYSIS = 0.8
FRAME_SUFFIXES = {".png", ".jpg", ".jpeg"}


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
            files += sorted(p.iterdir()) if p.is_dir() else [p]
        self.frames = [f for f in files if f.suffix.lower() in FRAME_SUFFIXES]
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
    def __init__(self, session, replay: bool, interval: float, profile_root: Path | None = None):
        self.shared = SharedSession(session)
        self.replay = replay
        self.interval = interval
        # Kept apart so a good frame cannot clear an analysis failure, nor a
        # good analysis a dropped tunnel.
        self.grab_error: str | None = None
        self.analysis_error: str | None = None
        self._failures: set = set()                 # analysis tracebacks already logged
        self.log_lines: deque[str] = deque(maxlen=200)
        # `job` names a background scan; a walk has a `target` instead.
        self.nav = dict(running=False, target=None, job=None, result=None)
        self.options = dict(full_look=False)
        # Every graph built here learns under this root into these profiles,
        # so the page, the navigator and a scan share one set of learning.
        self.profile_root = profile_root
        self._profiles: dict = {}
        self.graph: UIGraph | None = None
        self._nav_graph: UIGraph | None = None      # its own OCR engine, not shared
        self._lock = threading.Lock()
        self._snaps: dict[int, dict] = {}
        self._latest = 0
        # The newest frame taken, by anyone, ready to send: the picture on the
        # page never waits for analysis.
        self._live: tuple[int, float, bytes] | None = None
        self._recent: dict[int, bytes] = {}         # the last few frames sent, by version
        self._to_learn: np.ndarray | None = None    # the newest frame analysis could not name
        self._quit = threading.Event()
        self.map_version = 0
        # What the pipeline has found so far, by section, for the page.
        self.pipeline: dict = {}
        self.pipeline_version = 0
        self.rolls: deque = deque(maxlen=400)
        self.owned_entries: deque = deque(maxlen=40)
        self._set_graph(self._load())
        self.log(f"learning device profiles into {profile_root or DEVICES_DIR}")

    def _load(self, carousels: bool = True, ocr=None) -> UIGraph:
        """The map, built as every graph here must be: under --profiles, into
        the one set of profiles. `ocr` shares a loaded engine; without one the
        graph loads its own when it first reads."""
        graph = UIGraph.load(carousels=carousels)
        graph.profile_root, graph._profiles, graph._ocr = self.profile_root, self._profiles, ocr
        return graph

    def _set_graph(self, graph: UIGraph) -> None:
        """Adopt a new map from _load(): identification, the drawing and the page all follow."""
        if graph._ocr is None and self.graph is not None:
            graph._ocr = self.graph._ocr            # keep the loaded OCR engine
        self.graph = graph
        self._nav_graph = None
        with self._lock:
            self.map_version += 1
            self.map = map_payload(graph, self.map_version)
            self.page = build_page(self.map).encode()

    def log(self, line: str) -> None:
        self.log_lines.append(f"{time.strftime('%H:%M:%S')} {line}")

    # -- frames -----------------------------------------------------------------

    def start(self) -> None:
        threading.Thread(target=self._grab, daemon=True).start()
        threading.Thread(target=self._analyse_loop, daemon=True).start()
        threading.Thread(target=self._encode_loop, daemon=True).start()
        threading.Thread(target=self._learn_loop, daemon=True).start()

    def _learn_loop(self) -> None:
        """Give a frame analysis could not name a full look -- OCR and shapes
        -- which learns the screen, so the next frames of it name fast."""
        while not self._quit.is_set():
            time.sleep(0.5)
            with self._lock:
                frame, self._to_learn = self._to_learn, None
            if frame is None or self.nav["running"]:
                continue
            try:
                self.graph.recognise(frame)
            except Exception as exc:
                self._analysis_failed(exc)

    def _encode_loop(self) -> None:
        seen = 0
        while not self._quit.is_set():
            frame, version, taken_at = self.shared.latest(seen, timeout=1.0)
            if frame is None or version == seen:
                continue
            seen = version
            h, w = frame.shape[:2]
            scale = VIEW_WIDTH / w if w > VIEW_WIDTH else 1.0
            small = cv2.resize(frame, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
            ok, jpeg = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 82])
            if ok:
                with self._lock:
                    self._live = (version, taken_at, jpeg.tobytes())
                    self._recent[version] = self._live[2]
                    for old in sorted(self._recent)[:-KEEP_SNAPSHOTS]:
                        del self._recent[old]

    def _grab(self) -> None:
        while not self._quit.is_set():
            if self.nav["running"]:
                time.sleep(0.2)             # the navigator's own frames feed the page
                continue
            try:
                self.shared.screenshot()
                self.grab_error = None
            except Exception as exc:        # a dropped tunnel should not kill the page
                self.grab_error = f"screenshot failed: {exc}"
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
            if self.nav["running"] and time.monotonic() - getattr(self, "_last_busy", 0.0) < BUSY_ANALYSIS:
                continue        # a job is driving: analyse a frame now and then, not every one
            self._last_busy = time.monotonic()
            try:
                snap = self.analyse(frame)
            except Exception as exc:
                self._analysis_failed(exc)
                continue
            self.analysis_error = None
            snap["version"], snap["taken_at"] = version, taken_at
            with self._lock:
                self._snaps[version] = snap
                for old in sorted(self._snaps)[:-KEEP_SNAPSHOTS]:
                    del self._snaps[old]
                self._latest = version

    def _analysis_failed(self, exc: Exception) -> None:
        # The message stays up until a frame analyses cleanly. The traceback is
        # logged once per kind of failure and place it was raised: a bug hit on
        # every frame would otherwise bury the log.
        self.analysis_error = f"analysis failed: {type(exc).__name__}: {exc} (traceback in the log)"
        where = (type(exc).__name__,
                 tuple((f.filename, f.lineno) for f in traceback.extract_tb(exc.__traceback__)))
        if where not in self._failures:
            self._failures.add(where)
            self.log(traceback.format_exc().rstrip())

    def analyse(self, frame: np.ndarray) -> dict:
        """Everything the bot can tell about one frame, and how it told."""
        from bcgacha.perception import perceive

        started = time.monotonic()
        graph = self.graph                  # a scan may swap in a new map meanwhile
        h, w = frame.shape[:2]
        profile = graph.profile_for(frame)
        if self.log not in profile.listeners:
            profile.listeners.append(self.log)

        # Analysis reads nothing: a screen seen before is named from pictures
        # remembered of it, in milliseconds. One that cannot be named that way
        # is handed, when no job drives the phone, to a full look on its own
        # thread (_learn_loop), which learns it; the frames after name fast.
        title_box = profile.title_box
        busy = self.nav["running"]
        title = profile.known_text(frame, title_box) if title_box else None
        rec = graph.recognise(frame, title=title, slow=False, ocr=False)
        if not busy and not any(c.verified and c.name == rec.here for c in rec.candidates):
            with self._lock:
                self._to_learn = frame
        here = rec.here
        percept = rec.percept
        full_look = percept is not None
        if full_look:
            title = percept.title.text if percept.title else ""    # what the full look went on
        elif self.options["full_look"]:
            percept = perceive(frame, graph.ocr)                    # shown, not needed
        title_box = profile.title_box       # a full look may have just placed or widened it

        learned = []
        for key, entry in (profile.controls(here) if here else {}).items():
            found = profile.find(frame, here, key)
            learned.append(dict(key=key, label=entry.get("label", key), kind=entry.get("kind"),
                                found=found is not None,
                                box=list(found["box"]) if found else entry["box"],
                                score=found["score"] if found else None))
        perceived = [dict(label=c.label, kind=c.kind, box=list(c.box), tap=list(c.tap))
                     for c in (percept.controls if percept else [])]

        known_bases = profile.bases()
        base = None
        if here == "cat_base":
            # Why the chapter is or is not known: nothing learned yet, the door
            # not found, or learned doors that are all too far from this one.
            nearest = []
            if known_bases and rec.door:
                sig = bases.signature(frame, rec.door)
                nearest = sorted(
                    (bases.distance(sig, s), name) for name, s in known_bases.items())[:2]
            base = dict(learned=len(known_bases), door=rec.door is not None,
                        match=bases.MATCH_DISTANCE,
                        nearest=[dict(chapter=name, note=screen_note(graph, name),
                                      distance=round(d, 4) if math.isfinite(d) else None)
                                 for d, name in nearest])

        exits = []
        for i, t in enumerate(graph.transitions):
            if t.src != here or t.src == t.dst:
                continue
            how, point = "routine", None
            if not t.action:
                if not t.target or t.target == "@card":
                    how, point = "fixed point", (t.x, t.y)
                else:
                    found = profile.find(frame, here, t.target)
                    control = percept.find(t.target) if (found is None and percept) else None
                    if found:
                        how, point = "learned template", found["tap"]
                    elif control:
                        how, point = "perception", control.tap
                    elif t.x or t.y:
                        how, point = "recorded hint", (t.x, t.y)
                    else:
                        how = "not found"
            exits.append(dict(i=i, label=t.label, target=t.target, dst=t.dst, action=t.action,
                              how=how, x=point[0] if point else None, y=point[1] if point else None,
                              forbidden=graph.screens[t.dst].forbidden))
        dialog = safety.inspect_dialog(frame)
        # Drawn on the page, not acted on: found on a half-size frame.
        buttons = find_buttons(cv2.resize(frame, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA))

        chapter = rec.chapter
        return dict(
            width=w, height=h, here=here, title=title, title_box=title_box,
            title_from=("full look" if full_look else "learned title box") if title is not None else None,
            how="full look: OCR and shape segmentation" if full_look else "fast: learned title box and templates",
            candidates=[dict(name=c.name, score=round(c.score, 1), verified=c.verified, read=c.read)
                        for c in sorted(rec.candidates, key=lambda c: -c.score)],
            learned=learned, perceived=perceived,
            buttons=[dict(x=b.left, y=b.top, w=b.w, h=b.h,
                          fill=round(b.area / max(b.w * w * b.h * h, 1), 2)) for b in buttons],
            exits=exits, chapter=chapter,
            chapter_title=screen_note(graph, chapter) if chapter else None,
            door=list(rec.door) if rec.door else None, base=base,
            profile=dict(key=profile.key, title_box=title_box,
                         screens=profile.screen_names(), bases=sorted(known_bases)),
            dialog=dict(present=dialog.present, spends_cat_food=dialog.spends_cat_food),
            analysis_ms=round((time.monotonic() - started) * 1000),
        )

    def state(self) -> dict:
        with self._lock:
            snap = self._snaps.get(self._latest)
        view = dict(snap) if snap else None
        route = None
        if view and view["here"] and self.nav["target"] and view["here"] != self.nav["target"]:
            try:
                index = {id(t): i for i, t in enumerate(self.graph.transitions)}
                route = [index[id(t)] for t in self.graph.route(view["here"], self.nav["target"])]
            except NoRoute:
                route = None
        errors = [e for e in (self.grab_error, self.analysis_error) if e]
        return dict(mode="replay" if self.replay else "device", error="; ".join(errors) or None,
                    map_version=self.map_version, options=self.options,
                    pipeline_version=self.pipeline_version,
                    now=time.time(), view=view, route=route, nav=dict(self.nav),
                    live=dict(version=self._live[0], taken_at=self._live[1]) if self._live else None,
                    log=list(self.log_lines)[-80:])

    def jpeg(self, version: int | None) -> bytes | None:
        with self._lock:
            live = self._live
            if live and version is None:
                return live[2]
            return self._recent.get(version)

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
                return False, f"{self._busy()}. Stop it first."
            self.nav = dict(running=True, target=dst, job=None, result=None)
        self.shared.stop_requested.clear()
        threading.Thread(target=self._walk, args=(dst,), daemon=True).start()
        return True, f"Navigating to {dst}."

    def _busy(self) -> str:
        return (f"Busy {self.nav['job']}" if self.nav["job"]
                else f"Already navigating to {self.nav['target']}")

    def _walk(self, dst: str) -> None:
        self.log(f"goto {dst}")
        result = "gave up"
        try:
            if self._nav_graph is None:
                self._nav_graph = self._load()
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
                self.nav = dict(running=False, target=dst, job=None, result=result)
            self.shared.stop_requested.clear()

    def scan(self, rescan: bool = True) -> tuple[bool, str]:
        """In the background, read this save's sagas and chapters -- again if
        `rescan`, else only if none are saved -- and learn any Cat Base
        backgrounds this device lacks. The map redraws as it grows."""
        if self.replay:
            return False, "Replay mode has no device, so it cannot scan."
        scanning = rescan or carousel.load_catalogue() is None
        job = ("scanning the saga and chapter carousels" if scanning
               else "learning this device's Cat Base backgrounds")
        with self._lock:
            if self.nav["running"]:
                return False, f"{self._busy()}. Stop it first."
            self.nav = dict(running=True, target=None, job=job, result=None)
        self.shared.stop_requested.clear()
        threading.Thread(target=self._scan, args=(rescan, scanning), daemon=True).start()
        return True, f"{job[0].upper()}{job[1:]}."

    def _scan(self, rescan: bool, scanning: bool) -> None:
        job, result = self.nav["job"], "failed"

        def grow(catalogue: dict) -> None:
            # Every saga and chapter joins the map the moment it is read.
            graph = self._load(carousels=False)
            carousel.extend(graph, catalogue)
            self._set_graph(graph)

        try:
            scan_graph = self._load(carousels=False, ocr=self.graph._ocr)
            carousel.ensure(self.shared, rescan=rescan, log=self.log, progress=grow,
                            graph=scan_graph)
            if scanning:
                self._set_graph(self._load())
                result = "done; the map now has this save's sagas and chapters"
            else:
                result = "done"
        except Stopped:
            result = "stopped"
        except Exception as exc:
            result = f"error: {exc}"
            self.log(traceback.format_exc(limit=4).rstrip())
        finally:
            self.log(f"{job}: {result}")
            with self._lock:
                self.nav = dict(running=False, target=None, job=job, result=result)
            self.shared.stop_requested.clear()

    def catch_up(self, rescan: bool = False) -> None:
        """Once the device sends a frame, start a scan if this save's carousels
        are not saved (or `rescan`), or if the device lacks any Cat Base
        background they lead to: a new phone, or a chapter unlocked since."""
        threading.Thread(target=self._catch_up, args=(rescan,), daemon=True).start()

    def _catch_up(self, rescan: bool) -> None:
        try:
            catalogue = None if rescan else carousel.load_catalogue()
            if catalogue is not None:
                frame = None
                while frame is None and not self._quit.is_set():
                    frame, _, _ = self.shared.latest(0, timeout=5.0)
                if frame is None:
                    return
                missing = carousel.missing_bases(self.graph, catalogue, frame)
                if not missing:
                    return
                self.log(f"this device has yet to learn {len(missing)} Cat Base "
                         f"background{'s' if len(missing) != 1 else ''}")
            ok, message = self.scan(rescan=rescan)
            if not ok:
                self.log(f"startup scan not run: {message}")
        except Exception:
            self.log(traceback.format_exc(limit=4).rstrip())

    # -- the pipeline -------------------------------------------------------------

    def publish(self, section: str, payload) -> None:
        with self._lock:
            if section == "roll":
                self.rolls.append(payload)
            elif section == "owned_entry":
                self.owned_entries.append(payload)
            else:
                self.pipeline[section] = payload
            self.pipeline_version += 1

    def pipeline_state(self) -> dict:
        with self._lock:
            return dict(version=self.pipeline_version, sections=dict(self.pipeline),
                        rolls=list(self.rolls)[-80:], owned_entries=list(self.owned_entries)[-12:])

    STAGES = ("graph", "owned", "events", "seed", "plan", "run")

    def run_pipeline(self, stages: list[str], options: dict) -> tuple[bool, str]:
        """Run pipeline stages in order, in the background, on the one device session."""
        if self.replay:
            return False, "Replay mode has no device."
        stages = [st for st in self.STAGES if st in stages]
        if not stages:
            return False, "No stages named."
        with self._lock:
            if self.nav["running"]:
                return False, f"{self._busy()}. Stop it first."
            self.nav = dict(running=True, target=None, job=f"pipeline: {stages[0]}", result=None)
        self.shared.stop_requested.clear()
        threading.Thread(target=self._pipeline, args=(stages, options), daemon=True).start()
        return True, f"Running {', '.join(stages)}."

    def _pipeline(self, stages: list[str], options: dict) -> None:
        from bcgacha import events as live
        from bcgacha import pipeline as P
        from bcgacha.catindex import OwnedIndex
        from bcgacha.data import load

        result = "failed"
        try:
            graph = self._load()
            ctx = P.Context(session=self.shared, graph=graph, ocr=graph.ocr, dataset=load(),
                            log=self.log, publish=self.publish,
                            should_stop=self.shared.stop_requested.is_set)
            owned = account = None
            for stage in stages:
                with self._lock:
                    self.nav["job"] = f"pipeline: {stage}"
                self.publish("stage", dict(name=stage, state="running"))
                self.log(f"pipeline: {stage}")
                if stage == "graph":
                    P.stage_graph(ctx, reload=self._load)
                    self._set_graph(self._load())
                elif stage == "owned":
                    owned = P.stage_owned(ctx, force=bool(options.get("rescan_owned")),
                                          limit=options.get("owned_limit"))
                elif stage == "events":
                    P.stage_events(ctx, visit=True)
                elif stage == "seed":
                    account = P.stage_seed(ctx)
                elif stage in ("plan", "run"):
                    owned = owned or OwnedIndex.load()
                    if not owned.complete:
                        raise RuntimeError("no complete owned list: run the owned stage first")
                    account = account or P.stage_seed(ctx)
                    events = ctx.graph.events
                    prefer = live.find(events, options.get("prefer", "Iron Legion"))
                    # "Galaxy Gals, Iron Legion": only their units are wanted.
                    names = [n.strip() for n in str(options.get("goal_events") or "").split(",") if n.strip()]
                    goal_events = [live.find(events, n) for n in names]
                    if None in goal_events:
                        raise RuntimeError(f"no live event named {names[goal_events.index(None)]!r}")
                    legends = bool(options.get("legends", True))
                    # Counts given with the request win; else what the last run left.
                    rare = int(options.get("rare") or account.tickets or 0)
                    platinum = int(options.get("platinum") or account.platinum_tickets or 0)
                    if not rare:
                        raise RuntimeError("the rare ticket count is needed (options.rare)")
                    self.publish("tickets", dict(rare=rare, platinum=platinum, source="given"))
                    sim = P.simulate(ctx, account, owned.owned, events, rare, platinum, prefer,
                                     goal_events, legends)
                    self.publish("simulation", sim)
                    planner, goal, tiers = P.build_plan(ctx, account, owned.owned, events, platinum, prefer,
                                                        goal_events, legends)
                    self.publish("goal", P.goal_json(goal, ctx.dataset, tiers, owned.owned, events))
                    plan = planner.plan(account.seed, rolls=P.PLAN_ROLLS, index=account.index,
                                        track=account.track, previous_cat=account.last_cat_id)
                    self.publish("plan", P.plan_json(plan, ctx.dataset, events))
                    if stage == "run":
                        run = P.GoalRun(ctx, account, planner, goal, owned, events, tiers, rare, platinum)
                        self.publish("stage", dict(name="run", state="rolling"))
                        run.run()
                self.publish("stage", dict(name=stage, state="done"))
            result = "done"
        except (Stopped, P.Stopped):
            result = "stopped"
        except Exception as exc:
            result = f"error: {exc}"
            self.log(traceback.format_exc(limit=6).rstrip())
        finally:
            self.log(f"pipeline: {result}")
            with self._lock:
                self.nav = dict(running=False, target=None, job="pipeline", result=result)
            self.shared.stop_requested.clear()

    def stop(self) -> None:
        if self.nav["running"]:
            self.shared.stop_requested.set()
            self.log("stop requested; the walk ends before its next tap")


def screen_note(graph: UIGraph, name: str) -> str:
    """A chapter's saga, number and name, from its note; a screen the map
    has lost since its background was learned is known only by name."""
    screen = graph.screens.get(name)
    return screen.note if screen and screen.note else name


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
            elif url.path == "/api/pipeline":
                self._json(200, dbg.pipeline_state())
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
            elif url.path == "/api/pipeline":
                ok, message = dbg.run_pipeline(list(body.get("stages") or []), dict(body.get("options") or {}))
                self._json(200 if ok else 409, dict(ok=ok, message=message))
            elif url.path == "/api/scan":
                ok, message = dbg.scan()
                self._json(200 if ok else 409, dict(ok=ok, message=message))
            elif url.path == "/api/options":
                dbg.options.update({k: bool(v) for k, v in body.items() if k in dbg.options})
                self._json(200, dict(ok=True, message="", options=dbg.options))
            elif url.path == "/api/stop":
                dbg.stop()
                self._json(200, dict(ok=True, message="Stopping."))
            else:
                self._send(404, b"not found", "text/plain")

    return Handler


def serve(dbg: Debugger, host: str, port: int, rescan: bool = False) -> None:
    dbg.start()
    server = ThreadingHTTPServer((host, port), make_handler(dbg))
    if not dbg.replay:
        dbg.catch_up(rescan)
    print(f"debug UI on http://{host}:{port}  ({'replay' if dbg.replay else 'device'}); "
          f"learning device profiles into {dbg.profile_root or DEVICES_DIR}", file=sys.stderr)
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
                    help="PNG or JPEG frames, or folders of them, to cycle through "
                         "instead of the device")
    ap.add_argument("--serial", help="device serial, if more than one is attached")
    ap.add_argument("--profiles", type=Path, default=None, metavar="DIR",
                    help="learn device profiles here instead of state/devices; with "
                         "--replay, a fresh temporary folder unless given "
                         "(an empty folder shows what a fresh device learns)")
    ap.add_argument("--rescan", action="store_true",
                    help="read the saga and chapter carousels again once serving")
    args = ap.parse_args()

    if args.replay:
        # Replayed frames learn as live ones do. Into state/devices that could
        # overwrite what a bot running on the real device has learned.
        profiles = args.profiles or Path(tempfile.mkdtemp(prefix="bcgacha-profiles-"))
        serve(Debugger(ReplaySession(args.replay), True, max(args.interval, 1.5), profiles),
              args.host, args.port)
        return 0

    from bcgacha.session import DeviceSession

    with DeviceSession(args.serial) as session:
        # This save's sagas and chapters, and any Cat Base backgrounds this
        # device lacks, are learned in the background, so the page is up at
        # once and shows the learning happen.
        serve(Debugger(session, False, args.interval, args.profiles),
              args.host, args.port, rescan=args.rescan)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

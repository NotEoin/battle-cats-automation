#!/usr/bin/env python3
"""Draw data/ui_graph.json: every screen, how it is recognised, and every way between.

Screens are placed by hand so no two edges cross. A screen or transition the
layout does not know about yet is still drawn -- screens in a strip along the
bottom, transitions as straight lines -- and named on stderr, so the picture
never silently drops part of the map. Give it a place in LAYOUT or EDGES below.

    python scripts/draw_ui_graph.py                  # writes logs/ui_graph.html
    python scripts/draw_ui_graph.py --out map.html

scripts/debug_ui.py imports render_svg() to draw the same map under the live
screen. Routes on the page are UIGraph.route() output, never re-implemented.
"""
from __future__ import annotations

import argparse
import html
import json
import math
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from bcgacha.uigraph import NoRoute, UIGraph  # noqa: E402

CSS_FILE = HERE / "ui_graph.css"
PAGE_TEMPLATE = HERE / "ui_graph_page.html"
DEFAULT_OUT = ROOT / "logs" / "ui_graph.html"

# -- layout -------------------------------------------------------------------

NW, NH = 148, 58                                # screen box
C1, C2, C4, C5 = 24, 252, 752, 996              # column left edges
BUS_L, BUS_R, BUS_TOP, BUS_BOT = 548, 640, 28, 812   # cat_base, drawn as a bus
VBW, VBH = 1190, 970

# Centre-left anchor (x of the left edge, y of the centre) of every placed screen.
LAYOUT = {
    "opening": (C1, 100), "title": (C1, 252), "settings": (C1, 392),
    "saga_select": (C2, 252), "base_select": (C2, 392),
    "menu": (C4, 100), "cat_guide": (C5, 100),
    "upgrade": (C4, 176), "organize_cats": (C4, 252), "catnip_challenges": (C4, 328),
    "gamatoto": (C4, 440), "gamatoto_report": (C5, 440), "gamatoto_ongoing": (C4, 516),
    "rare_capsules": (C5, 640), "storage": (C4, 716), "platinum_capsules": (C5, 792),
    "roll_result": (C4, 912), "sent_to_storage": (C5, 912),
}
HUB = "cat_base"

ZONES = [
    (740, 386, 416, 171, "GAMATOTO · three states"),
    (740, 583, 440, 374, "Capsule machines"),
]

# How each reactive screen shows up. Annotations, not map edges.
STUBS = [
    ("roll_result", [(704, 912), (752, 912)], "after a draw", (698, 916), "end"),
    ("gamatoto_report", [(1070, 376), (1070, 411)], "log replays", (1070, 368), "middle"),
]

# Order of the screen pickers: roughly left to right, top to bottom.
ORDER = ["opening", "title", "settings", "saga_select", "base_select", "cat_base",
         "menu", "cat_guide", "upgrade", "organize_cats", "catnip_challenges",
         "gamatoto", "gamatoto_ongoing", "gamatoto_report", "storage", "rare_capsules",
         "platinum_capsules", "roll_result", "sent_to_storage", "purchase_offer"]


@dataclass
class Edge:
    tids: list[int]
    pts: list[tuple[float, float]] | None = None
    label: str | None = None
    lines: list[str] | None = None
    at: tuple[float, float] | None = None
    anchor: str = "middle"
    head: bool = True
    trunk: bool = False
    diamond: tuple[float, float] | None = None
    path: str | None = None
    heads: list = field(default_factory=list)
    chip: tuple[str, float, float] | None = None
    chip_only: bool = False
    icon: tuple[float, float] | None = None
    zone: bool = False
    auto: bool = False
    stub: bool = False


def _layout_edges(find) -> list[Edge]:
    """The hand-routed edges. `find(src, dst)` returns matching transition indices."""
    E: list[Edge] = []

    def add(tids, pts=None, **kw):
        if tids:
            E.append(Edge(tids=tids, pts=pts, **kw))

    # Front end
    add(find("opening", "title"), [(98, 129), (98, 223)], label="Skip", at=(106, 180), anchor="start")
    add(find("title", "settings"), [(78, 281), (78, 363)], label="Settings", at=(64, 326),
        anchor="end", icon=(78, 322))
    add(find("settings", "title"), [(118, 363), (118, 281)], label="Close", at=(126, 326), anchor="start")
    add(find("title", "saga_select") + find("title", "base_select"), [(172, 260), (220, 260)],
        label="Play", at=(194, 281), head=False, trunk=True, diamond=(226, 260))
    add(find("title", "saga_select"), [(232, 260), (252, 260)])
    add(find("title", "base_select"), [(226, 266), (226, 384), (252, 384)])
    add(find("saga_select", "title"), [(252, 244), (172, 244)], label="X", at=(212, 235))
    add(find("saga_select", "base_select"), [(362, 281), (362, 363)],
        label="enter selected saga", at=(370, 326), anchor="start")
    add(find("base_select", "saga_select"), [(322, 363), (322, 281)],
        lines=["X or", "Back card"], at=(314, 318), anchor="end")
    add(find("saga_select", "saga_select"), path="M310 223 C304 190, 348 190, 342 223",
        heads=[((342, 223), (348, 190)), ((310, 223), (304, 190))],
        chip=("swipe left / right", 326, 196))
    add(find("base_select", "base_select"), path="M310 421 C304 454, 348 454, 342 421",
        heads=[((342, 421), (348, 454)), ((310, 421), (304, 454))],
        chip=("swipe left / right", 326, 446))
    add(find("base_select", "cat_base"), [(400, 384), (548, 384)],
        label="enter selected chapter", at=(474, 372))
    add(find("cat_base", "base_select"), [(548, 400), (400, 400)])

    # Cat Base spokes: the forward control above, the way back below
    for dst, lab in (("upgrade", "Upgrade"), ("organize_cats", "Equip"),
                     ("catnip_challenges", "Missions"), ("storage", "Storage")):
        y = LAYOUT[dst][1]
        add(find("cat_base", dst), [(640, y - 8), (752, y - 8)], label=lab, at=(696, y - 18))
        add(find(dst, "cat_base"), [(752, y + 8), (640, y + 8)])
    add(find("cat_base", "menu"), [(640, 92), (752, 92)], label="Menu", at=(696, 82))
    add(find("menu", "cat_base"), [(752, 108), (640, 108)], label="Close", at=(696, 126))
    add(find("menu", "cat_guide"), [(900, 100), (996, 100)], label="Cat Guide", at=(948, 90))
    add(find("cat_guide", "cat_base"), [(1070, 71), (1070, 46), (640, 46)])

    # GAMATOTO: one tap, two recorded outcomes
    add(find("cat_base", "gamatoto") + find("cat_base", "gamatoto_ongoing"),
        [(640, 478), (722, 478)], label="GAMATOTO", at=(689, 468), head=False,
        trunk=True, diamond=(728, 478))
    add(find("cat_base", "gamatoto"), [(728, 472), (728, 448), (752, 448)])
    add(find("cat_base", "gamatoto_ongoing"), [(728, 484), (728, 508), (752, 508)])
    add(find("gamatoto", "cat_base"), [(752, 432), (640, 432)])
    add(find("gamatoto_ongoing", "cat_base"), [(752, 524), (640, 524)])
    add(find("gamatoto_report", "gamatoto"), [(996, 440), (900, 440)], label="Rewards",
        at=(948, 430), zone=True)

    # Capsule machines
    add(find("cat_base", "rare_capsules"), [(640, 632), (996, 632)], label="Rare Capsule", at=(700, 622))
    add(find("rare_capsules", "cat_base"), [(996, 648), (640, 648)])
    add(find("platinum_capsules", "cat_base"), [(996, 792), (640, 792)])
    add(find("rare_capsules", "storage"), [(1012, 669), (1012, 708), (900, 708)],
        label="Storage", at=(954, 698), zone=True)
    add(find("platinum_capsules", "storage"), [(1012, 763), (1012, 724), (900, 724)],
        label="Storage", at=(954, 742), zone=True)
    add(find("rare_capsules", "platinum_capsules"), [(1056, 669), (1056, 763)])
    add(find("platinum_capsules", "rare_capsules"), [(1084, 763), (1084, 669)])
    add(find("rare_capsules", "platinum_capsules") + find("platinum_capsules", "rare_capsules"),
        chip=("banner picker", 1070, 716), chip_only=True)
    add(find("roll_result", "sent_to_storage"), [(900, 912), (996, 912)], label="Ok",
        at=(948, 902), zone=True)
    add(find("sent_to_storage", "rare_capsules") + find("sent_to_storage", "platinum_capsules"),
        [(1070, 883), (1070, 859)], label="Ok", at=(1060, 876), anchor="end",
        head=False, trunk=True, diamond=(1070, 853), zone=True)
    add(find("sent_to_storage", "platinum_capsules"), [(1070, 847), (1070, 821)])
    add(find("sent_to_storage", "rare_capsules"),
        [(1076, 853), (1166, 853), (1166, 640), (1144, 640)])
    return E


# -- sagas and chapters: this save's carousels, laid out as rows ----------------------

PANEL_X0, PANEL_X1, PANEL_TOP = 24, 530, 496
ROW, CARD_H, SAGA_W, STRIP_X, GAP = 66, 48, 136, 196, 22


def _panel(screens, trans, find, pos, sizes) -> tuple[list[Edge], list, float]:
    """One row per saga: the saga card, then its chapters or whatever it opens.

    Returns the edges, the zone to draw behind the rows, and the y the panel
    ends at. Edges to screens elsewhere on the map become short stubs whose
    label names the far end, so nothing has to cross the diagram.
    """
    E: list[Edge] = []

    def add(tids, pts=None, **kw):
        if tids:
            E.append(Edge(tids=tids, pts=pts, **kw))

    def both(a, b):
        return find(a, b) + find(b, a)

    sagas = [n for n in screens if n.startswith("saga:")]
    top = PANEL_TOP + 84
    y = top
    for i, saga in enumerate(sagas):
        cy = top + i * ROW
        pos[saga] = (PANEL_X0, cy)
        sizes[saga] = (SAGA_W, CARD_H)
        key = saga.split(":", 1)[1]
        chapters = sorted((n for n in screens if n.startswith(f"chapter:{key}:")),
                          key=lambda n: int(n.rsplit(":", 1)[1]))
        opens = [t.dst for t in trans if t.src == saga and t.dst != HUB
                 and t.label == "enter selected saga" and not t.dst.startswith("chapter:")]
        strip = chapters or [d for d in dict.fromkeys(opens) if d not in pos]
        if strip:
            w = min(118, (PANEL_X1 - STRIP_X - (len(strip) - 1) * GAP) / len(strip))
            xs = [STRIP_X + k * (w + GAP) for k in range(len(strip))]
            for k, name in enumerate(strip):
                pos[name] = (xs[k], cy)
                sizes[name] = (w, CARD_H)
            add(find(saga, strip[0]), [(PANEL_X0 + SAGA_W, cy - 7), (STRIP_X, cy - 7)])
            add(sum((find(n, saga) for n in strip), []),
                [(STRIP_X, cy + 7), (PANEL_X0 + SAGA_W, cy + 7)])
            for k in range(len(strip) - 1):
                a, b = (xs[k] + w, cy), (xs[k + 1], cy)
                add(both(strip[k], strip[k + 1]), [a, b], head=False, heads=[(b, a), (a, b)])
            if chapters and "chapter_back_card" in screens:
                x0 = xs[0] + 14
                add(find(chapters[0], "chapter_back_card"),
                    [(x0, cy + CARD_H / 2), (x0, cy + CARD_H / 2 + 12)],
                    label="\u2190 Back card", at=(x0 + 7, cy + CARD_H / 2 + 14),
                    anchor="start", stub=True)
            end = xs[-1] + w
        else:
            end = PANEL_X0 + SAGA_W
        home = sum((find(n, HUB) for n in [saga] + strip), [])
        add(home, [(end, cy), (BUS_L, cy)])
        if i + 1 < len(sagas):
            a, b = (PANEL_X0 + 34, cy + CARD_H / 2), (PANEL_X0 + 34, cy + ROW - CARD_H / 2)
            add(both(saga, sagas[i + 1]), [a, b], head=False, heads=[(b, a), (a, b)])
        y = cy

    if sagas:
        first_top = top - CARD_H / 2
        add(sum((find(s, "title") for s in sagas), []),
            [(PANEL_X0 + 16, first_top), (PANEL_X0 + 16, first_top - 30)],
            label="\u2191 X to title, from any saga card", at=(PANEL_X0 + 60, first_top - 7),
            anchor="start", stub=True)
        add(find("saga_select", sagas[0]),
            [(PANEL_X0 + 48, first_top - 30), (PANEL_X0 + 48, first_top)],
            label="\u2193 from saga_select: drag to the first card",
            at=(PANEL_X0 + 60, first_top - 21), anchor="start", stub=True)

    # Base screens that belong with the carousels, when no row has taken them.
    for name in ("stage_reward_notice", "chapter_back_card"):
        if name not in screens or name in pos:
            continue
        y = (y + ROW) if sagas or name != "stage_reward_notice" else top
        pos[name] = (PANEL_X0, y)
        sizes[name] = (SAGA_W, CARD_H)
        r = PANEL_X0 + SAGA_W
        if name == "stage_reward_notice":
            add(find(name, HUB), [(r, y), (BUS_L, y)], label="Ok", at=(r + 40, y - 8))
        else:
            add(find(name, "saga_select"), [(r, y - 7), (r + 26, y - 7)],
                label="tap the card \u2192 saga_select", at=(r + 32, y - 3), anchor="start", stub=True)
            add(find("base_select", name), [(r + 26, y + 9), (r, y + 9)],
                label="from base_select: drag to the start", at=(r + 32, y + 13),
                anchor="start", stub=True)

    zone = (PANEL_X0 - 12, PANEL_TOP, PANEL_X1 - PANEL_X0 + 18, y + CARD_H / 2 + 22 - PANEL_TOP,
            "Sagas and chapters \u00b7 this save" if sagas else "Carousel screens")
    return E, zone, y + CARD_H / 2 + 22


# -- geometry -----------------------------------------------------------------------

esc = html.escape
HEAD_L, HEAD_W = 7.5, 3.8


def _unit(ax, ay, bx, by):
    d = math.hypot(bx - ax, by - ay) or 1.0
    return (bx - ax) / d, (by - ay) / d


def _rounded(pts, r=9.0, trim_end=0.0) -> str:
    """Polyline with rounded corners, optionally stopping short for an arrowhead."""
    pts = [(float(x), float(y)) for x, y in pts]
    if trim_end:
        ux, uy = _unit(*pts[-2], *pts[-1])
        pts[-1] = (pts[-1][0] - ux * trim_end, pts[-1][1] - uy * trim_end)
    out = [f"M{pts[0][0]:.1f} {pts[0][1]:.1f}"]
    for i in range(1, len(pts) - 1):
        (x0, y0), (x1, y1), (x2, y2) = pts[i - 1], pts[i], pts[i + 1]
        d1, d2 = math.hypot(x1 - x0, y1 - y0), math.hypot(x2 - x1, y2 - y1)
        rr = min(r, d1 / 2, d2 / 2)
        ax, ay = x1 - (x1 - x0) / d1 * rr, y1 - (y1 - y0) / d1 * rr
        bx, by = x1 + (x2 - x1) / d2 * rr, y1 + (y2 - y1) / d2 * rr
        out.append(f"L{ax:.1f} {ay:.1f} Q{x1:.1f} {y1:.1f} {bx:.1f} {by:.1f}")
    out.append(f"L{pts[-1][0]:.1f} {pts[-1][1]:.1f}")
    return " ".join(out)


def _arrowhead(tip, frm) -> str:
    ux, uy = _unit(*frm, *tip)
    bx, by = tip[0] - ux * HEAD_L, tip[1] - uy * HEAD_L
    px, py = -uy, ux
    pts = [tip, (bx + px * HEAD_W, by + py * HEAD_W), (bx - px * HEAD_W, by - py * HEAD_W)]
    return '<polygon class="head" points="' + " ".join(f"{x:.1f},{y:.1f}" for x, y in pts) + '"/>'


def _text(cls, x, y, s, anchor="middle", extra="") -> str:
    return f'<text class="{cls}" x="{x:.1f}" y="{y:.1f}" text-anchor="{anchor}"{extra}>{esc(s)}</text>'


def _noentry(x, y, r=6.0) -> str:
    d = r * 0.65
    return (f'<g class="noentry"><circle cx="{x}" cy="{y}" r="{r}"/>'
            f'<line x1="{x - d:.1f}" y1="{y + d:.1f}" x2="{x + d:.1f}" y2="{y - d:.1f}"/></g>')


def _clip(box, frm, to):
    """Where the segment from the box centre toward `to` leaves the box."""
    x, y, w, h = box
    cx, cy = x + w / 2, y + h / 2
    dx, dy = to[0] - frm[0], to[1] - frm[1]
    t = min(w / 2 / abs(dx) if dx else math.inf, h / 2 / abs(dy) if dy else math.inf)
    return cx + dx * t, cy + dy * t


# -- the drawing ----------------------------------------------------------------------

def anchors_text(screen) -> str:
    bits = []
    if screen.anchors:
        bits.append(f"{len(screen.anchors)} anchor" + ("s" if len(screen.anchors) > 1 else ""))
    if screen.absent:
        bits.append(f"{len(screen.absent)} absent")
    text = " · ".join(bits) or "no anchors"
    return f"off limits · {text}" if screen.forbidden else text


def title_text(screen) -> str:
    return f"“{screen.title}”" if screen.title else "no title"


def flags(name: str, screen) -> list[str]:
    out = []
    if name == "opening":
        out.append("first launch")
    if name == HUB:
        out.append("home")
    if screen.reactive:
        out.append("reactive")
    if screen.forbidden:
        out.append("off limits")
    return out


@dataclass
class Drawing:
    svg: str
    order: list[str]
    warnings: list[str]


def render_svg(graph: UIGraph, svg_id: str = "map") -> Drawing:
    screens, trans = graph.screens, graph.transitions
    warnings: list[str] = []

    def find(src, dst):
        return [i for i, t in enumerate(trans) if t.src == src and t.dst == dst]

    pos = {n: p for n, p in LAYOUT.items() if n in screens}
    sizes: dict[str, tuple[float, float]] = {}
    edges = _layout_edges(find)
    panel_edges, panel_zone, panel_end = _panel(screens, trans, find, pos, sizes)
    edges += panel_edges
    zones = ZONES + [panel_zone]

    # The purchase offer sits under the carousels; the Cat Base reaches down to it.
    bus_bot = BUS_BOT
    if "purchase_offer" in screens:
        py = max(716, panel_end + 60)
        pos["purchase_offer"] = (C2, py)
        edges.append(Edge(tids=find("purchase_offer", HUB), pts=[(C2 + NW, py), (BUS_L, py)]))
        bus_bot = max(BUS_BOT, py + 30)
    height = max(VBH, bus_bot + 110)

    # Screens the layout has no place for go in a strip along the bottom.
    unplaced = [n for n in screens if n not in pos and n != HUB]
    strip_top = height
    for k, name in enumerate(unplaced):
        col, row = k % 7, k // 7
        pos[name] = (C1 + col * (NW + 20), strip_top + 50 + row * (NH + 40))
        height = max(height, strip_top + 50 + row * (NH + 40) + NH + 20)
    if unplaced:
        warnings.append(f"no place in LAYOUT for: {', '.join(unplaced)}")

    def box(name):
        if name == HUB:
            return (BUS_L, BUS_TOP, BUS_R - BUS_L, bus_bot - BUS_TOP)
        x, cy = pos[name]
        w, h = sizes.get(name, (NW, NH))
        return (x, cy - h / 2, w, h)
    drawn = {i for e in edges if not e.trunk and not e.chip_only for i in e.tids}

    # Anything the hand layout does not route is drawn straight, so nothing is lost.
    auto = [i for i in range(len(trans)) if i not in drawn and trans[i].src in screens
            and trans[i].dst in screens]
    for i in auto:
        t = trans[i]
        bs, bd = box(t.src), box(t.dst)
        if t.src == t.dst:
            x, y, w, _h = bs
            edges.append(Edge(tids=[i], path=f"M{x + w - 30} {y} C{x + w - 30} {y - 30}, "
                              f"{x + w + 10} {y - 30}, {x + w - 10} {y}",
                              heads=[((x + w - 10, y), (x + w + 10, y - 30))],
                              label=t.label, at=(x + w - 20, y - 28), auto=True))
            continue
        cs = (bs[0] + bs[2] / 2, bs[1] + bs[3] / 2)
        cd = (bd[0] + bd[2] / 2, bd[1] + bd[3] / 2)
        ux, uy = _unit(*cs, *cd)
        off = (-uy * 5, ux * 5)                          # keep A->B and B->A apart
        a = _clip(bs, cs, cd)
        b = _clip(bd, cd, cs)
        a, b = (a[0] + off[0], a[1] + off[1]), (b[0] + off[0], b[1] + off[1])
        edges.append(Edge(tids=[i], pts=[a, b], label=t.label,
                          at=((a[0] + b[0]) / 2, (a[1] + b[1]) / 2 - 5), auto=True))
    if auto:
        warnings.append("drawn without a route in EDGES: " + ", ".join(
            f"{trans[i].src} --{trans[i].label}--> {trans[i].dst}" for i in auto))

    def kind(e: Edge) -> str:
        ts = [trans[i] for i in e.tids]
        if any(screens[t.dst].forbidden for t in ts):
            return "blocked"
        if e.chip_only or any(t.action for t in ts):
            return "routine"
        if all(t.label == "Back" for t in ts):
            return "back"
        return "tap"

    def edge_svg(k: int, e: Edge) -> str:
        cls = (f"edge kind-{kind(e)}" + (" trunk" if e.trunk else "")
               + (" chip-only" if e.chip_only else "") + (" in-zone" if e.zone else "")
               + (" auto" if e.auto else ""))
        out = [f'<g class="{cls}" data-e="{k}" data-t="{",".join(map(str, e.tids))}">']
        d = e.path or (_rounded(e.pts, trim_end=HEAD_L * 0.7 if e.head else 0) if e.pts else None)
        if d:
            out.append(f'<path class="hit" d="{d}"/><path class="line" d="{d}"/>')
        if e.heads:
            out += [_arrowhead(tip, frm) for tip, frm in e.heads]
        elif e.pts and e.head:
            out.append(_arrowhead(e.pts[-1], e.pts[-2]))
        if e.diamond:
            x, y = e.diamond
            out.append(f'<polygon class="diamond" points="{x},{y - 6} {x + 6},{y} {x},{y + 6} {x - 6},{y}"/>')
        if e.icon:
            out.append(_noentry(*e.icon))
        if e.chip:
            s, x, y = e.chip
            w = len(s) * 5.9 + 14
            out.append(f'<g class="chip" data-cx="{x}"><rect x="{x - w / 2:.1f}" y="{y - 9}" '
                       f'width="{w:.1f}" height="18" rx="9"/>{_text("chip-text", x, y + 3.6, s)}</g>')
        if e.label:
            out.append(_text("elabel", *e.at, e.label, e.anchor))
        if e.lines:
            x, y = e.at
            spans = "".join(f'<tspan x="{x}" dy="{0 if n == 0 else 13}">{esc(s)}</tspan>'
                            for n, s in enumerate(e.lines))
            out.append(f'<text class="elabel" x="{x}" y="{y}" text-anchor="{e.anchor}">{spans}</text>')
        out.append("</g>")
        return "".join(out)

    def node_svg(name: str) -> str:
        s = screens[name]
        cls = ["node"] + (["reactive"] if s.reactive else []) + \
              (["forbidden"] if s.forbidden else []) + (["hub"] if name == HUB else [])
        aria = f"{name}: title {title_text(s)}, {anchors_text(s)}" + (f". {s.note}" if s.note else "")
        x, y, w, h = box(name)
        cx = x + w / 2
        out = [f'<g class="{" ".join(cls)}" data-id="{name}" tabindex="0" role="button" '
               f'aria-label="{esc(aria)}">',
               f'<rect class="shadow" x="{x + 2}" y="{y + 2}" width="{w}" height="{h}" rx="{12 if name == HUB else 9}"/>',
               f'<rect class="box" x="{x}" y="{y}" width="{w}" height="{h}" rx="{12 if name == HUB else 9}"/>']
        ocr_cls = "node-ocr" + ("" if s.title else " none")
        if name == HUB:
            mid = (BUS_TOP + min(bus_bot, BUS_BOT)) / 2 + 30
            out += [_text("node-id", cx, y + 30, name),
                    _text(ocr_cls, cx, y + 47, title_text(s), extra=f' data-max="{w - 10}"'),
                    _text("node-ev", cx, y + 61, anchors_text(s), extra=f' data-max="{w - 10}"'),
                    f'<text class="hub-note" x="{cx}" y="{mid}" text-anchor="middle" '
                    f'transform="rotate(-90 {cx} {mid})">home · every screen routes back here</text>']
        elif name in sizes:
            cy = y + h / 2
            if name.startswith("saga:"):
                top_line, sub = s.title or name, f"saga card {list(pos).index(name) + 1}"
                sub = s.note.split(", ", 1)[-1] if s.note else sub
            elif name.startswith("chapter:"):
                top_line, sub = f"Chapter {name.rsplit(':', 1)[1]}", s.title or ""
            else:
                top_line, sub = name, title_text(s)
            cls_top = "node-id" if not name.startswith(("saga:", "chapter:")) else "card-name"
            out += [_text(cls_top, cx, cy - 4, top_line, extra=f' data-max="{w - 12}"'),
                    _text("card-sub", cx, cy + 12, sub, extra=f' data-max="{w - 12}"')]
        else:
            cy = y + h / 2
            out += [_text("node-id", cx, cy - 9, name),
                    _text(ocr_cls, cx, cy + 6, title_text(s), extra=f' data-max="{w - 16}"'),
                    _text("node-ev", cx, cy + 20, anchors_text(s), extra=f' data-max="{w - 16}"')]
            if s.forbidden:
                out.append(_noentry(x + 15, cy - 13))
        out.append("</g>")
        return "".join(out)

    parts = []
    for zx, zy, zw, zh, label in zones:
        parts.append(f'<g class="zone"><rect x="{zx}" y="{zy}" width="{zw}" height="{zh}" rx="14"/>'
                     + _text("zone-label", zx + 12, zy + 16, label, "start") + "</g>")
    parts.append('<g class="stubs">')
    stubs = list(STUBS)
    if "purchase_offer" in pos:
        px, py = pos["purchase_offer"]
        stubs.append(("purchase_offer", [(px + NW / 2, py + 74), (px + NW / 2, py + NH / 2)],
                      "offer pops up", (px + NW / 2, py + 88), "middle"))
    for name, pts, text, at, anchor in stubs:
        if name in screens and screens[name].reactive and name in pos:
            parts.append(f'<g class="stub" data-for="{name}"><path class="line" '
                         f'd="{_rounded(pts, trim_end=HEAD_L * 0.7)}"/>' + _arrowhead(pts[1], pts[0])
                         + _text("slabel", *at, text, anchor) + "</g>")
    if "opening" in pos:
        parts.append('<g class="stub" data-for="opening"><circle class="entry-dot" cx="222" cy="100" r="5"/>'
                     f'<path class="line solid" d="{_rounded([(216, 100), (172, 100)], trim_end=HEAD_L * 0.7)}"/>'
                     + _arrowhead((172, 100), (216, 100)) + _text("slabel", 232, 104, "first launch", "start") + "</g>")
    parts.append('</g><g class="edges">')
    parts += [edge_svg(k, e) for k, e in enumerate(edges)]
    order = [n for n in ORDER if n in screens]
    order += [n for n in pos if n not in order and n in screens] + [n for n in unplaced if n not in pos]
    parts.append('</g><g class="nodes">')
    parts += [node_svg(n) for n in order if n in pos or n == HUB]
    parts.append(f'</g><g class="badges" id="{svg_id}-badges"></g>')

    svg = (f'<svg id="{svg_id}" class="ui-map" viewBox="0 0 {VBW} {height}" role="group" '
           f'aria-label="UI map: {len(screens)} screens, {len(trans)} transitions" '
           f'xmlns="http://www.w3.org/2000/svg">' + "".join(parts) + "</svg>")
    return Drawing(svg=svg, order=order, warnings=warnings)


def map_data(graph: UIGraph) -> dict:
    """Everything the page scripts need, routes included, as plain JSON."""
    screens, trans = graph.screens, graph.transitions
    index = {id(t): i for i, t in enumerate(trans)}
    routes: dict[str, list[int] | None] = {}
    for a in screens:
        for b in screens:
            if a != b:
                try:
                    routes[f"{a}>{b}"] = [index[id(t)] for t in graph.route(a, b)]
                except NoRoute:
                    routes[f"{a}>{b}"] = None

    def control(t):
        return (t.src, round(t.x, 3), round(t.y, 3))

    siblings = {i: [j for j, u in enumerate(trans) if j != i and not t.action and not u.action
                    and control(u) == control(t) and u.dst != t.dst]
                for i, t in enumerate(trans)}
    home = {n: 0 if n == HUB else (None if routes.get(f"{n}>{HUB}") is None
                                   else len(routes[f"{n}>{HUB}"]))
            for n in screens}
    return dict(
        screens={n: dict(title=s.title, anchors=list(s.anchors), absent=list(s.absent),
                         forbidden=s.forbidden, reactive=s.reactive, note=s.note)
                 for n, s in screens.items()},
        transitions=[dict(src=t.src, dst=t.dst, x=t.x, y=t.y, label=t.label,
                          settle=t.settle, action=t.action) for t in trans],
        routes=routes, home=home, siblings=siblings,
    )


# -- the standalone page -------------------------------------------------------------

def _git(*args: str) -> str:
    try:
        return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True,
                              text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def build_page(graph: UIGraph) -> tuple[str, list[str]]:
    drawing = render_svg(graph)
    data = map_data(graph)
    data["order"] = drawing.order
    screens, trans = graph.screens, graph.transitions
    data["start"] = ["title" if "title" in screens else drawing.order[0],
                     "rare_capsules" if "rare_capsules" in screens else drawing.order[-1]]

    home = [v for v in data["home"].values()]
    stranded = [n for n, v in data["home"].items() if v is None]
    if stranded:
        home_fact = f"<b>{len(stranded)}</b> screens cannot reach {HUB}"
    else:
        home_fact = f"{HUB} within <b>{max(home)}</b> steps of every screen"

    commit = _git("log", "-1", "--format=%h", "--", "data/ui_graph.json") or "uncommitted"
    date = _git("log", "-1", "--format=%cd", "--date=format:%-d %b %Y", "--", "data/ui_graph.json")
    if _git("status", "--porcelain", "--", "data/ui_graph.json"):
        commit += " + uncommitted edits"

    def td(s, cls=""):
        return f'<td class="{cls}">{esc(str(s))}</td>'

    screen_rows = "".join(
        "<tr>" + td(n, "mono") + td(title_text(s) if s.title else "—")
        + td(", ".join(s.anchors) or "—", "mono") + td(", ".join(s.absent) or "—", "mono")
        + td(", ".join(flags(n, s)) or "—")
        + td("—" if data["home"][n] is None else data["home"][n], "num")
        + td(s.note or "—") + "</tr>"
        for n, s in ((n, screens[n]) for n in drawing.order))
    trans_rows = "".join(
        "<tr>" + td(i, "num") + td(t.src, "mono") + td(t.label) + td(t.dst, "mono")
        + td("routine" if t.action else "tap")
        + td(t.action if t.action else f"({t.x:.3f}, {t.y:.3f})", "mono")
        + td(f"{t.settle:.1f}", "num") + "</tr>"
        for i, t in enumerate(trans))
    n_routine = sum(bool(t.action) for t in trans)
    values = {
        "CSS": CSS_FILE.read_text(),
        "SVG": drawing.svg,
        "DATA": json.dumps(data, separators=(",", ":")).replace("</", "<\\/"),
        "OPTIONS": "".join(f'<option value="{n}">{n}</option>' for n in drawing.order),
        "COMMIT": esc(commit),
        "DATE": esc(date),
        "N_SCREENS": str(len(screens)),
        "N_TRANS": str(len(trans)),
        "N_TAP": str(len(trans) - n_routine),
        "N_ROUTINE": str(n_routine),
        "N_TITLED": str(sum(bool(s.title) for s in screens.values())),
        "N_REACT": str(sum(s.reactive for s in screens.values())),
        "N_FORB": str(sum(s.forbidden for s in screens.values())),
        "HOME_FACT": home_fact,
        "SCREEN_ROWS": screen_rows,
        "TRANS_ROWS": trans_rows,
    }
    page = PAGE_TEMPLATE.read_text()
    for key, value in values.items():
        page = page.replace("{{" + key + "}}", value)
    return page, drawing.warnings


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT, help=f"default: {DEFAULT_OUT}")
    ap.add_argument("--graph", type=Path, default=None, help="map to draw (default: data/ui_graph.json)")
    ap.add_argument("--carousels", type=Path, default=None,
                    help="sagas and chapters to layer on (default: state/carousels.json)")
    args = ap.parse_args()
    page, warnings = build_page(UIGraph.load(args.graph, carousels=args.carousels or True))
    for w in warnings:
        print(f"warning: {w}", file=sys.stderr)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(page)
    print(f"{args.out} ({len(page):,} bytes)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

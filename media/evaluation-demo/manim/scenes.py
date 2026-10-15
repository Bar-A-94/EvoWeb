"""The two academic pieces of the EvoWeb evaluation demo, rendered by Manim on a transparent
background and composited by Remotion.

    manim -qh -t --fps 30 -r 1920,1080 scenes.py Timeline Sweep
"""

import json
from pathlib import Path

from manim import (
    DOWN, LEFT, RIGHT, UP, UR, ORIGIN,
    Arrow, Axes, Create, DashedLine, FadeIn, FadeOut, GrowArrow, Line, Polygon, Rectangle,
    RoundedRectangle, Scene, Text, VGroup, Write, config, rate_functions, smooth,
)

DATA = json.loads((Path(__file__).resolve().parents[1] / "public" / "data.json").read_text())
NAVY = "#1f3a5f"
INK = "#2b3a4a"
MUTED = "#6b7a8c"
NODE_FILL = ["#dbe8f7", "#f9dede", "#dff0e3", "#e9e2f5", "#fbe9c9"]
NODE_EDGE = ["#2f5f8f", "#c05a5a", "#3f8f5f", "#7a5fa8", "#c08a2f"]
FUNCTIONAL, INTEGRATION, BACKWARD = "#2f5f8f", "#3f8f5f", "#c08a2f"
FONT = "Helvetica Neue"




def node(label: str, sub: str, i: int, width: float = 1.3) -> VGroup:
    box = RoundedRectangle(corner_radius=0.16, width=width, height=1.0, stroke_width=2.2)
    box.set_fill(NODE_FILL[i % 5], opacity=1).set_stroke(NODE_EDGE[i % 5])
    t = Text(label, font=FONT, weight="BOLD", color=NAVY).scale(0.42).move_to(box).shift(UP * 0.16)
    s = Text(sub, font=FONT, color=INK).scale(0.2).move_to(box).shift(DOWN * 0.2)
    return VGroup(box, t, s)


class Timeline(Scene):
    """The ten requests of one app, drawn left to right, as in Figure 1 (B)."""

    def construct(self):
        title = Text("Evaluating an evolving application", font=FONT, weight="BOLD", color=NAVY)
        title.scale(0.9).to_edge(UP, buff=0.9)
        sub = Text(
            "one app  ·  10 user requests  ·  after each, 5 browser checks",
            font=FONT, color=MUTED,
        ).scale(0.42).next_to(title, DOWN, buff=0.3)
        self.play(Write(title, run_time=1.1), FadeIn(sub, shift=UP * 0.1, run_time=0.8))

        labels = [
            ("R1", "Seed app"), ("R2", "Derived feature"), ("R3", "Interactive tool"),
            ("R4", "Multi-page flow"), ("R5", "…"), ("R6", "…"), ("R7", "…"), ("R8", "…"),
            ("R9", "…"), ("R10", "Final feature"),
        ]
        nodes = VGroup(*[node(l, s, i) for i, (l, s) in enumerate(labels)])
        nodes.arrange(RIGHT, buff=0.2).scale_to_fit_width(12.4).move_to(ORIGIN).shift(DOWN * 0.1)
        axis = Line(nodes.get_left() + LEFT * 0.2, nodes.get_right() + RIGHT * 0.3, color=NAVY, stroke_width=5)
        axis.shift(UP * 1.1)
        head = Polygon(axis.get_end(), axis.get_end() + LEFT * 0.35 + UP * 0.18,
                       axis.get_end() + LEFT * 0.35 + DOWN * 0.18, color=NAVY, fill_opacity=1)
        self.play(Create(axis, run_time=0.8), FadeIn(head, run_time=0.2))
        for i, n in enumerate(nodes):
            self.play(FadeIn(n, shift=UP * 0.15, run_time=0.16))
            if i < len(nodes) - 1:
                a = Arrow(n.get_right(), nodes[i + 1].get_left(), buff=0.03, stroke_width=2.5,
                          max_tip_length_to_length_ratio=0.5, color=NAVY)
                self.play(GrowArrow(a, run_time=0.08))
        foot = Text(
            "each request may depend on earlier ones: the app must keep working as it grows",
            font=FONT, color=INK,
        ).scale(0.4).next_to(nodes, DOWN, buff=0.9)
        self.play(FadeIn(foot, run_time=0.6))
        self.wait(0.7)


class Sweep(Scene):
    """Trajectory performance for one app: the survival curve over user-tolerance thresholds,
    its area (Survival), and the quality curve's area (Grade)."""

    def construct(self):
        s = DATA["scores"]
        th = s["thresholds"]
        surv = s["s_sweep"]
        qual = s["q_sweep"]

        title = Text("Trajectory performance", font=FONT, weight="BOLD", color=NAVY).scale(0.8)
        title.to_edge(UP, buff=0.7)
        sub = Text("aggregate over user-tolerance thresholds", font=FONT, color=MUTED).scale(0.4)
        sub.next_to(title, DOWN, buff=0.22)
        self.play(Write(title, run_time=0.8), FadeIn(sub, run_time=0.5))

        def panel(ylabel, ymax, ystep, curve, color, pos, area_label, area_value):
            ax = Axes(
                x_range=[0, 100, 25], y_range=[0, ymax, ystep], x_length=5.2, y_length=3.2,
                axis_config={"color": INK, "stroke_width": 2, "include_tip": False, "label_constructor": Text,
                             "font_size": 22, "decimal_number_config": {"num_decimal_places": 0}},
            ).move_to(pos)
            ax.add_coordinates()
            for lab in list(ax.get_x_axis().numbers) + list(ax.get_y_axis().numbers):
                lab.set_fill(INK, opacity=1).set_stroke(width=0)
            xl = Text("tolerance threshold t (%)", font=FONT, color=INK).scale(0.3).next_to(ax, DOWN, buff=0.15)
            yl = Text(ylabel, font=FONT, color=INK).scale(0.3).rotate(90 * 3.14159 / 180).next_to(ax, LEFT, buff=0.15)
            pts = [ax.c2p(t, v) for t, v in zip(th, curve)]
            graph = VGroup(*[Line(pts[i], pts[i + 1], color=color, stroke_width=4) for i in range(len(pts) - 1)])
            base = [ax.c2p(th[0], 0)] + pts + [ax.c2p(th[-1], 0)]
            area = Polygon(*base, color=color, fill_opacity=0.18, stroke_width=0)
            lab = Text(f"{area_label} = area = {area_value}", font=FONT, weight="BOLD", color=color).scale(0.4)
            lab.next_to(ax, UP, buff=0.18)
            return ax, xl, yl, graph, area, lab

        left = LEFT * 3.4 + DOWN * 0.3
        right = RIGHT * 3.4 + DOWN * 0.3
        ax1, xl1, yl1, g1, a1, l1 = panel("requests survived S(t)", 10, 2, surv, NAVY, left, "Survival", f"{s['survival']:.2f}")
        ax2, xl2, yl2, g2, a2, l2 = panel("delivered checks Q(t) (%)", 100, 25, qual, INTEGRATION, right, "Grade", f"{s['grade']:.3f}")
        self.play(FadeIn(ax1), FadeIn(xl1), FadeIn(yl1), FadeIn(ax2), FadeIn(xl2), FadeIn(yl2), run_time=0.6)
        self.play(Create(g1, run_time=1.6, rate_func=rate_functions.linear),
                  Create(g2, run_time=1.6, rate_func=rate_functions.linear))
        self.play(FadeIn(a1), FadeIn(a2), run_time=0.6)
        self.play(FadeIn(l1, shift=UP * 0.1), FadeIn(l2, shift=UP * 0.1), run_time=0.6)

        foot = Text(
            f"app {DATA['app']} of {DATA['model']}:  Grade {s['grade']:.3f}   ·   Survival {s['survival']:.2f} of 10 requests",
            font=FONT, weight="BOLD", color=NAVY,
        ).scale(0.5).to_edge(DOWN, buff=0.55)
        note = Text("the benchmark reports the mean over 32 apps and 3 runs", font=FONT, color=MUTED).scale(0.34)
        note.next_to(foot, DOWN, buff=0.12)
        self.play(FadeIn(foot, shift=UP * 0.1, run_time=0.6), FadeIn(note, run_time=0.6))
        self.wait(1.4)

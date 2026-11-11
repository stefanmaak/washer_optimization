"""Dash GUI of the simulated cage2: start/stop of mock Chris, Gantt chart of the execution, coverage of all runs."""

import colorsys
import logging
import threading
import time
from datetime import datetime, timedelta

import numpy as np
import plotly.graph_objects as go
from dash import Dash, Input, Output, State, ctx, dcc, html, no_update

from interface_service.sim.lab import GanttBar, SimLab, SimRun
from interface_service.sim.mock_chris import MockChris
from interface_service.sim.settings import SimSettings

logger = logging.getLogger(__name__)

N_COLORS = 40
FADE = 2.0  # seconds (real time) in which finished runs fade out of the Gantt chart
REFRESH_MS = 250
SPEEDS = [0.25, 0.5, 1, 2, 4, 8, 16]
# as in cage2's orchestrator config (lab_adaption/config.py)
DEVICE_COLORS = {
    "PFonRail": "#d62728",
    "BlueWasher": "#002171",
    "Squid1": "#43a047",
    "Squid2": "#9ccc65",
    "Squid4": "#00897b",
}


def run_color(number: int, alpha: float = 1.0) -> str:
    """Rainbow from red to violet in N_COLORS steps, round robin over the run numbers."""
    hue = ((number - 1) % N_COLORS) / N_COLORS * 0.8
    r, g, b = colorsys.hsv_to_rgb(hue, 0.85, 0.9)
    return f"rgba({r * 255:.0f},{g * 255:.0f},{b * 255:.0f},{alpha:.2f})"


def gantt_figure(bars: list[GanttBar], now: datetime) -> go.Figure:
    """Like the orchestrator's Gantt chart: one row per plate, colored by device. Planned steps are hatched."""
    fig = go.Figure()
    wall_now = time.monotonic()
    for device in sorted({bar.device for bar in bars}, key=_device_order):
        device_bars = [bar for bar in bars if bar.device == device]
        fig.add_trace(go.Bar(
            name=device,
            orientation="h",
            y=[f"run {bar.run}" for bar in device_bars],
            base=[bar.start for bar in device_bars],
            x=[(bar.finish - bar.start).total_seconds() * 1000 for bar in device_bars],
            marker=dict(
                color=DEVICE_COLORS.get(device, "grey"),
                opacity=[_fade(bar, wall_now) * (0.45 if bar.planned else 1.0) for bar in device_bars],
                line=dict(width=0),
                pattern=dict(shape=["/" if bar.planned else "" for bar in device_bars], fgcolor="white", size=6),
            ),
            hovertext=[f"{bar.step}" + (" (planned)" if bar.planned else "") for bar in device_bars],
            hoverinfo="text+name",
        ))
    if bars:
        # from the first step of the oldest active run to the end of the schedule
        active = [bar for bar in bars if bar.finished_wall is None] or bars
        start = min(bar.start for bar in active)
        end = max(max(bar.finish for bar in bars), now + timedelta(seconds=5))
        fig.update_xaxes(range=[start, end])
    runs = sorted({bar.run for bar in bars})
    fig.add_shape(type="line", x0=now, x1=now, y0=0, y1=1, yref="paper", line=dict(color="black", width=2))
    fig.update_xaxes(type="date")
    fig.update_yaxes(categoryorder="array", categoryarray=[f"run {r}" for r in runs][::-1])
    fig.update_layout(
        title="Execution", height=140 + 45 * max(3, len(runs)), margin=dict(l=70, r=20, t=40, b=30),
        barmode="overlay", bargap=0.3, legend=dict(orientation="h", y=1.02, x=1, xanchor="right", yanchor="bottom"),
    )
    return fig


def _device_order(device: str) -> int:
    return list(DEVICE_COLORS).index(device) if device in DEVICE_COLORS else len(DEVICE_COLORS)


def _fade(bar: GanttBar, wall_now: float) -> float:
    if bar.finished_wall is None:
        return 1.0
    return max(0.0, 1 - (wall_now - bar.finished_wall) / FADE)


def coverage_figure(runs: list[SimRun]) -> go.Figure:
    fig = go.Figure()
    for run in runs:
        if not run.coverage_points:
            continue
        washes, coverage = zip(*run.coverage_points)
        color = run_color(run.number)
        fig.add_trace(go.Scatter(
            x=washes, y=coverage, mode="lines+markers+text", line=dict(color=color, width=2),
            marker=dict(size=6), name=f"run {run.number}",
            text=[""] * (len(washes) - 1) + [f"run {run.number}"], textposition="middle right",
            textfont=dict(color=color), hovertemplate=f"run {run.number}<br>wash %{{x}}: %{{y:.1f}} %<extra></extra>",
        ))
        if run.failed_empty_checks:
            failed = run.failed_empty_checks
            fig.add_trace(go.Scatter(
                x=failed, y=np.interp(failed, washes, coverage), mode="markers",
                marker=dict(symbol="x", size=10, color=color, line=dict(width=1, color="black")),
                hovertemplate=f"run {run.number}<br>wash %{{x}}: wells not empty<extra></extra>",
            ))
    fig.update_xaxes(title="wash", dtick=1, rangemode="tozero")
    fig.update_yaxes(title="cell coverage [%]")
    fig.update_layout(
        title="Coverage (× = wells not emptied)", height=480, margin=dict(l=70, r=20, t=40, b=40),
        showlegend=False, uirevision="coverage",
    )
    return fig


SPEED_BUTTON = dict(fontSize="18px", width="36px")


def create_gui(lab: SimLab, mock_chris: MockChris) -> Dash:
    app = Dash(__name__, title="Washing optimization (simulated cage2)")
    app.layout = html.Div(
        style=dict(fontFamily="sans-serif", margin="10px 20px"),
        children=[
            html.Div(
                style=dict(display="flex", alignItems="center", gap="16px"),
                children=[
                    html.H3("Washing optimization – simulated cage2", style=dict(margin="0")),
                    html.Button(id="start-stop", n_clicks=0, style=dict(fontSize="16px", padding="4px 16px")),
                    html.Span(id="state"),
                    html.Span(style=dict(marginLeft="auto"), children=[
                        html.Button("−", id="slower", n_clicks=0, style=SPEED_BUTTON),
                        html.Span(id="speed", style=dict(display="inline-block", width="80px", textAlign="center")),
                        html.Button("+", id="faster", n_clicks=0, style=SPEED_BUTTON),
                    ]),
                ],
            ),
            dcc.Graph(id="gantt", config=dict(displayModeBar=False)),
            dcc.Graph(id="coverage"),
            dcc.Interval(id="tick", interval=REFRESH_MS),
            dcc.Store(id="coverage-version", data=-1),
        ],
    )

    @app.callback(Output("start-stop", "n_clicks"), Input("start-stop", "n_clicks"), prevent_initial_call=True)
    def toggle(_clicks):
        mock_chris.set_running(not mock_chris.running)
        return no_update

    @app.callback(
        Output("speed", "children"),
        Input("slower", "n_clicks"),
        Input("faster", "n_clicks"),
    )
    def change_speed(_slower, _faster):
        index = SPEEDS.index(lab.clock.speed) if lab.clock.speed in SPEEDS else SPEEDS.index(1)
        if ctx.triggered_id == "slower":
            index = max(0, index - 1)
        elif ctx.triggered_id == "faster":
            index = min(len(SPEEDS) - 1, index + 1)
        lab.clock.speed = SPEEDS[index]
        return f"speed ×{SPEEDS[index]:g}"

    @app.callback(
        Output("start-stop", "children"),
        Output("state", "children"),
        Output("gantt", "figure"),
        Input("tick", "n_intervals"),
    )
    def update_execution(_n):
        now = lab.clock.now()
        state = f"mock Chris {'running' if mock_chris.running else 'stopped'} ({mock_chris.submitted} tests sent)"
        state += f", {lab.active_runs} runs active" + (", rescheduling" if lab.scheduling else "")
        label = "Stop mock Chris" if mock_chris.running else "Start mock Chris"
        return label, state, gantt_figure(lab.gantt_bars(FADE), now)

    @app.callback(
        Output("coverage", "figure"),
        Output("coverage-version", "data"),
        Input("tick", "n_intervals"),
        State("coverage-version", "data"),
    )
    def update_coverage(_n, shown_version):
        if lab.version == shown_version:
            return no_update, no_update
        version = lab.version
        return coverage_figure(lab.runs_snapshot()), version

    return app


def start_gui(lab: SimLab, mock_chris: MockChris, settings: SimSettings) -> None:
    app = create_gui(lab, mock_chris)
    thread = threading.Thread(
        target=app.run,
        kwargs=dict(host=settings.gui_host, port=settings.gui_port, debug=False),
        name="sim-gui",
        daemon=True,
    )
    thread.start()
    logger.info("simulation GUI on http://localhost:%d", settings.gui_port)

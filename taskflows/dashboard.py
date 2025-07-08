#!/usr/bin/env python
import json
from dataclasses import dataclass
from typing import List, Literal, Optional

import requests
from grafanalib._gen import DashboardEncoder
from grafanalib.core import Annotation, Annotations, Dashboard as GLDashboard, Graph, Target, Time
from taskflows.utils import logger
from .service import Service
from .config import config

@dataclass
class LogsPanel:
    service: Service
    height: Literal['sm', 'md', 'lg', 'xl'] = 'md'
    width_fr: Optional[float] = None  # Fraction of the width (e.g., 0.5 for half-width, 1.0 for full-width)    

    @property
    def height_no(self) -> int:
        if self.height == 'sm':
            return 5
        if self.height == 'md':
            return 10
        if self.height == 'lg':
            return 15
        if self.height == 'xl':
            return 20
        raise ValueError(f"Invalid height: {self.height}")

@dataclass
class LogsTextSearch(LogsPanel):
    text: str
    title: Optional[str] = None 

    def __post_init__(self):
        if self.title is None:
            self.title = f"{self.service.name}: {self.text}"     

@dataclass
class LogsCountPlot(LogsPanel):
    text: str
    period: str = "5m"  # e.g., "1m", "5m", etc.
    title: Optional[str] = None 

    def __post_init__(self):
        if self.title is None:
            self.title = f"{self.service.name}: {self.text} Counts"


class Dashboard:
    def __init__(self, title: str, panels_grid: List[LogsPanel | List[LogsPanel]]):
        self.title = title
        self.panels_grid = panels_grid

    def create(self):
        dashboard = self._create_gl_dashboard()
        resp = requests.post(
            f"http://{config.grafana_api_key}/api/dashboards/db", 
            data=json.dumps(
            {"dashboard": dashboard}, cls=DashboardEncoder, indent=2
        ).encode("utf-8"), headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.grafana_api_key}",
        }
        )
        if resp.status_code == 200:
            logger.info(f"{self.title} dashboard created/updated successfully")
        else:
            logger.error(f"Error creating/updating dashboard: {resp.status_code} - {resp.text}")

    def _create_gl_dashboard(self) -> GLDashboard:
        for panels in self.panels_grid:
            if isinstance(panels, LogsPanel):
                continue
            if not all(isinstance(p, LogsPanel) for p in panels):
                raise ValueError("panels_grid must be list[LogsPanel | List[LogsPanel]].")
            if len(panels) > 24:
                raise ValueError("Each row in panels_grid can have at most 24 panels.")
        panels = []
        y = 0
        for panels in self.panels_grid:
            if not isinstance(panels, (tuple, list)):
                panels = [panels]
            default_width_fr = 1 / len(panels)
            x = 0
            for panel in panels:
                if panel.width_fr is None:
                    panel.width_fr = default_width_fr
                expr = '{name="/{}"}'.format(panel.service.name)
                title = panel.service.name
                if isinstance(panel, (LogsCountPlot, LogsTextSearch)):
                    title = panel.title
                    expr += f' |= "{panel.text}"'
                if isinstance(panel, LogsCountPlot):
                    panels.append(Graph(
                        title=title,
                        targets=[
                            Target(
                                expr=f'count_over_time({expr}[{panel.period}])',
                                legendFormat="Count",
                                refId="A",
                            )
                        ],
                    ))
                w = int(panel.width_fr * 24)
                panels.append({
                    "datasource": {"type": "loki", "uid": "P982945308D3682D1"},
                    "fieldConfig": {"defaults": {}, "overrides": []},
                    "gridPos": {"h": panel.height_no, "w": w, "x": x, "y": y},
                    "options": {
                        "dedupStrategy": "none",
                        "enableInfiniteScrolling": False,
                        "enableLogDetails": True,
                        "prettifyLogMessage": False,
                        "showCommonLabels": False,
                        "showLabels": False,
                        "showTime": False,
                        "sortOrder": "Descending",
                        "wrapLogMessage": False,
                    },
                    "pluginVersion": "11.5.1",
                    "targets": [{
                        "datasource": {"type": "loki", "uid": "P982945308D3682D1"},
                        "editorMode": "builder",
                        "expr": expr,
                        "queryType": "range",
                        "refId": "A",
                        "direction": None,
                    }],
                    "title": title,
                    "type": "logs",
                })
                y += panel.height_no
                x += w
        return GLDashboard(
            title=title,
            uid="de9suz5qmqfpca",
            editable=True,
            fiscalYearStartMonth=0,
            graphTooltip=0,
            id=1,
            links=[],
            panels=panels,
            preload=False,
            refresh="1m",
            schemaVersion=40,
            tags=[],
            templating={"list": []},
            time=Time("now-24h", "now"),
            timepicker={},
            timezone="browser",
            version=20,
            weekStart="",
            annotations=Annotations(
                list=[
                    Annotation(
                        builtIn=1,
                        datasource={"type": "grafana", "uid": "-- Grafana --"},
                        enable=True,
                        hide=True,
                        iconColor="rgba(0, 211, 255, 1)",
                        name="Annotations & Alerts",
                        type="dashboard",
                    )
                ]
            )
        ).auto_panel_ids()

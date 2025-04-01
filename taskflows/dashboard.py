#!/usr/bin/env python
import json
import os
from dataclasses import dataclass
from typing import List, Literal, Optional, Union

import requests
from grafanalib._gen import DashboardEncoder
from grafanalib.core import Annotation, Annotations, Dashboard, Graph, Target, Time

from taskflows.service import Service


@dataclass
class ServiceLogsPanel:
    service: Service
    height: Literal['sm', 'md', 'lg', 'xl']
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
class LogsTextSearch(ServiceLogsPanel):
    text: str
    title: Optional[str] = None 

    def __post_init__(self):
        if self.title is None:
            self.title = f"{self.service.name}: {self.text}"

        

@dataclass
class LogsCountPlot(ServiceLogsPanel):
    text: str
    period: str = "5m"  # e.g., "1m", "5m", etc.
    title: Optional[str] = None 

    def __post_init__(self):
        if self.title is None:
            self.title = f"{self.service.name}: {self.text} Counts"


def create_dashboard(title: str, panels_grid: list[Union[ServiceLogsPanel, List[ServiceLogsPanel]]]) -> Dashboard:
    # check arg.
    for panels in panels_grid:
        if isinstance(panels, ServiceLogsPanel):
            continue
        if not all(isinstance(p, ServiceLogsPanel) for p in panels):
            raise ValueError("panels_grid must be list[Union[ServiceLogsPanel, List[ServiceLogsPanel]]].")
        if len(panels) > 24:
            raise ValueError("Each row in panels_grid can have at most 24 panels.")
    panels = []
    y = 0
    for panels in panels_grid:
        if not isinstance(panels, (tuple,list)):
            panels = [panels]
        # find width fraction of each panel.
        default_width_fr = 1 / len(panels)
        x = 0
        for panel in panels:
            if panel.width_fr is None:
                panel.width_fr = default_width_fr
            expr ='{name="/{}"}'.format(panel.serice.name)
            title = panel.service.name
            if isinstance(panel, (LogsCountPlot, LogsTextSearch)):
                title = panel.title
                expr += f' |= "{panel.text}"'
            if isinstance(panel, LogsCountPlot):
                # TODO grid pos and other?
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
                # TODO where to get uid?
                "datasource": {"type": "loki", "uid": "P982945308D3682D1"},
                "fieldConfig": {"defaults": {}, "overrides": []},
                "gridPos": {"h": panel.height_no, "w": w, "x": x, "y": y},
                #"id": panel_id,
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
                    # TODO what is this?
                    "direction": None,
                }],
                "title": title,
                "type": "logs",
            })
            y += panel.height_no
            x += w
    return Dashboard(
        title=title,
        # TODO generate?
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



def load_dashboard(dashboard):
    dashboard_json = json.dumps(
        {"dashboard": dashboard}, cls=DashboardEncoder, indent=2
    ).encode("utf-8")

    # Assuming Grafana is running locally on port 3000
    grafana_url = "http://localhost:3000/api/dashboards/db"
    grafana_api_key = os.environ.get("GRAFANA_API_KEY")  # Set your Grafana API key as an environment variable

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {grafana_api_key}",
    }

    response = requests.post(grafana_url, data=dashboard_json, headers=headers)

    if response.status_code == 200:
        print("Dashboard created/updated successfully")
    else:
        print(f"Error creating/updating dashboard: {response.status_code} - {response.text}")

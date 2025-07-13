import json
import uuid
from typing import List, Literal, Optional

import requests
from grafanalib._gen import DashboardEncoder
from grafanalib.core import (
    Annotations, Dashboard as GLDashboard, Graph, Target, Time, 
    GridPos, Logs
)

from pydantic import BaseModel
from taskflows import logger
from taskflows.common import sort_service_names
from . import Service
from taskflows.config import config

class LogsPanelConfig(BaseModel):
    model_config = {"arbitrary_types_allowed": True}
    
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

class LogsTextSearch(LogsPanelConfig):
    text: str
    title: Optional[str] = None

    def model_post_init(self, __context):
        if self.title is None:
            self.title = f"{self.service.name}: {self.text}"     

class LogsCountPlot(LogsPanelConfig):
    text: str
    period: str = "5m"  # e.g., "1m", "5m", etc.
    title: Optional[str] = None

    def model_post_init(self, __context):
        if self.title is None:
            self.title = f"{self.service.name}: {self.text} Counts"


class Dashboard:
    def __init__(self, title: str, panels_grid: List[LogsPanelConfig | List[LogsPanelConfig]]):
        self.title = title
        self.panels_grid = panels_grid
        # generate a unique (and repeatable) id from the title.
        self.uid = str(uuid.uuid5(uuid.NAMESPACE_DNS, title))

    @classmethod
    def from_service_registries(cls, title: str, n_columns: int = 2, *service_registries):
        srv_names = []
        for reg in service_registries:
            srv_names.extend(sort_service_names(list(reg.services.keys())))
        panels_grid = []
        for i in range(0, len(srv_names), n_columns):
            row_services = srv_names[i : i + n_columns]
            panels_grid.append([
                LogsPanelConfig(service=Service(name=name)) for name in row_services
            ])
        return cls(title=title, panels_grid=panels_grid)

    def create(self):
        dashboard = self._create_gl_dashboard()
        resp = requests.post(
            f"http://{config.grafana_host}/api/dashboards/db", 
            data=json.dumps(
            {"dashboard": dashboard}, cls=DashboardEncoder, indent=2
        ).encode("utf-8"), headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {config.grafana_api_key}",
        }
        )
        if resp.status_code == 200:
            logger.info(f"{self.title} dashboard created/updated successfully")
        else:
            logger.error(f"Error creating/updating dashboard: {resp.status_code} - {resp.text}")

    def _create_gl_dashboard(self) -> GLDashboard:
        # Validate panels_grid structure
        for panels_row in self.panels_grid:
            if isinstance(panels_row, LogsPanelConfig):
                continue
            if not all(isinstance(p, LogsPanelConfig) for p in panels_row):
                raise ValueError("panels_grid must be list[LogsPanelConfig | List[LogsPanelConfig]].")
            if len(panels_row) > 24:
                raise ValueError("Each row in panels_grid can have at most 24 panels.")
        
        gl_panels = []
        y_pos = 0
        
        for panels_row in self.panels_grid:
            if not isinstance(panels_row, (tuple, list)):
                panels_row = [panels_row]
            
            default_width_fr = 1 / len(panels_row)
            x_pos = 0
            max_height = 0
            
            for panel in panels_row:
                if panel.width_fr is None:
                    panel.width_fr = default_width_fr
                
                expr = '{name="/{}"}'.format(panel.service.name)
                title = panel.service.name
                
                if isinstance(panel, (LogsCountPlot, LogsTextSearch)):
                    title = panel.title
                    expr += f' |= "{panel.text}"'
                
                width = int(panel.width_fr * 24)
                
                if isinstance(panel, LogsCountPlot):
                    # Create a proper grafanalib Graph panel
                    graph_panel = Graph(
                        title=title,
                        targets=[
                            Target(
                                expr=f'count_over_time({expr}[{panel.period}])',
                                legendFormat="Count",
                                refId="A",
                            )
                        ],
                        gridPos=GridPos(h=panel.height_no, w=width, x=x_pos, y=y_pos),
                        dataSource="loki"
                    )
                    gl_panels.append(graph_panel)
                else:
                    # Create a proper grafanalib Logs panel
                    logs_panel = Logs(
                        title=title,
                        dataSource="loki",
                        targets=[
                            Target(
                                expr=expr,
                                refId="A",
                            )
                        ],
                        gridPos=GridPos(h=panel.height_no, w=width, x=x_pos, y=y_pos),
                        showLabels=False,
                        showCommonLabels=False,
                        showTime=False,
                        wrapLogMessages=False,
                        sortOrder="Descending",
                        dedupStrategy="none",
                        enableLogDetails=True,
                        prettifyLogMessage=False,
                    )
                    gl_panels.append(logs_panel)
                
                x_pos += width
                max_height = max(max_height, panel.height_no)
            
            y_pos += max_height
        
        return GLDashboard(
            title=self.title,
            uid=self.uid,
            editable=True,
            fiscalYearStartMonth=0,
            graphTooltip=0,
            id=None,
            links=[],
            panels=gl_panels,
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
                    {
                        "builtIn": 1,
                        "datasource": {"type": "grafana", "uid": "-- Grafana --"},
                        "enable": True,
                        "hide": True,
                        "iconColor": "rgba(0, 211, 255, 1)",
                        "name": "Annotations & Alerts",
                        "type": "dashboard",
                    }
                ]
            )
        ).auto_panel_ids()

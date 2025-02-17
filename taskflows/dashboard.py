
"""
import json
import os

import requests
from grafanalib._gen import DashboardEncoder
from grafanalib.core import Dashboard, Graph, Target


dashboard = Dashboard(
    title="Python Loki Dashboard",
    panels=[
        Graph(
            title="Log Rate",
            targets=[
                Target(
                    expr='sum(rate({app="my-app"}[1m])) by (level)',
                    legendFormat="{{level}}",
                    refId="A",
                )
            ],
        )
    ],
).auto_panel_ids()


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
"""
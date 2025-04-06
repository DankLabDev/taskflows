# TaskFlows: Task Management, Scheduling, and Alerting System

TaskFlows is a Python library that provides robust task management, scheduling, and alerting capabilities. It allows you to convert regular functions into managed tasks with logging, alerts, retries, and more. TaskFlows also supports creating system services that run on specified schedules with flexible constraints.

## Features
- Convert any Python function into a managed task
- Task execution logging and metadata storage
- Configurable alerting via Slack and Email
- Automated retries and timeout handling
- Schedule-based execution using system services
- Support for various scheduling patterns (calendar-based, periodic)
- System resource constraint options

## Setup

### Prerequisites
```bash
sudo apt install dbus
loginctl enable-linger
```

### Installation
```bash
pip install taskflows
```

### Database Configuration
Task execution metadata is stored in either:
- SQLite (default, no configuration needed)
- PostgreSQL (requires configuration)

To use a custom database:
```bash
# For SQLite
export TASKFLOWS_DB_URL="sqlite:///path/to/your/database.db"

# For PostgreSQL
export TASKFLOWS_DB_URL="postgresql://user:password@localhost:5432/dbname"
export TASKFLOWS_DB_SCHEMA="custom_schema"  # Optional, defaults to 'taskflows'
```

## Usage

### Command Line Interface
Admin commands are accessed via the `tf` command line tool:
```bash
# Get help on available commands
tf --help

# Create services defined in a Python file
tf create my_services.py

# List active services
tf list

# Stop a service
tf stop service-name
```

### Creating Tasks
Turn any function (optionally async) into a managed task:

```python
import os
from taskflows import task, Alerts, Slack, Email

alerts=[
    Alerts(
        send_to=[   
            Slack(
                bot_token=os.getenv("SLACK_BOT_TOKEN"),
                channel="critical_alerts"
            ),
            Email(
                addr="sender@gmail.com", 
                password=os.getenv("EMAIL_PWD"),
                receiver_addr=["someone@gmail.com", "someone@yahoo.com"]
            )
        ],
        send_on=["start", "error", "finish"]
    )
]

@task(
    name='some-task',
    required=True,
    retries=1,
    timeout=30,
    alerts=alerts
)
async def hello():
    print("Hi.")
    
# Execute the task
if __name__ == "__main__":
    hello()
```

### Task Parameters
- `name`: Unique identifier for the task
- `required`: Whether task failure should halt execution
- `retries`: Number of retry attempts if the task fails
- `timeout`: Maximum execution time in seconds
- `alerts`: Alert configurations for the task

### Review Task Status/Results
Tasks can send alerts via Slack and/or Email, as shown in the above example. Internally, alerts are sent using the [alert-msgs](https://github.com/djkelleher/alert-msgs) package.   
Task start/finish times, status, retry count, return values can be found in the `task_runs` table.   
Any errors that occurred during the execution of a task can be found in the `task_errors` table.   

### Creating Services
*Note: To use services, your system must have systemd (the init system on most modern Linux distributions)*    

Services run commands on a specified schedule. See [Service](taskflows/service/service.py#35) for service configuration options.    

To create the service(s), use the `create` method (e.g. `srv.create()`), or use the CLI `create` command (e.g. `tf create my_services.py`)   

### Service Examples

#### Calendar-based Scheduling
Run a command at specific calendar days/times:

```python
from taskflows import Calendar, Service

# Run every day at 2:00 PM Eastern Time
srv = Service(
    name="daily-backup",
    start_command="docker start backup-service",
    start_schedule=Calendar("Mon-Sun 14:00 America/New_York"),
)

# Create and register the service
srv.create()
```

#### One-time Scheduling
Run a command once at a specific time:

```python
from datetime import datetime, timedelta
from taskflows import Calendar, Service

# Run once, 30 minutes from now
run_time = datetime.now() + timedelta(minutes=30)
srv = Service(
    name='write-message',
    start_command="bash -c 'echo hello >> hello.txt'",
    start_schedule=Calendar.from_datetime(run_time),
)
srv.create()
```

#### Periodic Scheduling with Constraints
Run a command periodically with system resource constraints:

```python
from taskflows import Service, Periodic, CPUPressure

# Run after system boot, then every 5 minutes
# Skip if CPU usage is over 80% for the last 5 minutes
service = Service(
    name="resource-aware-task",
    start_command="docker start my-service",
    start_schedule=Periodic(start_on="boot", period=60*5, relative_to="start"),
    system_load_constraints=CPUPressure(max_percent=80, timespan="5min", silent=True)
)
service.create()
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| TASKFLOWS_DB_URL | Database connection URL | sqlite:///~/.local/share/taskflows/taskflows.db |
| TASKFLOWS_DB_SCHEMA | PostgreSQL schema name | taskflows |
| TASKFLOWS_DISPLAY_TIMEZONE | Timezone for display purposes | UTC |
| TASKFLOWS_DOCKER_LOG_DRIVER | Docker logging driver | json-file |
| TASKFLOWS_FLUENT_BIT_HOST | Fluent Bit host for logging | localhost |
| TASKFLOWS_FLUENT_BIT_PORT | Fluent Bit port for logging | 24224 |

## Development Resources
dbus documentation:
- https://www.freedesktop.org/software/systemd/man/latest/org.freedesktop.systemd1.html
- https://pkg.go.dev/github.com/coreos/go-systemd/dbus

## Contributing
Contributions are welcome! Please feel free to submit a Pull Request.

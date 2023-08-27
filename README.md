
## Python task management, scheduling, alerts.

Admin commands are accessed via the `tasks` command line tool. See `tasks --help` for complete usage.  

### Setup
`pip install task-flows`   

Task execution metadata is stored in Postgresql. Set environment variable `TASK_FLOWS_DB` to the URL of the Postgresql instance you would like to use.

### Create a scheduled Task
```python
from task_flows import ScheduledTask, OnCalendar

task = ScheduledTask(
    task_name="my-task",
    command="my-command",
    timer=OnCalendar("Sun 17:00 America/New_York"),
)
task.create()
```

### Create Tasks
Turn any function (optionally async) into a task that logs metadata to the database and sends alerts, allows retries, etc..
```python
@task(
    name='some-task',
    required=True,
    retries=1,
    timeout=30,
    alert_methods=["slack","email"],
    alert_events=["start", "error", "finish"]
)
async def hello():
    print("Hi.")
```
Environmental variables can be set for argument defaults that should be applied to all tasks that don't specify a value for the argument.
Then the above function is equivalent to:
```bash
export TASK_FLOWS_ALERT_METHODS="slack,email"
export TASK_FLOWS_ALERT_EVENTS="start,error,finish"
```
```python
@task(
    name='some-task',
    required=True,
    retries=1,
    timeout=2,
)
async def hello():
    print("Hi.")
```

### Review Task Status/Results
Tasks can send alerts via Slack and/or Email, as shown in the above example. Task start/finish times, status, retry count, return values can be found in the `task_runs` table. Any errors that occurred during the execution of a task can be found in the `task_errors` table.




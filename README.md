
# Task Management, Scheduling, and Alerting.

Admin commands are accessed via the `taskflows` command line tool. See `taskflows --help` for complete usage.  

### Setup
```bash
sudo apt install libdbus-glib-1-dev
loginctl enable-linger
pip install taskflows
``` 

Task execution metadata is stored in SQLite (default) or Postgresql. To use a personal database, set environment variable `TASKFLOWS_DB_URL` to your database URL. If using Postgresql, TASKFLOWS_DB_SCHEMA may also be set to use a custom schema (default schema is *taskflows*).   

### Create Tasks
Turn any function (optionally async) into a task that logs metadata to the database and sends alerts, allows retries, etc..
```python
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
```

### Review Task Status/Results
Tasks can send alerts via Slack and/or Email, as shown in the above example. Internally, alerts are sent using the [alert-msgs](https://github.com/djkelleher/alert-msgs) package.   
Task start/finish times, status, retry count, return values can be found in the `task_runs` table.   
Any errors that occurred during the execution of a task can be found in the `task_errors` table.   

### Create Services
*Note: To use services, your system must have systemd (the init system on most modern Linux distributions)*    

Services run commands on a specified schedule. See [Service](taskflows/service/service.py#35) for service configuration options.    

To create the service(s), use the `create` method (e.g. `srv.create()`), or use the CLI `create` command (e.g. `taskflows create my_services.py`)   

### Examples
```python
from taskflows import Calendar, Service
```
#### Run at specified calendar days/time.
see [Calendar](taskflows/service/schedule.py#14) for more options.
```python
srv = Service(
    name="something",
    command="docker start something",
    schedule=Calendar("Mon-Sun 14:00 America/New_York"),
)
```
#### Run command once at half an hour from now.
```python
run_time = datetime.now() + timedelta(minutes=30)
srv = Service(
    name='write-message',
    command="bash -c 'echo hello >> hello.txt'",
    schedule=Calendar.from_datetime(run_time),
)
```
#### Run command after system boot, then again every 5 minutes after start of previous run. Skip run if CPU usage is over 80% for the last 5 minutes.
see [Periodic](taskflows/service/schedule.py#34) and [constraints](taskflows/service/constraints.py) for more options.
```python
Service(
    name="my-periodic-task",
    command="docker start something",
    schedule=Periodic(start_on="boot", period=60*5, relative_to="start"),
    system_load_constraints=CPUPressure(max_percent=80, timespan="5min", silent=True)
)
```


## Python task management, scheduling, alerts.

Admin commands are accessed via the `tasks` command line tool. See `tasks --help` for complete usage.  

### Setup
`pip install taskflows`   

Task execution metadata is stored in Postgresql. Set environment variable `TASKFLOWS_DB` to the URL of the Postgresql instance you would like to use.


### Create Tasks
Turn any function (optionally async) into a task that logs metadata to the database and sends alerts, allows retries, etc..
```python
alerts=[
    Alerts(
        send_to=[   
            Slack(
                bot_token=os.getenv("SLACK_BOT_TOKEN"),
                app_token=os.getenv("SLACK_APP_TOKEN"),
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
Tasks can send alerts via Slack and/or Email, as shown in the above example. Task start/finish times, status, retry count, return values can be found in the `task_runs` table. Any errors that occurred during the execution of a task can be found in the `task_errors` table.


### Create a scheduled Task
```python
from taskflows import Calendar, Service

tws_weekend_start_srv = Service(
    name="something",
    command="docker start something",
    schedule=Calendar("Mon-Sun 14:00 America/New_York"),
)

task.create()
```






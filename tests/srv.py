from taskflows.service import Calendar, Service

srv = Service(
    name="test",
    start_command="bash -c 'echo test'",
    start_schedule=Calendar("Sun 17:00 America/New_York"),
)

from taskflows.service import Calendar, Service

srv = Service(
    name="test",
    command="bash -c 'echo test'",
    schedule=Calendar("Sun 17:00 America/New_York"),
)

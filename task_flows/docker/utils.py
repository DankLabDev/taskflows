from functools import cache
from typing import Optional

import docker


@cache
def get_docker_client(user_host: Optional[str] = None):
    base_url = f"ssh://{user_host}" if user_host else "unix:///var/run/docker.sock"
    return docker.DockerClient(base_url=base_url)

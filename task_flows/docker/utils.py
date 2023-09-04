from functools import lru_cache
from typing import Optional

import docker


@lru_cache
def get_docker_client(user_host: Optional[str] = None):
    base_url = f"ssh://{user_host}" if user_host else "unix:///var/run/docker.sock"
    return docker.DockerClient(base_url=base_url)

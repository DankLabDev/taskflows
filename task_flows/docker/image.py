from dataclasses import asdict, dataclass
from typing import Dict, Optional

from docker.errors import ImageNotFound
from docker.models.images import Image
from task_flows.utils import logger

from .utils import get_docker_client


@dataclass
class ContainerLimits:
    # Set memory limit for build.
    memory: Optional[int] = None
    # Total memory (memory + swap), -1 to disable swap
    memswap: Optional[int] = None
    # CPU shares (relative weight)
    cpushares: Optional[int] = None
    # CPUs in which to allow execution, e.g., 0-3, 0,1
    cpusetcpus: Optional[str] = None


@dataclass
class Image:
    """Docker image."""

    # Image name.
    tag: str
    # Directory that docker build command should be ran in.
    path: str
    # path to Dockerfile relative to `build_dir`.
    dockerfile: str
    # Whether to return the status
    quiet: bool = False
    # Do not use the cache when set to True.
    nocache: Optional[bool] = None
    # Remove intermediate containers.
    rm: bool = True
    # HTTP timeout
    timeout: Optional[int] = None
    # The encoding for a stream. Set to gzip for compressing.
    encoding: Optional[str] = None
    # Downloads any updates to the FROM image in Dockerfiles
    pull: Optional[bool] = None
    # Always remove intermediate containers, even after unsuccessful builds
    forcerm: Optional[bool] = None
    # A dictionary of build arguments
    buildargs: Optional[dict] = None
    # A dictionary of limits applied to each container created by the build process. Valid keys:
    container_limits: Optional[ContainerLimits] = None
    # Size of /dev/shm in bytes. The size must be greater than 0. If omitted the system uses 64MB.
    shmsize: Optional[int] = None
    # A dictionary of labels to set on the image
    labels: Optional[Dict[str, str]] = None
    # A list of images used for build cache resolution.
    cache_from: Optional[list] = None
    # Name of the build-stage to build in a multi-stage Dockerfile
    target: Optional[str] = None
    # networking mode for the run commands during build
    network_mode: Optional[str] = None
    # Squash the resulting images layers into a single layer.
    squash: Optional[bool] = None
    # Extra hosts to add to /etc/hosts in building
    # containers, as a mapping of hostname to IP address.
    extra_hosts: Optional[dict] = None
    # Platform in the format.
    platform: Optional[str] = None
    # Isolation technology used during build. Default: None.
    isolation: Optional[str] = None
    # If True, and if the docker client
    # configuration file (~/.docker/config.json by default)
    # contains a proxy configuration, the corresponding environment
    # variables will be set in the container being built.
    use_config_proxy: Optional[bool] = None

    def build(self, force_recreate: bool = False) -> Image:
        client = get_docker_client()
        try:
            img = client.images.get(self.tag)
        except ImageNotFound:
            img = None
        if img is not None:
            logger.warning("Image already exists: %s", self.tag)
            if not force_recreate:
                logger.warning("Will not recreate image: %s", self.tag)
                return img
            logger.warning("Removing existing image: %s", self.tag)
            client.images.remove(self.tag, force=True)
        logger.info("Building image %s", self.tag)
        built_img, log = client.images.build(**asdict(self))
        fmt_log = []
        for row in log:
            if "id" in row:
                row_fmt = f"[{row['id']}][{row['status']}]"
                if row["progress_detail"]:
                    row_fmt += f"[{row['progress_detail']}]"
                row_fmt += f"[{row['progress']}]"
            elif "stream" in row:
                fmt_log.append(row["stream"])
        print("".join(fmt_log))
        return built_img

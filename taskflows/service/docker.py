from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Sequence, Union

import docker
from docker.errors import ImageNotFound
from docker.models.containers import Container
from docker.models.images import Image
from docker.types import LogConfig
from dotenv import dotenv_values
from xxhash import xxh32

from taskflows.utils import config, logger


@lru_cache
def get_docker_client(user_host: Optional[str] = None):
    base_url = f"ssh://{user_host}" if user_host else "unix:///var/run/docker.sock"
    return docker.DockerClient(base_url=base_url)


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
class DockerImage:
    """Docker image."""

    # Image name.
    tag: str
    # Directory that docker build command should be ran in.
    path: str
    # path to Dockerfile relative to `path`.
    dockerfile: str = "Dockerfile"
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
            if not force_recreate:
                logger.warning("Will not recreate image: %s", self.tag)
                return img
            logger.warning("Removing existing image: %s", self.tag)
            client.images.remove(self.tag, force=True)
        logger.info("Building image %s", self.tag)
        built_img, log = client.images.build(**asdict(self))
        print(_fmt_log(log))
        return built_img


def _fmt_log(log) -> str:
    fmt_log = []
    for row in log:
        if "id" in row:
            row_fmt = f"[{row['id']}][{row['status']}]"
            if row["progress_detail"]:
                row_fmt += f"[{row['progress_detail']}]"
            row_fmt += f"[{row['progress']}]"
        elif "stream" in row:
            fmt_log.append(row["stream"])
    return "".join(fmt_log)


@dataclass
class Volume:
    """Docker volume."""

    host_path: Union[Path, str]
    container_path: Union[Path, str]
    read_only: bool = False

    def __post_init__(self):
        self.host_path = str(self.host_path)
        self.container_path = str(self.container_path)


@dataclass
class Ulimit:
    """System ulimit (system resource limit)."""

    name: str
    soft: Optional[int] = None
    hard: Optional[int] = None

    def __post_init__(self):
        if self.soft is None and self.hard is None:
            raise ValueError("Either `soft` limit or `hard` limit must be set.")


fluentd_log_driver = LogConfig(
    type=LogConfig.types.FLUENTD,
    config={
        "fluentd-address": f"{config.fluent_bit_host}:{config.fluent_bit_port}",
        "tag": "docker.{{.Name}}",
    },
)


@dataclass
class DockerContainer:
    """Docker container."""

    image: Union[str, DockerImage]
    command: str
    name: Optional[str] = None
    network_mode: Optional[
        Literal["bridge", "host", "none", "overlay", "ipvlan", "macvlan"]
    ] = None
    init: Optional[bool] = None
    detach: Optional[bool] = None
    user: Optional[str] = None
    mem_limit: Optional[str] = None
    shm_size: Optional[str] = None
    env: Optional[Dict[str, str]] = None
    env_file: Optional[Union[str, Path]] = None
    # Local volumes.
    volumes: Optional[Union[Volume, Sequence[Volume]]] = None
    # List of container names or IDs to get volumes from.
    volumes_from: Optional[List[str]] = None
    # The name of a volume driver/plugin.
    volume_driver: Optional[str] = None
    ulimits: Optional[Union[Ulimit, Sequence[Ulimit]]] = None
    # enable auto-removal of the container on daemon
    # side when the containeras process exits.
    auto_remove: Optional[bool] = None
    # Block IO weight (relative device weight) in
    # the form of:. [{"Path": "device_path", "Weight": weight}].
    blkio_weight_device: Optional[Dict[str, str]] = None
    # Block IO weight (relative weight), accepts a weight
    # value between 10 and 1000.
    blkio_weight: Optional[int] = None
    # Add kernel capabilities. For example,.
    cap_add: Optional[List[str]] = None
    # Drop kernel capabilities.
    cap_drop: Optional[List[str]] = None
    # Override the default parent cgroup.
    cgroup_parent: Optional[str] = None
    # Override the default cgroup namespace mode for the
    # container. One of:
    # -the container runs in its own private cgroup
    cgroupns: Optional[str] = None
    # Number of usable CPUs (Windows only).
    cpu_count: Optional[int] = None
    # Usable percentage of the available CPUs
    # (Windows only).
    cpu_percent: Optional[int] = None
    # The length of a CPU period in microseconds.
    cpu_period: Optional[int] = None
    # Microseconds of CPU time that the container can
    # get in a CPU period.
    cpu_quota: Optional[int] = None
    # Limit CPU real-time period in microseconds.
    cpu_rt_period: Optional[int] = None
    # Limit CPU real-time runtime in microseconds.
    cpu_rt_runtime: Optional[int] = None
    # CPU shares (relative weight).
    cpu_shares: Optional[int] = None
    # CPUs in which to allow execution (,).
    cpuset_cpus: Optional[str] = None
    # Memory nodes (MEMs) in which to allow execution
    # (,). Only effective on NUMA systems.
    cpuset_mems: Optional[str] = None
    # A list of cgroup rules to
    # apply to the container.
    device_cgroup_rules: Optional[List[str]] = None
    # Limit read rate (bytes per second) from a device
    # in the form of: [{“Path”: “device_path”, “Rate”: rate}]
    device_read_bps: Optional[List[Dict[str, Any]]] = None
    # Limit read rate (IO per second) from a device.
    device_read_iops: Optional[int] = None
    # Limit write rate (bytes per second) from a
    # device.
    device_write_bps: Optional[int] = None
    # Limit write rate (IO per second) from a device.
    device_write_iops: Optional[int] = None
    # Expose host devices to the container,
    # as a list of strings in the form.For example,allows the container
    # to have read-write access to the hostasvia a
    # node namedinside the container.
    devices: Optional[List[str]] = None
    # Expose host resources such as
    # GPUs to the container, as a list ofinstances.
    device_requests: Optional[List[docker.types.DeviceRequest]] = None
    # Set custom DNS servers.
    dns: Optional[List[str]] = None
    # Additional options to be added to the containers resolv.conf file.
    dns_opt: Optional[List[str]] = None
    # DNS search domains.
    dns_search: Optional[List[str]] = None
    # Set custom DNS search domains.
    domainname: Optional[Union[str, List[str]]] = None
    # The entrypoint for the container.
    entrypoint: Optional[Union[str, List[str]]] = None
    # Environment variables to set inside
    # the container, as a dictionary or a list of strings in the
    # format ["SOMEVARIABLE=xxx"].
    environment: Optional[Union[Dict[str, str], List[str]]] = None
    # Additional hostnames to resolve inside the
    # container, as a mapping of hostname to IP address.
    extra_hosts: Optional[Dict[str, str]] = None
    # List of additional group names and/or
    # IDs that the container process will run as.
    group_add: Optional[List[str]] = None
    # Specify a test to perform to check that the
    # container is healthy. The dict takes the following keys:
    # TODO this should have it's own type?
    healthcheck: Optional[Dict[str, Any]] = None
    # Optional hostname for the container.
    hostname: Optional[str] = None
    # Run an init inside the container that forwards
    # signals and reaps processes
    init: Optional[bool] = None
    # Path to the docker-init binary
    init_path: Optional[str] = None
    # Set the IPC mode for the container.
    ipc_mode: Optional[str] = None
    # Isolation technology to use. Default:.
    isolation: Optional[str] = None
    # Kernel memory limit
    kernel_memory: Optional[Union[str, int]] = None
    # A dictionary of name-value labels (e.g.) or a list of
    # names of labels to set with empty values (e.g.)
    labels: Optional[Union[Dict[str, str], List[str]]] = None
    # Mapping of links using theformat. The alias is optional.
    # Containers declared in this dict will be linked to the new
    # container using the provided alias. Default:.
    links: Optional[Dict[str, str]] = None
    # Logging configuration. Defaults to fluentd_log_driver
    # log_config: Optional[docker.types.LogConfig] = field(
    #    default_factory=lambda: fluentd_log_driver
    # )
    log_config: Optional[docker.types.LogConfig] = None
    # LXC config.
    lxc_conf: Optional[dict] = None
    # MAC address to assign to the container.
    mac_address: Optional[str] = None
    # Memory limit. Accepts float values
    # (which represent the memory limit of the created container in
    # bytes) or a string with a units identification char
    # (,,,). If a string is
    # specified without a units character, bytes are assumed as an
    # intended unit.
    mem_limit: Optional[Union[str, int]] = None
    # Memory soft limit.
    mem_reservation: Optional[Union[str, int]] = None
    # Tune a containeras memory swappiness
    # behavior. Accepts number between 0 and 100.
    mem_swappiness: Optional[int] = None
    # Maximum amount of memory + swap a
    # container is allowed to consume.
    memswap_limit: Optional[Union[str, int]] = None
    # Specification for mounts to be added to
    # the container. More powerful alternative to. Each
    # item in the list is expected to be aobject.
    mounts: Optional[List[docker.types.Mount]] = None
    # The name for this container.
    name: Optional[str] = None
    # CPU quota in units of 1e-9 CPUs.
    nano_cpus: Optional[int] = None
    # Name of the network this container will be connected
    # to at creation time. You can connect to additional networks
    # using. Incompatible with.
    network: Optional[str] = None
    # Disable networking.
    network_disabled: Optional[bool] = None
    # Whether to disable OOM killer.
    oom_kill_disable: Optional[bool] = None
    # An integer value containing the score given
    # to the container in order to tune OOM killer preferences.
    oom_score_adj: Optional[int] = None
    # If set to, use the host PID
    # inside the container.
    pid_mode: Optional[str] = None
    # Tune a containeras pids limit. Setfor
    # unlimited.
    pids_limit: Optional[int] = None
    # Platform in the format.
    # Only used if the method needs to pull the requested image.
    platform: Optional[str] = None
    # Ports to bind inside the container.The keys of the dictionary are the ports to bind inside the
    # container, either as an integer or a string in the form, where the protocol is either,, or.The values of the dictionary are the corresponding ports to
    # open on the host, which can be either:Incompatible withnetwork mode.
    ports: Optional[dict] = None
    # Give extended privileges to this container.
    privileged: Optional[bool] = None
    # Publish all ports to the host.
    publish_all_ports: Optional[bool] = None
    # Mount the containeras root filesystem as read
    # only.
    read_only: Optional[bool] = None
    # Remove the container when it has finished running.
    # Default:.
    remove: Optional[bool] = None
    # Restart the container when it exits.
    # Configured as a dictionary with keys:For example:
    restart_policy: Optional[dict] = None
    # Runtime to use with this container.
    runtime: Optional[str] = None
    # A list of string values to
    # customize labels for MLS systems, such as SELinux.
    security_opt: Optional[List[str]] = None
    # Size of /dev/shm (e.g.).
    shm_size: Optional[Union[str, int]] = None
    # Keepopen even if not attached.
    stdin_open: Optional[bool] = None
    # Return logs fromwhen.
    # Default:.
    stdout: Optional[bool] = None
    # Return logs fromwhen.
    # Default:.
    stderr: Optional[bool] = None
    # The stop signal to use to stop the container
    # (e.g.).
    stop_signal: Optional[str] = None
    # Storage driver options per container as a
    # key-value mapping.
    storage_opt: Optional[dict] = None
    # If true andis false, return a log
    # generator instead of a string. Ignored ifis true.
    # Default:.
    stream: Optional[bool] = None
    # Kernel parameters to set in the container.
    sysctls: Optional[dict] = None
    # Temporary filesystems to mount, as a dictionary
    # mapping a path inside the container to options for that path.For example:
    tmpfs: Optional[dict] = None
    # Allocate a pseudo-TTY.
    tty: Optional[bool] = None
    # If, and if the docker client
    # configuration file (by default)
    # contains a proxy configuration, the corresponding environment
    # variables will be set in the container being built.
    use_config_proxy: Optional[bool] = None
    # Username or UID to run commands as inside the
    # container.
    user: Optional[Union[str, int]] = None
    # Sets the user namespace mode for the container
    # when user namespace remapping option is enabled. Supported
    # values are:
    userns_mode: Optional[str] = None
    # Sets the UTS namespace mode for the container.
    # Supported values are:
    uts_mode: Optional[str] = None
    # The version of the API to use. Set toto
    # automatically detect the serveras version. Default:
    version: Optional[str] = None
    # Path to the working directory.
    working_dir: Optional[str] = None

    def __post_init__(self):
        if isinstance(self.volumes, Volume):
            self.volumes = [self.volumes]
        if isinstance(self.ulimits, Ulimit):
            self.ulimits = [self.ulimits]

    def create(self) -> Container:
        """Create a Docker container for running a script.

        Args:
            task_name (str): Name of the task the container is for.
            container (Container): container for the task.

        Returns:
            Container: The created Docker container.
        """
        # create default container name if one wasn't assigned.
        if self.name is None:
            if isinstance(self.image, DockerImage):
                img_name = self.image.tag
            else:
                img_name = self.image.split("/")[-1].split(":")[0]
            command_id = xxh32(self.command).hexdigest()
            self.name = f"{img_name}-{command_id}"

        # remove any existing container with this name.
        self.delete()
        # if image is not build, it must be built.
        if isinstance(self.image, DockerImage):
            self.image.build()
        cfg = {k: v for k, v in asdict(self).items() if v is not None}
        if cfg.get("log_config") is None:
            cfg["log_config"] = fluentd_log_driver

        env = cfg.pop("env", {})
        if env_file := cfg.pop("env_file", None):
            env.update(dotenv_values(env_file))
        if env:
            cfg["environment"] = env

        cfg["name"] = self.name
        if " " in self.command:
            cfg["command"] = self.command.split()
        if self.ulimits:
            cfg["ulimits"] = [
                docker.types.Ulimit(name=l.name, soft=l.soft, hard=l.hard)
                for l in self.ulimits
            ]
        if self.volumes:
            cfg["volumes"] = {
                v.host_path: {
                    "bind": v.container_path,
                    "mode": "ro" if v.read_only else "rw",
                }
                for v in self.volumes
            }
        if isinstance(self.image, DockerImage):
            cfg["image"] = self.image.tag
        logger.info("Creating Docker container %s: %s", self.name, cfg)
        return get_docker_client().containers.create(**cfg)

    def delete(self):
        """Remove container."""
        delete_docker_container(self.name)


def delete_docker_container(container_name: str, force: bool = True) -> bool:
    """Remove container.

    Args:
        container_name (str): Name of container to remove.
    """
    try:
        container = get_docker_client().containers.get(container_name)
    except docker.errors.NotFound:
        return False
    container.remove(force=force)
    logger.info("Removed Docker container: %s", container_name)
    return True

import os
from datetime import datetime
from pathlib import Path
from subprocess import PIPE, run
from typing import Any, Dict, List, Union

import sqlalchemy as sa
from paramiko import AutoAddPolicy, SSHClient

from .common import logger

host_ssh = sa.Table(
    "host_ssh",
    sa.MetaData(),
    sa.Column("hostname", sa.String, primary_key=True),
    sa.Column("port", sa.Integer),
    sa.Column("username", sa.String),
    sa.Column("password", sa.String),
    sa.Column("pkey", sa.String),
    sa.Column("key_filename", sa.String),
    sa.Column("passphrase", sa.String),
)


host_resources = sa.Table(
    "host_resources",
    sa.MetaData(),
    sa.Column("hostname", sa.String, primary_key=True),
    sa.Column("nproc", sa.Integer),
    sa.Column("memory", sa.Float),
)

# TODO create task to trim table at time
resource_usage = sa.Table(
    "resource_usage",
    sa.MetaData(),
    sa.Column("hostname", sa.String, primary_key=True),
    sa.Column("time", sa.DateTime, primary_key=True),
    sa.Column("cpu_usage_pct", sa.Float),
    sa.Column("memory_usage", sa.Float),
)


CONFIG_DIR = os.getenv("CONFIG_DIR", Path(__file__).parent / "task_configs")
CONFIG_DIR.mkdir(exist_ok=True, parents=True)


db_file = Path(__file__).parent / "data.db"
# connection isn't opened until first query.
engine = sa.create_engine(f"sqlite:////{db_file}")


def create_table(engine, table) -> None:
    if sa.inspect(engine).has_table(table.name):
        table.create(engine)


def get_ssh_credentials(hostname: str) -> Dict[str, Any]:
    _get_table_values(host_ssh, hostname)


def set_ssh_credentials(hostname: str, values: Dict[str, Any]) -> None:
    _set_table_values(host_ssh, hostname, values)


def get_resources(hostname: str) -> Dict[str, Any]:
    _get_table_values(host_resources, hostname)


def set_resources(hostname: str, values: Dict[str, Any]) -> None:
    _set_table_values(host_resources, hostname, values)


def get_resource_usage(hostname: str) -> Dict[str, Any]:
    _get_table_values(resource_usage, hostname)


def set_resource_usage(hostname: str, values: Dict[str, Any]) -> None:
    if "time" not in values:
        values["time"] = datetime.now()
    engine.execute(sa.insert(resource_usage).values(values))


def _set_table_values(table: sa.Table, hostname: str, values: Dict[str, Any]):
    with engine.connect() as conn:
        conn.execute(sa.delete(table).where(table.c.hostname == hostname))
        conn.execute(sa.insert(table).values(values))


def _get_table_values(table: sa.Table, hostname: str) -> Dict[str, Any]:
    query = sa.select(table.c.nproc, table.c.memory).where(table.c.hostname == hostname)
    return {k: v for k, v in dict(engine.execute(query).fetchone()) if v is not None}


# map hostname to SSHClient.
_open_ssh_clients: Dict[str, SSHClient] = {}


def ssh_client(hostname: str, **credentials) -> SSHClient:
    """Get an SSH client connection to a remote host."""
    # check if we already opened a client connection to this host.
    if hostname in _open_ssh_clients:
        return _open_ssh_clients[hostname]
    # create a client connection and cache it for future calls.
    ssh_client = SSHClient()
    ssh_client.set_missing_host_key_policy(AutoAddPolicy())
    # if new credentials were provided, save them to database.
    if credentials:
        set_ssh_credentials(hostname, credentials)
    # check database for credentials if nothing was provided.
    credentials = credentials or get_ssh_credentials(hostname)
    if not credentials:
        raise ValueError(f"No credentials were provided for host {hostname}")
    ssh_client.connect(**credentials)
    _open_ssh_clients[hostname] = ssh_client
    return ssh_client


def add_host_ssh_credentials(hostname: str, **credentials) -> None:
    """Store credentials that will be used to initialize an SSH connection to hostname.
    e.g. 'username' and 'password
    """
    if credentials:
        _ssh_credentials[hostname].update(credentials)
        _credentials_file.write_bytes(pickle.dumps(_ssh_credentials))


def close_all() -> None:
    for host, conn in _ssh_clients.items():
        logger.info(f"Closing SSH connection to {host}")
        conn.close()


def exec_local_command(command: Union[List[str], str]) -> str:
    if isinstance(command, str):
        command = command.split()
    result = run(command, stderr=PIPE, stdout=PIPE)
    stderr = result.stderr.decode()
    if stderr:
        raise RuntimeError(f"Error executing command '{command}': {stderr}")
    return result.stdout.decode()


def exec_remote_command(hostname: str, command: Union[List[str], str]) -> str:
    if isinstance(command, (list, tuple)):
        command = " ".join(command)
    _, stdout, stderr = ssh_client(hostname).exec_command(command)
    stderr = stdout.read().decode()
    if stderr:
        raise RuntimeError(f"Error executing command '{command}': {stderr}")
    return stdout.read().decode()


def exec_command(command: Union[List[str], str], hostname: str = "localhost") -> str:
    if hostname in ("localhost", "127.0.0.1"):
        return exec_local_command(command)
    return exec_remote_command(hostname, command)
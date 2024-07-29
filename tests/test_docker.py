from tempfile import NamedTemporaryFile
from time import sleep

import pytest

from taskflows.service import DockerContainer, DockerRunService, MambaEnv, Volume

venv = MambaEnv("trading")


@pytest.fixture
def temp_file():
    with NamedTemporaryFile() as f:
        yield f.name


def write_file(text_file):
    with open(text_file, "w") as f:
        f.write("hello")


@pytest.fixture
def docker_container(temp_file):
    return DockerContainer(
        name="taskflows-test",
        image="taskflows",
        command=lambda: write_file(f"/opt/{temp_file}"),
        network_mode="host",
        volumes=[
            # Volume(
            #    host_path="/home/dan/.taskflows",
            #    container_path=f"/root/.taskflows",
            # ),
            Volume(
                host_path=temp_file,
                container_path=f"/opt/{temp_file}",
            ),
            Volume(
                host_path="/var/run/docker.sock",
                container_path="/var/run/docker.sock",
            ),
        ],
    )


def test_container_run_py_function(temp_file, docker_container):
    docker_container.run()
    assert open(temp_file).read().strip() == "hello"


def test_docker_run_service(temp_file, docker_container):
    srv = DockerRunService(docker_container, venv=venv)
    srv.create()
    srv.start()
    sleep(2)
    assert open(temp_file).read().strip() == "hello"

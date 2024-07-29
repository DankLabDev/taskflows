FROM mambaorg/micromamba:jammy

# mambaorg/micromamba defaults to a non-root user.
USER root

ENV PROJ_DIR="/opt/taskflows"

# activate base environment.
ARG MAMBA_DOCKERFILE_ACTIVATE=1

# Install Python
RUN micromamba install --yes --name base -c conda-forge python=3.11
RUN micromamba clean --all --yes

RUN apt-get update && DEBIAN_FRONTEND=noninteractive \
    apt-get install -y --no-install-recommends \
    gcc build-essential systemd dbus \
    libffi-dev libdbus-1-dev libdbus-glib-1-dev pkg-config \
    # Clean up
    && apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# copy files.
WORKDIR $PROJ_DIR
COPY . .

RUN pip install -e .[dev]
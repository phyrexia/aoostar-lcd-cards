# syntax=docker/dockerfile:1
#
# aoostar-lcd-cards + asterctl (https://github.com/zehnm/aoostar-rs, MIT OR Apache-2.0).
# asterctl is NOT vendored: it is built from the pinned commit (default) or downloaded as
# the pinned release with its SHA-256 checked. Both read asterctl.version.
#
#   docker build -t aoostar-lcd .                                   # build asterctl from source
#   docker build -t aoostar-lcd --build-arg ASTERCTL_SOURCE=release .   # prebuilt, x86_64 only
#
# Run (the panel is a USB serial device; nothing else is privileged):
#   docker run -d --name aoostar-lcd --device /dev/ttyACM0 --group-add dialout \
#     --network host -v ./config.yaml:/config/config.yaml:ro aoostar-lcd

ARG ASTERCTL_SOURCE=source
ARG RUST_IMAGE=rust:1.88-slim-bookworm
ARG PYTHON_IMAGE=python:3.12-slim-bookworm

# --- asterctl from source (any architecture) ------------------------------------------
FROM ${RUST_IMAGE} AS asterctl-source
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates pkg-config libudev-dev \
 && rm -rf /var/lib/apt/lists/*
COPY asterctl.version /src/asterctl.version
COPY scripts/install-asterctl.sh /src/scripts/install-asterctl.sh
COPY licenses/asterctl /src/licenses/asterctl
RUN sh /src/scripts/install-asterctl.sh --from source --prefix /opt/asterctl

# --- asterctl prebuilt release (Linux x86_64) -----------------------------------------
FROM debian:bookworm-slim AS asterctl-release
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl libudev1 \
 && rm -rf /var/lib/apt/lists/*
COPY asterctl.version /src/asterctl.version
COPY scripts/install-asterctl.sh /src/scripts/install-asterctl.sh
COPY licenses/asterctl /src/licenses/asterctl
RUN sh /src/scripts/install-asterctl.sh --from release --prefix /opt/asterctl

FROM asterctl-${ASTERCTL_SOURCE} AS asterctl

# --- runtime ---------------------------------------------------------------------------
FROM ${PYTHON_IMAGE}
RUN apt-get update \
 && apt-get install -y --no-install-recommends libudev1 \
 && rm -rf /var/lib/apt/lists/*
COPY --from=asterctl /opt/asterctl/bin/asterctl /usr/local/bin/asterctl
COPY --from=asterctl /opt/asterctl/share/doc/asterctl /usr/share/doc/asterctl
COPY pyproject.toml README.md LICENSE NOTICE /src/
COPY src /src/src
RUN pip install --no-cache-dir /src && rm -rf /src \
 && useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin aoostar \
 && install -d -o aoostar -m 0755 /var/lib/aoostar-lcd \
 && asterctl --version && aoostar-lcd --version
USER aoostar
ENV AOOSTAR_LCD_CONFIG=/config/config.yaml
ENTRYPOINT ["aoostar-lcd"]
CMD ["run"]

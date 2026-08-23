# A Linux box with systemd, for exercising deploy/ without touching anyone's machine.
#
# Development utility, not part of the product. Nobody installing hvk needs this; anyone
# verifying that deploy/ works before trusting it does.
#
# Debian 12 on purpose: it is what most VPS run, and its Python 3.11 is exactly the minimum
# ADR-0001 targets, so a passing test here means something.

FROM debian:12

ENV DEBIAN_FRONTEND=noninteractive \
    container=docker \
    LANG=C.UTF-8

# libpam-systemd and dbus-user-session are the difference between a testbed that works and
# one that cannot test anything: pam_systemd sets XDG_RUNTIME_DIR and creates /run/user/<uid>,
# and dbus-user-session provides the bus `systemctl --user` talks to. Everything deploy/
# installs is user-scope, so without them the per-user systemd instance never starts.
RUN apt-get update && apt-get install -y --no-install-recommends \
        systemd systemd-sysv dbus libpam-systemd dbus-user-session \
        cron git tmux \
        python3 python3-venv \
        ca-certificates curl sudo procps less vim-tiny \
    && rm -rf /var/lib/apt/lists/*

# systemd inside a container spends its time trying to manage hardware it does not have.
# Removing these units keeps the boot quiet and quick.
RUN find /etc/systemd/system /lib/systemd/system \
        -path '*.wants/*' \
        \( -name '*udev*' -o -name '*getty*' -o -name '*swap*' -o -name '*mount*' \) \
        -exec rm -f {} + 2>/dev/null || true

# Everything deploy/ installs is user-scope, so the tests have to run as a normal user.
ARG USERNAME=hvk
ARG UID=1000
RUN useradd --create-home --shell /bin/bash --uid "$UID" "$USERNAME" \
    && echo "$USERNAME ALL=(ALL) NOPASSWD:ALL" > "/etc/sudoers.d/$USERNAME" \
    && chmod 0440 "/etc/sudoers.d/$USERNAME" \
    # Lingering is what makes user services survive without a login session. deploy/README.md
    # calls it the one privileged step; here it is baked in so the container starts ready.
    && mkdir -p /var/lib/systemd/linger && touch "/var/lib/systemd/linger/$USERNAME"

# Optional, and off by default. The real ob and claude need credentials, so the testbed uses
# stubs unless you ask for the real thing: build with --build-arg WITH_RUNTIMES=1.
ARG WITH_RUNTIMES=0
RUN if [ "$WITH_RUNTIMES" = "1" ]; then \
        curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && \
        apt-get install -y --no-install-recommends nodejs && \
        rm -rf /var/lib/apt/lists/* && \
        su - "$USERNAME" -c 'curl -fsSL https://bun.sh/install | bash'; \
    fi

STOPSIGNAL SIGRTMIN+3
CMD ["/sbin/init"]

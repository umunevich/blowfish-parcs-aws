#!/bin/bash
# EC2 "User data" for the PARCS master node (Ubuntu 24.04, x86_64).
# Runs once as root on first boot: installs Docker and starts the PARCS-Python
# master (web UI + job scheduler on port 8080).
# Log: /var/log/cloud-init-output.log
set -eux

apt-get update
apt-get install -y docker.io git python3
systemctl enable --now docker
usermod -aG docker ubuntu

# --network host: PARCS nodes talk to each other on random ports (Flask, Pyro4),
# so the container uses the VM's network stack directly.
docker run -d --name parcs --restart unless-stopped --network host \
    -e PARCS_ARGS="master" \
    hummer12007/parcs-node

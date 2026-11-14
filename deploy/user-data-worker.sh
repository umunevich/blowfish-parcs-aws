#!/bin/bash
# EC2 "User data" for a PARCS worker node (Ubuntu 24.04, x86_64).
# BEFORE PASTING: replace MASTER_PRIVATE_IP with the master's *private* IPv4
# address (e.g. 172.31.12.34), shown in the EC2 console for the master instance.
# Log: /var/log/cloud-init-output.log
set -eux

MASTER_PRIVATE_IP="MASTER_PRIVATE_IP"

apt-get update
apt-get install -y docker.io
systemctl enable --now docker
usermod -aG docker ubuntu

# The worker registers itself on the master at MASTER_PRIVATE_IP:8080 and then
# serves Pyro4 RPC calls on random ports (hence --network host).
docker run -d --name parcs --restart unless-stopped --network host \
    -e PARCS_ARGS="worker ${MASTER_PRIVATE_IP}" \
    hummer12007/parcs-node

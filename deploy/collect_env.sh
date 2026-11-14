#!/bin/bash
# Print information about the cloud environment for the report.
# Run on the master VM:  bash deploy/collect_env.sh [WORKER_PRIVATE_IP ...]
set -u

imds() {  # EC2 instance metadata (IMDSv2)
    local token
    token=$(curl -s -X PUT http://169.254.169.254/latest/api/token \
        -H "X-aws-ec2-metadata-token-ttl-seconds: 60")
    curl -s -H "X-aws-ec2-metadata-token: ${token}" "http://169.254.169.254/latest/meta-data/$1"
}

echo "== Instance"
echo "instance-type:     $(imds instance-type)"
echo "availability-zone: $(imds placement/availability-zone)"
echo "private-ip:        $(imds local-ipv4)"
echo
echo "== OS / CPU / memory"
grep PRETTY_NAME /etc/os-release
lscpu | grep -E "Model name|^CPU\(s\)|Thread|Core|MHz" || true
free -h | head -2
echo
echo "== Docker / PARCS"
docker --version
docker ps --format "{{.Names}}  {{.Image}}  {{.Status}}"
docker exec parcs python --version 2>&1
echo
echo "== Workers registered on the master"
curl -s http://localhost:8080/api/worker | python3 -m json.tool
for ip in "$@"; do
    echo
    echo "== Network latency to worker ${ip}"
    ping -c 5 -q "${ip}" | tail -2
done

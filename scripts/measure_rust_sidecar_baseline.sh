#!/usr/bin/env bash
set -euo pipefail

container="${PODLY_CONTAINER_NAME:-podly-pure-podcasts}"
url="${1:-}"

echo "== docker stats =="
docker stats --no-stream "$container"

echo
echo "== docker top =="
docker top "$container" -eo pid,ppid,rss,vsz,comm,args

echo
echo "== cgroup memory =="
docker exec "$container" sh -lc 'cat /sys/fs/cgroup/memory.current; grep -E "^(anon|file|kernel|slab|inactive_file|active_file) " /sys/fs/cgroup/memory.stat'

if [[ -n "$url" ]]; then
  echo
  echo "== route timing =="
  curl -sS -o /tmp/podly_route_timing.json -w 'status=%{http_code} time_total=%{time_total} size=%{size_download}\n' "$url"
fi

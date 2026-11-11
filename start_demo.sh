#!/usr/bin/env bash
set -eo pipefail
root=$(cd "$(dirname "$0")" && pwd)
exec /usr/bin/python3 "$root/ros2_ws/src/bai08_turtlebot4/scripts/session.py" "$@"

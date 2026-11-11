#!/usr/bin/env bash
set -eo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
source /opt/ros/humble/setup.bash
if [[ -n "${BAI08_UNDERLAY:-}" ]]; then source "$BAI08_UNDERLAY/install/setup.bash"; fi
cd "$root/ros2_ws"
colcon build --symlink-install --packages-select bai08_turtlebot4

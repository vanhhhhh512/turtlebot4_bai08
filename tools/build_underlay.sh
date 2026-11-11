#!/usr/bin/env bash
set -eo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
ws="$root/underlay"
mkdir -p "$ws/src"
if [[ ! -e "$ws/src/create3_overrides" ]]; then
  git clone https://github.com/vanhhhhh512/turtlebot4_bai04.git "$ws/src/create3_overrides"
fi
git -C "$ws/src/create3_overrides" checkout --detach 9f2e4143fcf0caddd72a630accf6f99a6bf37cc5
source /opt/ros/humble/setup.bash
cd "$ws"
colcon build --base-paths src/create3_overrides/upstream --packages-select irobot_create_nodes irobot_create_control --allow-overriding irobot_create_nodes irobot_create_control --cmake-args -DBUILD_TESTING=OFF -DCMAKE_BUILD_TYPE=Release

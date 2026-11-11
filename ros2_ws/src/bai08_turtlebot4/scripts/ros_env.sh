#!/usr/bin/env bash
# Source inside an env -i shell to avoid Jazzy/user overlays.
source /opt/ros/humble/setup.bash
if [[ -n "${BAI08_UNDERLAY:-}" ]]; then source "$BAI08_UNDERLAY/install/setup.bash"; fi
export ROS_DOMAIN_ID=${BAI08_DOMAIN:-108}
export ROS_LOCALHOST_ONLY=1 RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export CYCLONEDDS_URI="file://$BAI08_PACKAGE/config/cyclonedds.xml"
export IGN_PARTITION="bai08_${BAI08_SESSION}"
export ROS_LOG_DIR="$BAI08_RUN/ros_log"
mkdir -p "$ROS_LOG_DIR"

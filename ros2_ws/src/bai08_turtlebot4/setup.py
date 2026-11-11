from setuptools import setup
from glob import glob

setup(
    name="bai08_turtlebot4",
    version="0.1.0",
    packages=["bai08_turtlebot4"],
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/bai08_turtlebot4"]),
        ("share/bai08_turtlebot4", ["package.xml"]),
    ]
    + [
        ("share/bai08_turtlebot4/" + d, glob(d + "/*"))
        for d in ["launch", "config", "worlds"]
    ],
    entry_points={
        "console_scripts": [
            "controller = bai08_turtlebot4.ros_node:main",
            "prepare = bai08_turtlebot4.prepare:main",
        ]
    },
)

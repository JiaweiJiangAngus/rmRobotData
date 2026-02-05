#!/bin/bash
g++ fetch_robot.cpp -o fetch_robot -lcurl
./fetch_robot
export PYTHONPATH=$HOME/.local/lib/python3.10/site-packages
g++ analyzer.cpp -o analyze
./analyze
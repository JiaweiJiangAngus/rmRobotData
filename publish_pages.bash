#!/bin/bash
set -euo pipefail

mkdir -p bin docs

if [ "${1:-}" = "--fetch" ]; then
    ./build.bash
else
    g++ -std=c++17 analyzer.cpp -o bin/analyze
fi

printf 'exit\n' | RM_AUTO_OPEN_BROWSER=0 ./bin/analyze
cp bin/robot_dashboard.html docs/index.html

echo "GitHub Pages 文件已更新: docs/index.html"

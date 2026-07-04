#!/bin/bash
set -euo pipefail

mkdir -p bin docs
mkdir -p docs/rules

if [ "${1:-}" = "--fetch" ]; then
    ./build.bash
else
    g++ -std=c++17 analyzer.cpp -o bin/analyze
fi

printf 'exit\n' | RM_AUTO_OPEN_BROWSER=0 ./bin/analyze
cp bin/robot_dashboard.html docs/index.html
if compgen -G "data/rules/*.pdf" >/dev/null; then
    cp data/rules/*.pdf docs/rules/
fi

echo "GitHub Pages 文件已更新: docs/index.html"

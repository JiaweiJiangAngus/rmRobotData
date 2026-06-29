#!/usr/bin/env bash
set -euo pipefail

# 始终切到脚本所在目录，避免从别的目录执行时生成路径错乱
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

CXX="${CXX:-g++}"
CXXFLAGS="${CXXFLAGS:--std=c++17 -O2 -Wall -Wextra}"
LDFLAGS_CURL="${LDFLAGS_CURL:--lcurl}"

log()  { printf '\033[1;36m%s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m%s\033[0m\n' "$*"; }
err()  { printf '\033[1;31m%s\033[0m\n' "$*" >&2; }

check_cmd() {
    if ! command -v "$1" >/dev/null 2>&1; then
        err "未找到 $1。"
        return 1
    fi
}

check_header() {
    local header="$1"
    local package_hint="$2"
    if ! printf '#include <%s>\nint main(){return 0;}\n' "$header" | "$CXX" -std=c++17 -x c++ -fsyntax-only - >/dev/null 2>&1; then
        err "缺少头文件 <$header>。"
        err "Ubuntu/Debian 可尝试安装：$package_hint"
        return 1
    fi
}

log "[Checking] 检查构建环境..."
check_cmd python3
check_cmd "$CXX"
check_header "curl/curl.h" "sudo apt install libcurl4-openssl-dev"
check_header "nlohmann/json.hpp" "sudo apt install nlohmann-json3-dev"

mkdir -p bin

log "----------------------------------------"
log "[1/4] 正在编译 fetch_robot..."
"$CXX" $CXXFLAGS fetch_robot.cpp -o bin/fetch_robot $LDFLAGS_CURL

if [[ "${1:-}" == "--no-fetch" ]]; then
    warn "[2/4] 已跳过抓取数据：收到 --no-fetch 参数。"
else
    log "[2/4] 正在抓取最新数据..."
    ./bin/fetch_robot
fi

log "----------------------------------------"
log "[3/4] 正在编译 analyzer..."
"$CXX" $CXXFLAGS analyzer.cpp -o bin/analyze

log "[4/4] 构建完成。"
log "运行 ./run.bash 可生成并打开 bin/robot_dashboard.html。"
log "只想编译、不抓取数据时，可执行：./build.bash --no-fetch"
log "----------------------------------------"

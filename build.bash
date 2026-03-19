#!/bin/bash
echo "[Checking] Python runtime..."
python3 --version > /dev/null 2>&1
if [ $? -ne 0 ]; then
    echo "未找到 python3，请先安装 Python 3。"
    exit 1
else
    echo "Python 运行环境检查通过。"
fi

# 创建 bin 文件夹（如果不存在）
if [ ! -d "bin" ]; then
    echo ">> 创建 bin 目录..."
    mkdir -p bin
fi

# 设置 Python 环境变量
export PYTHONPATH=$HOME/.local/lib/python3.10/site-packages

# ==========================================
# 2. 编译 & 运行数据抓取程序 (fetch_robot)
# ==========================================

echo "----------------------------------------"
echo "[1/4] 正在编译 fetch_robot..."
# 将可执行文件输出到 bin/fetch_robot
g++ fetch_robot.cpp -o bin/fetch_robot -lcurl

echo "[2/4] 正在抓取最新数据..."
# 运行 bin 目录下的程序
# 注意：程序运行时的"当前目录"依然是项目根目录，
# 所以生成的 data 文件夹会出现在根目录下，这是正确的。
./bin/fetch_robot

# ==========================================
# 3. 编译 & 运行分析程序 (analyzer)
# ==========================================

echo "----------------------------------------"
echo "[3/4] 正在编译 analyzer..."
# 将可执行文件输出到 bin/analyze
# 加上 -std=c++17 确保兼容性
g++ -std=c++17 analyzer.cpp -o bin/analyze

echo "[4/4] 编译完成!"
echo "查询结果会生成到 bin/robot_dashboard.html，可直接用run.bash打开。"
echo "----------------------------------------"

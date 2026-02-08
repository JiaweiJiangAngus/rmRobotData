#!/bin/bash
echo "[Checking] Python libraries..."
python3 -c "import pandas, matplotlib, tkinter" > /dev/null 2>&1
if [ $? -ne 0 ]; then
    echo "正在安装必要的 Python 库..."
    pip3 install pandas matplotlib
    # tkinter 通常是 apt install python3-tk
    echo "提示: 如果运行报错缺少 tkinter，请执行: sudo apt-get install python3-tk"
else
    echo "Python 库检查通过。"
fi

# 创建 bin 文件夹（如果不存在）
if [ ! -d "bin" ]; then
    echo ">> 创建 bin 目录..."
    mkdir -p bin
fi

# 设置 Python 环境变量 (根据你的要求)
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
echo "----------------------------------------"

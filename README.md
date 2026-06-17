# RM Robot Data Dashboard

一个用于整理、查询和网页化展示 RoboMaster 机器人数据的小工具。项目会从本地 `data/` 数据文件生成交互式网页仪表盘，支持按赛区、兵种、学校、战队和指标进行筛选与排序。

## 现在能看什么

- 全量数据总览：学校、战队、赛区、兵种与多项比赛指标。
- 快速筛选：按赛区、兵种、关键词过滤。
- 指标排序：点击不同数据指标查看排名。
- 战队对比：筛到单支战队时，页面会显示雷达图，用来观察不同兵种的综合表现。
- 静态部署：生成的 `docs/index.html` 可以直接放到 GitHub Pages 上作为网页访问。

## 项目结构

```text
rmRobotData/
├── data/                 # 原始数据文件
├── docs/
│   └── index.html         # GitHub Pages 使用的网页入口
├── bin/
│   ├── robot_dashboard.html # 本地查询后生成的网页报告
│   ├── analyze             # 编译后的分析程序
│   └── fetch_robot         # 编译后的数据抓取程序
├── analyzer.cpp           # 数据分析与 CSV 生成逻辑
├── fetch_robot.cpp        # 数据抓取逻辑
├── view_table.py          # 将 CSV 渲染成 HTML 仪表盘
├── build.bash             # 编译并抓取最新数据
├── run.bash               # 进入查询并自动打开网页
└── publish_pages.bash     # 更新 docs/index.html，用于 GitHub Pages
```

## 本地使用

### 1. 安装依赖

Linux / WSL / macOS 下需要：

```bash
sudo apt install g++ python3 libcurl4-openssl-dev
```

如果不是 Ubuntu，请保证系统里至少有：

- `g++`
- `python3`
- `curl` / `libcurl`

### 2. 编译并抓取数据

```bash
./build.bash
```

这个脚本会做三件事：

1. 检查 Python 环境。
2. 编译 `fetch_robot.cpp` 和 `analyzer.cpp`。
3. 抓取最新数据，并把可执行文件放到 `bin/` 目录。

### 3. 进入查询并打开网页

```bash
./run.bash
```

查询结束后，会生成：

```text
bin/robot_dashboard.html
```

在 Linux 桌面环境下，脚本会尝试自动用默认浏览器打开它。要是没弹浏览器，手动打开这个文件就行。

## 不运行程序，直接看现成网页

项目里已经带了一个可直接打开的网页：

```text
docs/index.html
```

本地直接双击这个文件，或者在浏览器地址栏打开它，就能看到网页版仪表盘。

也可以用本地静态服务器预览：

```bash
python3 -m http.server 8000 -d docs
```

然后在浏览器打开：

```text
http://localhost:8000
```

## 发布到 GitHub Pages

这个项目最简单的部署方式是把 `docs/index.html` 作为 GitHub Pages 的入口文件。

### 1. 更新网页文件

如果只想用当前 `data/` 里的数据生成网页：

```bash
./publish_pages.bash
```

如果想先抓取最新数据，再生成网页：

```bash
./publish_pages.bash --fetch
```

运行后会更新：

```text
docs/index.html
```

### 2. 提交并推送

```bash
git add README.md data/ docs/index.html
 git commit -m "update robot data dashboard"
 git push
```

### 3. 在 GitHub 打开 Pages

进入仓库页面：

```text
Settings -> Pages -> Build and deployment
```

选择：

```text
Source: Deploy from a branch
Branch: master
Folder: /docs
```

保存后，GitHub 会自动发布 `docs/index.html`。如果仓库名是 `rmRobotData`，网页地址通常会长这样：

```text
https://你的GitHub用户名.github.io/rmRobotData/
```

如果第一次打开是 404，等一两分钟再刷新；GitHub Pages 第一次部署通常不是瞬间完成的。

## 常见问题

### 运行 `./run.bash` 没打开浏览器

先确认网页是否已经生成：

```bash
ls bin/robot_dashboard.html
```

如果文件存在，直接用浏览器打开它。

### 运行脚本提示没有权限

给脚本加执行权限：

```bash
chmod +x build.bash run.bash publish_pages.bash
```

### 编译时报 `curl` 相关错误

安装 libcurl 开发库：

```bash
sudo apt install libcurl4-openssl-dev
```

### GitHub Pages 404

优先检查这几件事：

1. 仓库里是否真的存在 `docs/index.html`。
2. Pages 的分支是否选的是 `master`。
3. Pages 的目录是否选的是 `/docs`。
4. `docs/index.html` 是否已经 push 到 GitHub。

## 推荐工作流

平时更新数据可以直接跑：

```bash
./publish_pages.bash --fetch
 git add data/ docs/index.html
 git commit -m "update dashboard data"
 git push
```

推送完成后，GitHub Pages 会自动更新网页。

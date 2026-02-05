import pandas as pd
import tkinter as tk
from tkinter import ttk, messagebox
import matplotlib.pyplot as plt
import sys
import platform

# ==========================================
# 1. 字体配置 (防乱码)
# ==========================================
def configure_fonts():
    system_name = platform.system()
    font_candidates = []
    if system_name == "Linux":
        font_candidates = ["WenQuanYi Micro Hei", "WenQuanYi Zen Hei", "Noto Sans CJK SC", "DejaVu Sans", "sans-serif"]
    elif system_name == "Windows":
        font_candidates = ["Microsoft YaHei", "SimHei", "Arial", "sans-serif"]
    elif system_name == "Darwin":
        font_candidates = ["PingFang SC", "Heiti TC", "Arial", "sans-serif"]
    else:
        font_candidates = ["WenQuanYi Micro Hei", "sans-serif"]

    plt.rcParams['font.sans-serif'] = font_candidates
    plt.rcParams['axes.unicode_minus'] = False

configure_fonts()

# ==========================================
# 2. 单个兵种页面的创建逻辑
# ==========================================
class RobotTab:
    def __init__(self, notebook, df_subset, type_name, default_sort_col=None):
        self.df = df_subset.copy()
        self.type_name = type_name
        
        # --- 数据清洗：删除全是空值或0的列，让表格更干净 ---
        # 排除必须保留的基础列
        base_cols = ["赛区", "学校", "战队", "兵种"]
        
        # 找出数值列
        numeric_cols = []
        for col in self.df.columns:
            if col not in base_cols:
                # 如果这一列全是 0 或全是 NaN，就丢弃
                try:
                    # 转为数字，无法转的变成 NaN
                    temp_col = pd.to_numeric(self.df[col], errors='coerce').fillna(0)
                    if (temp_col == 0).all():
                        self.df = self.df.drop(columns=[col])
                    else:
                        numeric_cols.append(col)
                except:
                    pass # 非数值列保留
        
        # --- 自动排序 ---
        if default_sort_col and default_sort_col in self.df.columns:
            try:
                self.df = self.df.sort_values(by=default_sort_col, ascending=False)
            except: pass

        # 创建 Tab 容器
        self.frame = tk.Frame(notebook)
        notebook.add(self.frame, text=f" {type_name} ") # 设置标签页标题

        # === 顶部控制栏 (画图) ===
        ctrl_frame = tk.Frame(self.frame, pady=5, bg="#f0f0f0")
        ctrl_frame.pack(fill=tk.X)
        
        tk.Label(ctrl_frame, text=f"📊 {type_name} 数据分析:", bg="#f0f0f0", font=('bold')).pack(side=tk.LEFT, padx=10)

        self.sel_metric = tk.StringVar()
        if numeric_cols:
            # 尝试选中默认排序的列，否则选第一个
            if default_sort_col and default_sort_col in numeric_cols:
                self.sel_metric.set(default_sort_col)
            else:
                self.sel_metric.set(numeric_cols[0])

        cb = ttk.Combobox(ctrl_frame, textvariable=self.sel_metric, values=numeric_cols, state="readonly", width=20)
        cb.pack(side=tk.LEFT, padx=5)

        btn = tk.Button(ctrl_frame, text="生成图表", command=self.generate_chart, bg="#3498db", fg="white")
        btn.pack(side=tk.LEFT, padx=10)

        # === 表格区域 ===
        table_frame = tk.Frame(self.frame)
        table_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        y_scroll = tk.Scrollbar(table_frame)
        y_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        x_scroll = tk.Scrollbar(table_frame, orient=tk.HORIZONTAL)
        x_scroll.pack(side=tk.BOTTOM, fill=tk.X)

        cols = ["序号"] + list(self.df.columns)
        self.tree = ttk.Treeview(table_frame, columns=cols, show='headings',
                                 yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)
        
        y_scroll.config(command=self.tree.yview)
        x_scroll.config(command=self.tree.xview)

        # 列设置
        for i, c in enumerate(cols):
            if i == 0:
                self.tree.heading(c, text=c)
            else:
                self.tree.heading(c, text=c, command=lambda _c=c: self.sort_tree(_c, False))
            w = len(str(c)) * 20
            self.tree.column(c, width=min(max(w, 80), 200), anchor='center')

        # 插入数据
        for idx, (_, row) in enumerate(self.df.iterrows(), start=1):
            vals = [idx] + [("" if pd.isna(x) else x) for x in row.tolist()]
            self.tree.insert("", tk.END, values=vals)

        self.tree.pack(fill=tk.BOTH, expand=True)

    def sort_tree(self, col, reverse):
        # 树状图排序逻辑
        if col == "序号":
            return  # 不排序序号列
        l = [(self.tree.set(k, col), k) for k in self.tree.get_children('')]
        try:
            l.sort(key=lambda t: float(t[0]) if t[0] not in ["", "-"] else -999999.0, reverse=reverse)
        except:
            l.sort(key=lambda t: t[0], reverse=reverse)
        for index, (_, k) in enumerate(l):
            self.tree.move(k, '', index)
            self.tree.set(k, "序号", index + 1)
        self.tree.heading(col, command=lambda: self.sort_tree(col, not reverse))

    def generate_chart(self):
        metric = self.sel_metric.get()
        if not metric: return
        try:
            # 画图数据准备
            plot_df = self.df.sort_values(by=metric, ascending=True)
            
            plt.figure(figsize=(10, 6))
            
            # 标签：显示队伍
            labels = plot_df['赛区'] + "   " + plot_df['学校'] + "   " + plot_df['战队']
            
            bars = plt.barh(labels, plot_df[metric], color='#3498db')
            plt.xlabel(metric)
            plt.title(f"{self.type_name} - {metric} (Top 20)")
            plt.grid(axis='x', linestyle='--', alpha=0.5)
            plt.tight_layout()
            
            for bar in bars:
                plt.text(bar.get_width(), bar.get_y() + bar.get_height()/2, 
                         f'{bar.get_width():.2f}', va='center', fontsize=9)
            plt.show()
        except Exception as e:
            messagebox.showerror("Error", str(e))

# ==========================================
# 3. 主窗口逻辑
# ==========================================
def main(csv_file, title, default_sort=None):
    try:
        df = pd.read_csv(csv_file, encoding='utf-8')
    except:
        return

    root = tk.Tk()
    root.title(f"RM 数据查询 - {title}")
    root.geometry("1200x700")

    # 创建 Tab 容器
    notebook = ttk.Notebook(root)
    notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

    # 获取所有兵种类型
    if "兵种" in df.columns:
        robot_types = df['兵种'].unique()
        # 对兵种排序，让步兵、英雄排前面，雷达排后面
        priority = ["步兵", "英雄", "工程", "哨兵", "无人机", "飞镖", "雷达"]
        robot_types = sorted(robot_types, key=lambda x: priority.index(x) if x in priority else 99)

        for r_type in robot_types:
            # 筛选该兵种的数据
            sub_df = df[df['兵种'] == r_type]
            if not sub_df.empty:
                RobotTab(notebook, sub_df, r_type, default_sort)
    else:
        # 如果没有兵种列，就只显示一个通用页
        RobotTab(notebook, df, "通用数据", default_sort)

    root.mainloop()

if __name__ == "__main__":
    if len(sys.argv) >= 3:
        sort_col = sys.argv[3] if len(sys.argv) > 3 else None
        main(sys.argv[1], sys.argv[2], sort_col)
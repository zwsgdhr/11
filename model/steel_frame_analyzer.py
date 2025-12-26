import tkinter as tk
from tkinter import ttk, messagebox
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import openseespy.opensees as ops
import opsvis as opsv
import os

# 设置中文字体
plt.rcParams['font.sans-serif'] = ['SimHei', 'DejaVu Sans', 'Arial Unicode MS', 'Microsoft YaHei']
plt.rcParams['axes.unicode_minus'] = False  # 正确显示负号


class SteelFrameAnalyzer:
    def __init__(self, parent_frame):
        self.parent_frame = parent_frame

        # 创建绘图画布
        self.fig, self.ax = plt.subplots(figsize=(10, 8))
        self.canvas = FigureCanvasTkAgg(self.fig, master=parent_frame)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        # 添加点击事件绑定
        self.canvas.mpl_connect('button_press_event', self.on_canvas_click)

        # 内力图类型选择 - 放在绘图区域右上角
        diagram_frame = ttk.Frame(parent_frame)
        diagram_frame.place(relx=0.98, rely=0.02, anchor=tk.NE)

        self.diagram_var = tk.StringVar(value="模型图")
        diagram_options = ["模型图", "荷载图", "反力图", "变形图", "轴力图", "剪力图", "弯矩图"]
        diagram_combo = ttk.Combobox(diagram_frame, textvariable=self.diagram_var,
                                     values=diagram_options, state="readonly", width=12)
        diagram_combo.bind("<<ComboboxSelected>>", self.on_diagram_change)
        diagram_combo.pack()

        # 比例参数
        self.def_scale = 50.0
        self.axial_scale = 0.05
        self.shear_scale = 0.05
        self.moment_scale = 0.1

        # 加载H型钢规格表
        self.h_steel_data = self.load_h_steel_data()

        # 初始化
        self.column_elements = []
        self.beam_elements = []
        self.current_analysis_data = None

        # 存储每个梁的荷载值
        self.beam_loads = {}

        # 存储每个元素的H型钢规格（覆盖默认值）
        self.element_steels = {}

        # 存储节点荷载
        self.node_loads = {}

        # 存储梁上的集中荷载
        self.beam_point_loads = {}

        # 临时存储当前选中的元素
        self.selected_element = None
        self.selected_node = None

    def update_scale(self, chart_type, value):
        """更新比例值"""
        if chart_type == 'def':
            self.def_scale = value
        elif chart_type == 'axial':
            self.axial_scale = value
        elif chart_type == 'shear':
            self.shear_scale = value
        elif chart_type == 'moment':
            self.moment_scale = value

    def get_current_diagram_type(self):
        """获取当前图表类型"""
        return self.diagram_var.get()

    def load_h_steel_data(self):
        """加载H型钢规格参数表"""
        try:
            # 查找当前目录下的H型钢规格参数表
            file_path = "H型钢规格参数表.xlsx"
            if os.path.exists(file_path):
                df = pd.read_excel(file_path)
                return df
            else:
                messagebox.showwarning("警告", "找不到H型钢规格表.xlsx文件，使用默认数据")
                # 返回默认数据
                default_data = {
                    'Dimension': [
                        "HW100×100×6×8", "HW125×125×6.5×9", "HW150×150×7×10",
                        "HW175×175×7.5×11", "HW200×200×8×12", "HW200×204×12×12",
                        "HW244×252×11×11", "HW250×250×9×14", "HW250×255×14×14",
                        "HW294×302×12×12", "HW300×300×10×15", "HW300×305×15×15",
                        "HW338×351×13×13"
                    ],
                    'A': [21.58, 30, 39.64, 51.42, 63.53, 71.53, 81.31, 91.43, 103.9, 106.3, 118.5, 133.5, 133.3],
                    'Ix': [378, 839, 1620, 2900, 4720, 4980, 8700, 10700, 11400, 16600, 20200, 21300, 27700],
                    'Iy': [134, 293, 563, 984, 1600, 1700, 2940, 3650, 3880, 5510, 6750, 7100, 9380],
                    'G': [16.9, 23.6, 31.1, 40.4, 49.9, 56.2, 63.8, 71.8, 81.6, 83.5, 93, 105, 105]
                }
                df = pd.DataFrame(default_data)
                return df
        except Exception as e:
            messagebox.showerror("错误", f"加载H型钢规格表失败: {str(e)}")
            return None

    def get_steel_properties(self, dimension):
        """根据H型钢型号获取截面属性"""
        if self.h_steel_data is None:
            # 返回默认值
            return 0.006353, 4.72e-5, 1.6e-5, 49.9  # A, Ix, Iy, G (m², m⁴, m⁴, kg/m)

        row = self.h_steel_data[self.h_steel_data['Dimension'] == dimension]
        if row.empty:
            messagebox.showwarning("警告", f"未找到H型钢规格: {dimension}")
            return 0.006353, 4.72e-5, 1.6e-5, 49.9  # 默认值

        area_cm2 = row.iloc[0]['A']  # cm²
        ix_cm4 = row.iloc[0]['Ix']  # cm⁴
        iy_cm4 = row.iloc[0]['Iy']  # cm⁴
        weight_kg_m = row.iloc[0]['G']  # kg/m

        area_m2 = area_cm2 / 10000  # cm² → m²
        ix_m4 = ix_cm4 / 100000000  # cm⁴ → m⁴
        iy_m4 = iy_cm4 / 100000000  # cm⁴ → m⁴

        return area_m2, ix_m4, iy_m4, weight_kg_m

    def get_material_properties(self, grade):
        """根据钢材强度等级获取弹性模量（单位：kN/m²）"""
        properties = {
            "Q235B": 206e6,  # 206 GPa = 206e9 Pa = 206e6 kN/m²
            "Q355B": 206e6  # Q355B的弹性模量也是206 GPa
        }
        return properties.get(grade, 206e6)  # 默认Q235B

    def analyze_frame(self, span_list, height, floors, steel_grade, default_load, include_self_weight):
        """执行结构分析（使用 kN-m 单位体系）"""
        # 获取材料属性（kN/m²）
        E = self.get_material_properties(steel_grade)

        # 清除之前的模型
        ops.wipe()
        ops.model('basic', '-ndm', 2, '-ndf', 3)

        # 创建节点
        node_id = 1
        total_bays = len(span_list)
        total_nodes_per_floor = total_bays + 1

        for floor in range(floors + 1):
            x_pos = 0
            for i in range(total_nodes_per_floor):
                ops.node(node_id, x_pos, floor * height)
                node_id += 1
                if i < total_bays:
                    x_pos += span_list[i]

        # 固定底部节点
        for i in range(total_nodes_per_floor):
            ops.fix(i + 1, 1, 1, 1)

        # 定义几何变换
        ops.geomTransf('Linear', 1)

        # 创建单元
        ele_id = 1
        column_elements = []
        beam_elements = []

        # 柱单元
        for floor in range(floors):
            for col_idx in range(total_nodes_per_floor):
                start_node = floor * total_nodes_per_floor + col_idx + 1
                end_node = (floor + 1) * total_nodes_per_floor + col_idx + 1
                # 获取柱的H型钢规格
                col_dimension = self.element_steels.get(ele_id, "HW200×200×8×12")  # 默认值
                col_area, col_Ix, col_Iy, col_weight = self.get_steel_properties(col_dimension)
                ops.element('elasticBeamColumn', ele_id, start_node, end_node,
                            col_area, E, col_Ix, 1)
                column_elements.append(ele_id)
                ele_id += 1

        # 梁单元
        for floor in range(1, floors + 1):
            base_node = floor * total_nodes_per_floor + 1
            for span_idx in range(total_bays):
                start_node = base_node + span_idx
                end_node = start_node + 1
                # 获取梁的H型钢规格
                beam_dimension = self.element_steels.get(ele_id, "HW200×200×8×12")  # 默认值
                beam_area, beam_Ix, beam_Iy, beam_weight = self.get_steel_properties(beam_dimension)
                ops.element('elasticBeamColumn', ele_id, start_node, end_node,
                            beam_area, E, beam_Ix, 1)
                beam_elements.append(ele_id)
                ele_id += 1

        # 定义时间序列和模式
        ops.timeSeries('Constant', 1)
        ops.pattern('Plain', 1, 1)

        # 施加梁均布荷载（kN/m）
        for i, beam_id in enumerate(beam_elements):
            # 如果已有自定义荷载，则使用，否则使用默认值
            load_value = self.beam_loads.get(beam_id, default_load)
            total_load = load_value
            # 如果启用自重，添加自重荷载
            if include_self_weight:
                beam_dimension = self.element_steels.get(beam_id, "HW200×200×8×12")  # 默认值
                _, _, _, beam_weight = self.get_steel_properties(beam_dimension)
                beam_self_weight = beam_weight * 9.81 / 1000  # kg/m * 9.81 m/s² → N/m → kN/m
                total_load += beam_self_weight
            ops.eleLoad('-ele', beam_id,
                        '-type', '-beamUniform', -total_load, 0.0)

        # 施加柱的自重（如果启用）
        if include_self_weight:
            for col_id in column_elements:
                # 获取柱的H型钢规格
                col_dimension = self.element_steels.get(col_id, "HW200×200×8×12")  # 默认值
                _, _, _, col_weight = self.get_steel_properties(col_dimension)

                # 获取柱的长度
                ele_nodes = ops.eleNodes(col_id)
                start_node = ele_nodes[0]
                end_node = ele_nodes[1]

                start_coord = ops.nodeCoord(start_node)
                end_coord = ops.nodeCoord(end_node)

                length = ((end_coord[0] - start_coord[0]) ** 2 + (end_coord[1] - start_coord[1]) ** 2) ** 0.5
                col_self_weight = col_weight * 9.81 / 1000  # kg/m * 9.81 m/s² → N/m → kN/m
                total_column_load = col_self_weight * length

                # 将柱自重作为节点荷载施加到柱顶节点
                ops.load(end_node, 0.0, -total_column_load, 0.0)

        # 施加节点荷载
        for node_id, (fx, fy, mz) in self.node_loads.items():
            ops.load(node_id, fx, fy, mz)

        # 施加梁集中荷载
        for ele_id, point_loads in self.beam_point_loads.items():
            for pos_ratio, fx, fy in point_loads:
                # OpenSees中的集中荷载使用比例位置
                ops.eleLoad('-ele', ele_id, '-type', '-beamPoint', fy, pos_ratio, fx, pos_ratio)

        # 分析设置
        ops.constraints('Transformation')
        ops.numberer('RCM')
        ops.system('BandGeneral')
        ops.test('NormDispIncr', 1.0e-6, 6, 2)
        ops.algorithm('Linear')
        ops.integrator('LoadControl', 1)
        ops.analysis('Static')
        ops.analyze(1)

        # 保存元素ID和分析数据
        self.column_elements = column_elements
        self.beam_elements = beam_elements
        analysis_data = {
            'spans': span_list,
            'height': height,
            'floors': floors,
            'E': E,
            'steel_grade': steel_grade,
            'default_load': default_load,
            'include_self_weight': include_self_weight
        }

        # 显示默认图
        self.plot_model_diagram()

        return analysis_data

    def on_canvas_click(self, event):
        """处理画布点击事件"""
        if event.inaxes != self.ax:
            return

        # 获取当前显示的图类型
        diagram_type = self.diagram_var.get()

        # 只在模型图或荷载图上允许点击选择
        if diagram_type not in ["模型图", "荷载图"]:
            return

        # 首先检查是否点击了节点
        clicked_node = None
        min_node_distance = float('inf')

        for node_tag in ops.getNodeTags():
            try:
                node_x, node_y = ops.nodeCoord(node_tag)
                distance = ((event.xdata - node_x) ** 2 + (event.ydata - node_y) ** 2) ** 0.5
                if distance < min_node_distance and distance < 0.5:  # 0.5m范围内的节点
                    min_node_distance = distance
                    clicked_node = node_tag
            except:
                continue

        if clicked_node:
            # 点击了节点，弹出菜单选择操作
            self.select_node_operation(clicked_node)
            return

        # 检查是否点击了梁或柱
        clicked_element = None
        min_distance = float('inf')

        # 检查梁
        for beam_id in self.beam_elements:
            try:
                ele_nodes = ops.eleNodes(beam_id)
                start_node = ele_nodes[0]
                end_node = ele_nodes[1]

                start_x, start_y = ops.nodeCoord(start_node)
                end_x, end_y = ops.nodeCoord(end_node)

                # 计算点击点到梁中心的距离
                center_x = (start_x + end_x) / 2
                center_y = (start_y + end_y) / 2

                distance = ((event.xdata - center_x) ** 2 + (event.ydata - center_y) ** 2) ** 0.5
                if distance < min_distance:
                    min_distance = distance

                    # 如果距离足够近，认为点击了该梁
                    if distance < max(abs(end_x - start_x), abs(end_y - start_y)) * 0.5:
                        clicked_element = beam_id
            except:
                continue

        # 检查柱
        for col_id in self.column_elements:
            try:
                ele_nodes = ops.eleNodes(col_id)
                start_node = ele_nodes[0]
                end_node = ele_nodes[1]

                start_x, start_y = ops.nodeCoord(start_node)
                end_x, end_y = ops.nodeCoord(end_node)

                # 计算点击点到柱中心的距离
                center_x = (start_x + end_x) / 2
                center_y = (start_y + end_y) / 2

                distance = ((event.xdata - center_x) ** 2 + (event.ydata - center_y) ** 2) ** 0.5
                if distance < min_distance:
                    min_distance = distance

                    # 如果距离足够近，认为点击了该柱
                    if distance < max(abs(end_x - start_x), abs(end_y - start_y)) * 0.5:
                        clicked_element = col_id
            except:
                continue

        if clicked_element:
            # 弹出菜单选择操作
            self.select_element_operation(clicked_element)

    def select_element_operation(self, element_id):
        """选择对元素执行的操作（修改荷载或H型钢规格）"""
        # 创建新窗口
        dialog = tk.Toplevel(self.parent_frame.winfo_toplevel())
        dialog.title(f"选择操作 - 元素 {element_id}")
        dialog.geometry("350x200")
        dialog.transient(self.parent_frame.winfo_toplevel())
        dialog.grab_set()

        # 添加标签
        element_type = "梁" if element_id in self.beam_elements else "柱"
        ttk.Label(dialog, text=f"元素 {element_id} ({element_type})").pack(pady=10)

        # 按钮框架
        button_frame = ttk.Frame(dialog)
        button_frame.pack(pady=15)

        def modify_load():
            dialog.destroy()
            self.modify_beam_load(element_id)

        def modify_steel():
            dialog.destroy()
            self.modify_element_steel(element_id)

        def add_point_load():
            dialog.destroy()
            self.add_beam_point_load(element_id)

        # 根据元素类型显示不同的按钮
        if element_id in self.beam_elements:
            # 梁可以修改荷载、H型钢规格和添加集中荷载
            ttk.Button(button_frame, text="修改均布荷载", command=modify_load).pack(side=tk.TOP, pady=2)
            ttk.Button(button_frame, text="添加集中荷载", command=add_point_load).pack(side=tk.TOP, pady=2)

        ttk.Button(button_frame, text="修改H型钢规格", command=modify_steel).pack(side=tk.TOP, pady=2)
        ttk.Button(button_frame, text="取消", command=dialog.destroy).pack(side=tk.TOP, pady=2)

    def select_node_operation(self, node_id):
        """选择对节点执行的操作（添加或修改节点荷载）"""
        # 创建新窗口
        dialog = tk.Toplevel(self.parent_frame.winfo_toplevel())
        dialog.title(f"选择操作 - 节点 {node_id}")
        dialog.geometry("350x200")
        dialog.transient(self.parent_frame.winfo_toplevel())
        dialog.grab_set()

        # 添加标签
        ttk.Label(dialog, text=f"节点 {node_id}").pack(pady=10)

        # 按钮框架
        button_frame = ttk.Frame(dialog)
        button_frame.pack(pady=15)

        def add_node_load():
            dialog.destroy()
            self.add_node_load(node_id)

        def remove_node_load():
            if node_id in self.node_loads:
                del self.node_loads[node_id]
                messagebox.showinfo("成功", f"节点 {node_id} 的荷载已删除")
            else:
                messagebox.showwarning("警告", f"节点 {node_id} 没有荷载")
            dialog.destroy()
            self.reanalyze_with_current_settings()

        # 按钮
        ttk.Button(button_frame, text="添加/修改节点荷载", command=add_node_load).pack(side=tk.TOP, pady=2)
        ttk.Button(button_frame, text="删除节点荷载", command=remove_node_load).pack(side=tk.TOP, pady=2)
        ttk.Button(button_frame, text="取消", command=dialog.destroy).pack(side=tk.TOP, pady=2)

    def add_node_load(self, node_id):
        """添加或修改节点荷载"""
        # 获取当前节点荷载值
        current_fx, current_fy, current_mz = self.node_loads.get(node_id, (0.0, 0.0, 0.0))

        # 创建新窗口
        dialog = tk.Toplevel(self.parent_frame.winfo_toplevel())
        dialog.title(f"节点 {node_id} 荷载")
        dialog.geometry("350x250")
        dialog.transient(self.parent_frame.winfo_toplevel())
        dialog.grab_set()

        # 添加标签
        ttk.Label(dialog, text=f"节点 {node_id} 荷载:").pack(pady=10)

        # FX输入
        fx_frame = ttk.Frame(dialog)
        fx_frame.pack(pady=5)
        ttk.Label(fx_frame, text="FX (kN):").pack(side=tk.LEFT)
        fx_var = tk.DoubleVar(value=current_fx)
        fx_entry = ttk.Entry(fx_frame, textvariable=fx_var, width=10)
        fx_entry.pack(side=tk.LEFT, padx=5)

        # FY输入
        fy_frame = ttk.Frame(dialog)
        fy_frame.pack(pady=5)
        ttk.Label(fy_frame, text="FY (kN):").pack(side=tk.LEFT)
        fy_var = tk.DoubleVar(value=current_fy)
        fy_entry = ttk.Entry(fy_frame, textvariable=fy_var, width=10)
        fy_entry.pack(side=tk.LEFT, padx=5)

        # MZ输入
        mz_frame = ttk.Frame(dialog)
        mz_frame.pack(pady=5)
        ttk.Label(mz_frame, text="MZ (kN·m):").pack(side=tk.LEFT)
        mz_var = tk.DoubleVar(value=current_mz)
        mz_entry = ttk.Entry(mz_frame, textvariable=mz_var, width=10)
        mz_entry.pack(side=tk.LEFT, padx=5)

        # 按钮框架
        button_frame = ttk.Frame(dialog)
        button_frame.pack(pady=15)

        def save_node_load():
            try:
                fx = fx_var.get()
                fy = fy_var.get()
                mz = mz_var.get()
                self.node_loads[node_id] = (fx, fy, mz)
                messagebox.showinfo("成功", f"节点 {node_id} 的荷载已更新为 FX:{fx}kN, FY:{fy}kN, MZ:{mz}kN·m")
                dialog.destroy()
                # 自动重新分析
                self.reanalyze_with_current_settings()
            except:
                messagebox.showerror("错误", "请输入有效的荷载值")

        def remove_node_load():
            if node_id in self.node_loads:
                del self.node_loads[node_id]
            messagebox.showinfo("成功", f"节点 {node_id} 的荷载已删除")
            dialog.destroy()
            # 自动重新分析
            self.reanalyze_with_current_settings()

        # 按钮
        ttk.Button(button_frame, text="保存", command=save_node_load).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="删除", command=remove_node_load).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="取消", command=dialog.destroy).pack(side=tk.LEFT, padx=5)

    def modify_beam_load(self, beam_id):
        """修改梁的荷载值"""
        # 获取当前梁的荷载值
        current_load = self.beam_loads.get(beam_id, 5.0)  # 默认值

        # 创建新窗口
        dialog = tk.Toplevel(self.parent_frame.winfo_toplevel())
        dialog.title(f"修改梁 {beam_id} 的荷载")
        dialog.geometry("300x150")
        dialog.transient(self.parent_frame.winfo_toplevel())
        dialog.grab_set()

        # 添加标签
        ttk.Label(dialog, text=f"梁单元 {beam_id} 当前荷载:").pack(pady=10)

        # 输入框
        load_var = tk.DoubleVar(value=current_load)
        entry = ttk.Entry(dialog, textvariable=load_var, width=15)
        entry.pack(pady=5)

        # 按钮框架
        button_frame = ttk.Frame(dialog)
        button_frame.pack(pady=15)

        def save_load():
            try:
                new_load = load_var.get()
                self.beam_loads[beam_id] = new_load
                messagebox.showinfo("成功", f"梁 {beam_id} 的荷载已更新为 {new_load} kN/m")
                dialog.destroy()
                # 自动重新分析
                self.reanalyze_with_current_settings()
            except:
                messagebox.showerror("错误", "请输入有效的荷载值")

        def reset_load():
            if beam_id in self.beam_loads:
                del self.beam_loads[beam_id]
            messagebox.showinfo("成功", f"梁 {beam_id} 的荷载已恢复默认值")
            dialog.destroy()
            # 自动重新分析
            self.reanalyze_with_current_settings()

        # 按钮
        ttk.Button(button_frame, text="保存", command=save_load).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="恢复默认", command=reset_load).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="取消", command=dialog.destroy).pack(side=tk.LEFT, padx=5)

    def add_beam_point_load(self, beam_id):
        """在梁上添加集中荷载"""
        # 创建新窗口
        dialog = tk.Toplevel(self.parent_frame.winfo_toplevel())
        dialog.title(f"梁 {beam_id} 集中荷载")
        dialog.geometry("400x250")
        dialog.transient(self.parent_frame.winfo_toplevel())
        dialog.grab_set()

        # 添加标签
        ttk.Label(dialog, text=f"梁单元 {beam_id} 集中荷载:").pack(pady=10)

        # 位置比例输入 (0-1之间)
        pos_frame = ttk.Frame(dialog)
        pos_frame.pack(pady=5)
        ttk.Label(pos_frame, text="位置比例 (0-1):").pack(side=tk.LEFT)
        pos_var = tk.DoubleVar(value=0.5)
        pos_entry = ttk.Entry(pos_frame, textvariable=pos_var, width=10)
        pos_entry.pack(side=tk.LEFT, padx=5)

        # FX输入
        fx_frame = ttk.Frame(dialog)
        fx_frame.pack(pady=5)
        ttk.Label(fx_frame, text="FX (kN):").pack(side=tk.LEFT)
        fx_var = tk.DoubleVar(value=0.0)
        fx_entry = ttk.Entry(fx_frame, textvariable=fx_var, width=10)
        fx_entry.pack(side=tk.LEFT, padx=5)

        # FY输入
        fy_frame = ttk.Frame(dialog)
        fy_frame.pack(pady=5)
        ttk.Label(fy_frame, text="FY (kN):").pack(side=tk.LEFT)
        fy_var = tk.DoubleVar(value=-10.0)  # 默认向下
        fy_entry = ttk.Entry(fy_frame, textvariable=fy_var, width=10)
        fy_entry.pack(side=tk.LEFT, padx=5)

        # 按钮框架
        button_frame = ttk.Frame(dialog)
        button_frame.pack(pady=15)

        def save_point_load():
            try:
                pos = pos_var.get()
                if pos < 0 or pos > 1:
                    raise ValueError("位置比例必须在0到1之间")
                fx = fx_var.get()
                fy = fy_var.get()

                # 添加到列表中
                if beam_id not in self.beam_point_loads:
                    self.beam_point_loads[beam_id] = []
                self.beam_point_loads[beam_id].append((pos, fx, fy))

                messagebox.showinfo("成功", f"梁 {beam_id} 已添加集中荷载: 位置{pos}, FX:{fx}kN, FY:{fy}kN")
                dialog.destroy()
                # 自动重新分析
                self.reanalyze_with_current_settings()
            except Exception as e:
                messagebox.showerror("错误", f"请输入有效的荷载值: {str(e)}")

        def remove_all_point_loads():
            if beam_id in self.beam_point_loads:
                del self.beam_point_loads[beam_id]
            messagebox.showinfo("成功", f"梁 {beam_id} 的所有集中荷载已删除")
            dialog.destroy()
            # 自动重新分析
            self.reanalyze_with_current_settings()

        # 按钮
        ttk.Button(button_frame, text="添加集中荷载", command=save_point_load).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="清空集中荷载", command=remove_all_point_loads).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="取消", command=dialog.destroy).pack(side=tk.LEFT, padx=5)

    def modify_element_steel(self, element_id):
        """修改元素的H型钢规格"""
        # 获取当前元素的H型钢规格
        if element_id in self.element_steels:
            current_steel = self.element_steels[element_id]
        else:
            # 使用默认值
            current_steel = "HW200×200×8×12"

        # 获取H型钢选项
        if self.h_steel_data is not None:
            steel_options = list(self.h_steel_data['Dimension'].values)
        else:
            steel_options = ["HW200×200×8×12"]  # 默认值

        # 创建新窗口
        dialog = tk.Toplevel(self.parent_frame.winfo_toplevel())
        dialog.title(f"修改元素 {element_id} 的H型钢规格")
        dialog.geometry("400x250")
        dialog.transient(self.parent_frame.winfo_toplevel())
        dialog.grab_set()

        # 添加标签
        element_type = "梁" if element_id in self.beam_elements else "柱"
        ttk.Label(dialog, text=f"{element_type}单元 {element_id} H型钢规格:").pack(pady=10)

        # 下拉列表
        steel_var = tk.StringVar(value=current_steel)
        steel_combo = ttk.Combobox(dialog, textvariable=steel_var,
                                   values=steel_options, width=30, state="readonly")
        steel_combo.pack(pady=5)

        # 显示当前规格的参数
        def update_params(*args):
            try:
                steel = steel_var.get()
                _, _, _, weight = self.get_steel_properties(steel)

                # 获取参数
                row = self.h_steel_data[self.h_steel_data['Dimension'] == steel]
                if not row.empty:
                    area = row.iloc[0]['A']
                    ix = row.iloc[0]['Ix']
                    iy = row.iloc[0]['Iy']

                    param_text.config(state=tk.NORMAL)
                    param_text.delete(1.0, tk.END)
                    param_text.insert(tk.END, f"截面面积: {area} cm²\n")
                    param_text.insert(tk.END, f"x轴惯性矩: {ix} cm⁴\n")
                    param_text.insert(tk.END, f"y轴惯性矩: {iy} cm⁴\n")
                    param_text.insert(tk.END, f"每米重量: {weight} kg/m\n")
                    param_text.config(state=tk.DISABLED)
            except:
                pass

        steel_combo.bind("<<ComboboxSelected>>", update_params)

        # 参数显示框
        param_frame = ttk.Frame(dialog)
        param_frame.pack(pady=5)
        ttk.Label(param_frame, text="规格参数:").pack(anchor=tk.W)
        param_text = tk.Text(param_frame, width=30, height=4, state=tk.DISABLED)
        param_text.pack()

        # 更新初始参数
        update_params()

        # 按钮框架
        button_frame = ttk.Frame(dialog)
        button_frame.pack(pady=15)

        def save_steel():
            try:
                new_steel = steel_var.get()
                self.element_steels[element_id] = new_steel
                messagebox.showinfo("成功", f"元素 {element_id} 的H型钢规格已更新为 {new_steel}")
                dialog.destroy()
                # 自动重新分析
                self.reanalyze_with_current_settings()
            except:
                messagebox.showerror("错误", "请选择有效的H型钢规格")

        def reset_steel():
            if element_id in self.element_steels:
                del self.element_steels[element_id]
            messagebox.showinfo("成功", f"元素 {element_id} 的H型钢规格已恢复默认值")
            dialog.destroy()
            # 自动重新分析
            self.reanalyze_with_current_settings()

        # 按钮
        ttk.Button(button_frame, text="保存", command=save_steel).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="恢复默认", command=reset_steel).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="取消", command=dialog.destroy).pack(side=tk.LEFT, padx=5)

    def reanalyze_with_current_settings(self):
        """使用当前设置重新分析"""
        if not hasattr(self, 'current_analysis_data'):
            messagebox.showwarning("警告", "请先进行一次分析")
            return

        try:
            # 获取当前参数
            span_list = self.current_analysis_data['spans']
            height = self.current_analysis_data['height']
            floors = self.current_analysis_data['floors']
            steel_grade = self.current_analysis_data['steel_grade']
            default_load = self.current_analysis_data['default_load']
            include_self_weight = self.current_analysis_data['include_self_weight']

            # 重新执行分析
            self.current_analysis_data = self.analyze_frame(
                span_list, height, floors, steel_grade, default_load, include_self_weight
            )
        except Exception as e:
            messagebox.showerror("错误", f"重新分析过程中出现错误:\n{str(e)}")

    def initialize_plot(self):
        """初始化绘图"""
        self.ax.set_title("钢框架结构图")
        self.ax.axis('equal')
        self.ax.grid(True)
        self.canvas.draw()

    def on_diagram_change(self, event=None):
        """根据选择绘制相应的内力图"""
        diagram_type = self.diagram_var.get()

        if diagram_type == "模型图":
            self.plot_model_diagram()
        elif diagram_type == "荷载图":
            self.plot_load_diagram()
        elif diagram_type == "反力图":
            self.plot_reaction_diagram()
        elif diagram_type == "变形图":
            self.plot_deformation_diagram()
        elif diagram_type == "轴力图":
            self.plot_axial_force_diagram()
        elif diagram_type == "剪力图":
            self.plot_shear_force_diagram()
        elif diagram_type == "弯矩图":
            self.plot_moment_diagram()

    def plot_model_diagram(self):
        self.ax.clear()
        opsv.plot_model(ax=self.ax)

        # 在模型图上标注梁的荷载值和H型钢规格
        for beam_id in self.beam_elements:
            try:
                ele_nodes = ops.eleNodes(beam_id)
                start_node = ele_nodes[0]
                end_node = ele_nodes[1]

                start_x, start_y = ops.nodeCoord(start_node)
                end_x, end_y = ops.nodeCoord(end_node)

                # 计算梁中点位置
                mid_x = (start_x + end_x) / 2
                mid_y = (start_y + end_y) / 2

                # 获取该梁的荷载值
                load_value = self.beam_loads.get(beam_id, 5.0)  # 默认值

                # 计算总荷载（包括自重）
                total_load = load_value
                if self.current_analysis_data and self.current_analysis_data.get('include_self_weight', False):
                    beam_dimension = self.element_steels.get(beam_id, "HW200×200×8×12")
                    _, _, _, beam_weight = self.get_steel_properties(beam_dimension)
                    beam_self_weight = beam_weight * 9.81 / 1000  # kg/m * 9.81 m/s² → N/m → kN/m
                    total_load += beam_self_weight

                # 获取该梁的H型钢规格
                beam_dimension = self.element_steels.get(beam_id, "HW200×200×8×12")

                # 在梁上方标注荷载值和H型钢规格
                load_label = f'{total_load:.2f}kN/m'
                if self.current_analysis_data and self.current_analysis_data.get('include_self_weight', False):
                    load_label += f'\n(含{beam_self_weight:.2f}kN/m自重)'

                # 在梁下方标注荷载值和H型钢规格（避免与杆件编号重叠）
                self.ax.text(
                    mid_x, mid_y - 0.2,
                    f'{load_label}\n{beam_dimension}',
                    ha='center',
                    va='top',  # 文本顶部对齐，显示在 (mid_x, mid_y-0.3) 下方
                    fontsize=8,
                    bbox=dict(boxstyle="round,pad=0.2", facecolor='yellow', alpha=0.7)
                )

                # 标注集中荷载
                if beam_id in self.beam_point_loads:
                    for pos_ratio, fx, fy in self.beam_point_loads[beam_id]:
                        # 计算集中荷载的位置
                        point_x = start_x + (end_x - start_x) * pos_ratio
                        point_y = start_y + (end_y - start_y) * pos_ratio

                        # 画箭头表示集中荷载
                        arrow_length = 0.3
                        self.ax.arrow(point_x, point_y + 0.3, -fx * 0.01, -fy * 0.01,
                                      head_width=0.05, head_length=0.05, fc='red', ec='red')

                        # 标注荷载值
                        self.ax.text(point_x, point_y + 0.5, f'F({fx:.1f}, {fy:.1f})',
                                     ha='center', va='bottom', fontsize=7,
                                     bbox=dict(boxstyle="round,pad=0.1", facecolor='orange', alpha=0.7))
            except:
                continue

        # 在模型图上标注柱的H型钢规格
        for col_id in self.column_elements:
            try:
                ele_nodes = ops.eleNodes(col_id)
                start_node = ele_nodes[0]
                end_node = ele_nodes[1]

                start_x, start_y = ops.nodeCoord(start_node)
                end_x, end_y = ops.nodeCoord(end_node)

                # 计算柱中点位置
                mid_x = (start_x + end_x) / 2
                mid_y = (start_y + end_y) / 2

                # 获取该柱的H型钢规格
                col_dimension = self.element_steels.get(col_id, "HW200×200×8×12")

                # 在柱旁边标注H型钢规格
                self.ax.text(mid_x + 0.3, mid_y, f'{col_dimension}',
                             ha='left', va='center', fontsize=8,
                             bbox=dict(boxstyle="round,pad=0.2", facecolor='lightgreen', alpha=0.7))
            except:
                continue

        # 标注节点荷载
        for node_id, (fx, fy, mz) in self.node_loads.items():
            try:
                node_x, node_y = ops.nodeCoord(node_id)

                # 画箭头表示节点荷载
                arrow_length = 0.3
                if fx != 0 or fy != 0:
                    self.ax.arrow(node_x, node_y, -fx * 0.01, -fy * 0.01,
                                  head_width=0.05, head_length=0.05, fc='red', ec='red')

                # 标注荷载值
                load_text = f'F({fx:.1f}, {fy:.1f})'
                if mz != 0:
                    load_text += f'\nMz:{mz:.1f}'

                self.ax.text(node_x, node_y + 0.3, load_text,
                             ha='center', va='bottom', fontsize=7,
                             bbox=dict(boxstyle="round,pad=0.1", facecolor='cyan', alpha=0.7))
            except:
                continue

        # 如果启用了自重，在图上标注自重信息
        if self.current_analysis_data and self.current_analysis_data.get('include_self_weight', False):
            self.ax.text(0.02, 0.98, "考虑梁柱自重",
                         transform=self.ax.transAxes,
                         fontsize=10,
                         verticalalignment='top',
                         bbox=dict(boxstyle="round,pad=0.3", facecolor='lightcoral', alpha=0.7))

        self.ax.set_title("钢框架结构模型图 (点击梁/柱/节点可修改参数)")
        self.ax.axis('equal')
        self.ax.grid(True)
        self.canvas.draw()

    def plot_load_diagram(self):
        self.ax.clear()
        try:
            opsv.plot_load(ax=self.ax, nep=11, node_supports=True)

            # 在荷载图上也标注梁的荷载值和H型钢规格
            for beam_id in self.beam_elements:
                try:
                    ele_nodes = ops.eleNodes(beam_id)
                    start_node = ele_nodes[0]
                    end_node = ele_nodes[1]

                    start_x, start_y = ops.nodeCoord(start_node)
                    end_x, end_y = ops.nodeCoord(end_node)

                    # 计算梁中点位置
                    mid_x = (start_x + end_x) / 2
                    mid_y = (start_y + end_y) / 2

                    # 获取该梁的荷载值
                    load_value = self.beam_loads.get(beam_id, 5.0)  # 默认值

                    # 计算总荷载（包括自重）
                    total_load = load_value
                    if self.current_analysis_data and self.current_analysis_data.get('include_self_weight', False):
                        beam_dimension = self.element_steels.get(beam_id, "HW200×200×8×12")
                        _, _, _, beam_weight = self.get_steel_properties(beam_dimension)
                        beam_self_weight = beam_weight * 9.81 / 1000  # kg/m * 9.81 m/s² → N/m → kN/m
                        total_load += beam_self_weight

                    # 获取该梁的H型钢规格
                    beam_dimension = self.element_steels.get(beam_id, "HW200×200×8×12")

                    # 在梁上方标注荷载值和H型钢规格
                    load_label = f'{total_load:.2f}kN/m'
                    if self.current_analysis_data and self.current_analysis_data.get('include_self_weight', False):
                        load_label += f'\n(含{beam_self_weight:.2f}kN/m自重)'

                    self.ax.text(mid_x, mid_y + 0.2, f'{load_label}\n{beam_dimension}',
                                 ha='center', va='bottom', fontsize=8,
                                 bbox=dict(boxstyle="round,pad=0.2", facecolor='yellow', alpha=0.7))
                except:
                    continue

            # 在荷载图上也标注柱的H型钢规格
            for col_id in self.column_elements:
                try:
                    ele_nodes = ops.eleNodes(col_id)
                    start_node = ele_nodes[0]
                    end_node = ele_nodes[1]

                    start_x, start_y = ops.nodeCoord(start_node)
                    end_x, end_y = ops.nodeCoord(end_node)

                    # 计算柱中点位置
                    mid_x = (start_x + end_x) / 2
                    mid_y = (start_y + end_y) / 2

                    # 获取该柱的H型钢规格
                    col_dimension = self.element_steels.get(col_id, "HW200×200×8×12")

                    # 在柱旁边标注H型钢规格
                    self.ax.text(mid_x + 0.3, mid_y, f'{col_dimension}',
                                 ha='left', va='center', fontsize=8,
                                 bbox=dict(boxstyle="round,pad=0.2", facecolor='lightgreen', alpha=0.7))
                except:
                    continue

            # 如果启用了自重，在图上标注自重信息
            if self.current_analysis_data and self.current_analysis_data.get('include_self_weight', False):
                self.ax.text(0.02, 0.98, "考虑梁柱自重",
                             transform=self.ax.transAxes,
                             fontsize=10,
                             verticalalignment='top',
                             bbox=dict(boxstyle="round,pad=0.3", facecolor='lightcoral', alpha=0.7))

            self.ax.set_title("荷载分布图 (kN/m) - 点击梁/柱/节点可修改参数")
            self.ax.axis('equal')
            self.ax.grid(True)
        except Exception as e:
            self.ax.text(0.5, 0.5, f"荷载图绘制失败: {str(e)}",
                         horizontalalignment='center', verticalalignment='center',
                         transform=self.ax.transAxes, fontsize=12)
        self.canvas.draw()

    def plot_reaction_diagram(self):
        self.ax.clear()
        try:
            opsv.plot_reactions(ax=self.ax)
            # 如果启用了自重，在图上标注自重信息
            if self.current_analysis_data and self.current_analysis_data.get('include_self_weight', False):
                self.ax.text(0.02, 0.98, "考虑梁柱自重",
                             transform=self.ax.transAxes,
                             fontsize=10,
                             verticalalignment='top',
                             bbox=dict(boxstyle="round,pad=0.3", facecolor='lightcoral', alpha=0.7))
            self.ax.set_title("支座反力图 (kN, kN·m)")
            self.ax.axis('equal')
            self.ax.grid(True)
        except Exception as e:
            self.ax.text(0.5, 0.5, f"反力图绘制失败: {str(e)}",
                         horizontalalignment='center', verticalalignment='center',
                         transform=self.ax.transAxes, fontsize=12)
        self.canvas.draw()

    def plot_deformation_diagram(self):
        self.ax.clear()
        opsv.plot_defo(ax=self.ax, sfac=self.def_scale, unDefoFlag=1,
                       fmt_undefo={'color': 'gray', 'linestyle': '--'})
        # 如果启用了自重，在图上标注自重信息
        if self.current_analysis_data and self.current_analysis_data.get('include_self_weight', False):
            self.ax.text(0.02, 0.98, "考虑梁柱自重",
                         transform=self.ax.transAxes,
                         fontsize=10,
                         verticalalignment='top',
                         bbox=dict(boxstyle="round,pad=0.3", facecolor='lightcoral', alpha=0.7))
        self.ax.set_title(f"结构变形图 (放大{self.def_scale:.1f}倍)")
        self.ax.axis('equal')
        self.ax.grid(True)

        # 标注节点位移
        for node_tag in ops.getNodeTags():
            try:
                disp = ops.nodeDisp(node_tag)
                ux = disp[0] * 1000  # m → mm
                uy = disp[1] * 1000  # m → mm
                x, y = ops.nodeCoord(node_tag)  # 获取节点坐标
                self.ax.annotate(f'U({ux:.2f}, {uy:.2f})mm', (x, y),
                                 xytext=(5, 5), textcoords='offset points',
                                 fontsize=8, color='red', weight='bold',
                                 bbox=dict(boxstyle="round,pad=0.2", fc="yellow", alpha=0.7))
            except:
                continue

        # 标注梁跨中挠度
        for ele_id in self.beam_elements:
            try:
                # 获取单元两端节点坐标
                ele_nodes = ops.eleNodes(ele_id)
                start_node = ele_nodes[0]
                end_node = ele_nodes[1]

                start_coord = np.array(ops.nodeCoord(start_node))  # [x, y]
                end_coord = np.array(ops.nodeCoord(end_node))  # [x, y]

                # 计算单元中点坐标（未变形）
                mid_coord = (start_coord + end_coord) / 2

                # 获取两端位移
                start_disp = np.array(ops.nodeDisp(start_node))  # [ux, uy, rz]
                end_disp = np.array(ops.nodeDisp(end_node))  # [ux, uy, rz]

                # 插值计算中点位移（线性插值）
                mid_disp = (start_disp + end_disp) / 2
                mid_uy = mid_disp[1] * 1000  # m → mm

                # 标注挠度
                self.ax.annotate(f'δ_mid={mid_uy:.2f}mm', (mid_coord[0], mid_coord[1]),
                                 xytext=(0, 10), textcoords='offset points',
                                 fontsize=8, color='blue', weight='bold',
                                 bbox=dict(boxstyle="round,pad=0.2", fc="lightblue", alpha=0.7))
            except:
                continue

        self.canvas.draw()

    def plot_axial_force_diagram(self):
        self.ax.clear()
        try:
            opsv.section_force_diagram_2d('N', self.axial_scale, ax=self.ax, number_format='.1f')
            # 如果启用了自重，在图上标注自重信息
            if self.current_analysis_data and self.current_analysis_data.get('include_self_weight', False):
                self.ax.text(0.02, 0.98, "考虑梁柱自重",
                             transform=self.ax.transAxes,
                             fontsize=10,
                             verticalalignment='top',
                             bbox=dict(boxstyle="round,pad=0.3", facecolor='lightcoral', alpha=0.7))
            self.ax.set_title(f"轴力图 (单位: kN, 比例: {self.axial_scale:.3f})")
            self.ax.axis('equal')
            self.ax.grid(True)
        except Exception as e:
            self.ax.text(0.5, 0.5, f"轴力图绘制失败: {str(e)}",
                         horizontalalignment='center', verticalalignment='center',
                         transform=self.ax.transAxes, fontsize=12)
        self.canvas.draw()

    def plot_shear_force_diagram(self):
        self.ax.clear()
        try:
            opsv.section_force_diagram_2d('V', self.shear_scale, ax=self.ax, number_format='.1f')
            # 如果启用了自重，在图上标注自重信息
            if self.current_analysis_data and self.current_analysis_data.get('include_self_weight', False):
                self.ax.text(0.02, 0.98, "考虑梁柱自重",
                             transform=self.ax.transAxes,
                             fontsize=10,
                             verticalalignment='top',
                             bbox=dict(boxstyle="round,pad=0.3", facecolor='lightcoral', alpha=0.7))
            self.ax.set_title(f"剪力图 (单位: kN, 比例: {self.shear_scale:.3f})")
            self.ax.axis('equal')
            self.ax.grid(True)
        except Exception as e:
            self.ax.text(0.5, 0.5, f"剪力图绘制失败: {str(e)}",
                         horizontalalignment='center', verticalalignment='center',
                         transform=self.ax.transAxes, fontsize=12)
        self.canvas.draw()

    def plot_moment_diagram(self):
        self.ax.clear()
        try:
            opsv.section_force_diagram_2d('M', self.moment_scale, ax=self.ax, number_format='.1f')
            # 如果启用了自重，在图上标注自重信息
            if self.current_analysis_data and self.current_analysis_data.get('include_self_weight', False):
                self.ax.text(0.02, 0.98, "考虑梁柱自重",
                             transform=self.ax.transAxes,
                             fontsize=10,
                             verticalalignment='top',
                             bbox=dict(boxstyle="round,pad=0.3", facecolor='lightcoral', alpha=0.7))
            self.ax.set_title(f"弯矩图 (单位: kN·m, 比例: {self.moment_scale:.3f})")
            self.ax.axis('equal')
            self.ax.grid(True)
        except Exception as e:
            self.ax.text(0.5, 0.5, f"弯矩图绘制失败: {str(e)}",
                         horizontalalignment='center', verticalalignment='center',
                         transform=self.ax.transAxes, fontsize=12)
        self.canvas.draw()

    def display_results(self, result_text_widget):
        """输出内力结果到指定的文本框（单位：kN / kN·m）"""
        if not self.current_analysis_data:
            return

        result_text_widget.delete(1.0, tk.END)
        result_text_widget.insert(tk.END, "钢框架分析结果\n")
        result_text_widget.insert(tk.END, "=" * 50 + "\n\n")

        # 输出钢材信息
        result_text_widget.insert(tk.END, f"钢材强度等级: {self.current_analysis_data['steel_grade']}\n")
        result_text_widget.insert(tk.END, f"钢材弹性模量: {self.current_analysis_data['E'] / 1e6:.0f} GPa\n\n")

        # 输出自重信息
        if self.current_analysis_data.get('include_self_weight', False):
            result_text_widget.insert(tk.END, "自重信息:\n")
            result_text_widget.insert(tk.END, "-" * 15 + "\n")
            result_text_widget.insert(tk.END, "梁柱自重已计入分析\n")
            result_text_widget.insert(tk.END, "钢材容重: 78.5 kN/m³ (7850 kg/m³ × 9.81 m/s²)\n\n")

        # 输出节点荷载信息
        if self.node_loads:
            result_text_widget.insert(tk.END, "节点荷载:\n")
            result_text_widget.insert(tk.END, "-" * 20 + "\n")
            for node_id, (fx, fy, mz) in self.node_loads.items():
                result_text_widget.insert(tk.END, f"节点 {node_id}: FX={fx}kN, FY={fy}kN, MZ={mz}kN·m\n")
            result_text_widget.insert(tk.END, "\n")

        # 输出梁集中荷载信息
        if self.beam_point_loads:
            result_text_widget.insert(tk.END, "梁集中荷载:\n")
            result_text_widget.insert(tk.END, "-" * 20 + "\n")
            for ele_id, point_loads in self.beam_point_loads.items():
                for pos_ratio, fx, fy in point_loads:
                    result_text_widget.insert(tk.END, f"梁 {ele_id}: 位置={pos_ratio:.2f}, FX={fx}kN, FY={fy}kN\n")
            result_text_widget.insert(tk.END, "\n")

        # 柱内力
        result_text_widget.insert(tk.END, "柱内力:\n")
        result_text_widget.insert(tk.END, "-" * 20 + "\n")
        for i, ele_id in enumerate(self.column_elements):
            try:
                forces = ops.eleResponse(ele_id, 'force')  # 已是 kN / kN·m
                axial_force = forces[1]
                shear_force = forces[0]
                moment_i = forces[2]
                moment_j = forces[5]

                # 获取该柱的H型钢规格
                col_dimension = self.element_steels.get(ele_id, "HW200×200×8×12")
                _, _, _, col_weight = self.get_steel_properties(col_dimension)
                col_self_weight = col_weight * 9.81 / 1000  # kg/m * 9.81 m/s² → N/m → kN/m

                result_text_widget.insert(tk.END, f"柱 {i + 1} (单元 {ele_id}, 规格: {col_dimension}):\n")
                result_text_widget.insert(tk.END, f"  每米重量: {col_weight:.1f} kg/m\n")
                result_text_widget.insert(tk.END, f"  每米自重: {col_self_weight:.3f} kN/m\n")
                result_text_widget.insert(tk.END, f"  轴力: {axial_force:.2f} kN\n")
                result_text_widget.insert(tk.END, f"  剪力: {shear_force:.2f} kN\n")
                result_text_widget.insert(tk.END, f"  I端弯矩: {moment_i:.2f} kN·m\n")
                result_text_widget.insert(tk.END, f"  J端弯矩: {moment_j:.2f} kN·m\n\n")
            except:
                result_text_widget.insert(tk.END, f"柱 {i + 1} (单元 {ele_id}): 无法获取内力\n\n")

        # 梁内力
        result_text_widget.insert(tk.END, "梁内力:\n")
        result_text_widget.insert(tk.END, "-" * 20 + "\n")
        for i, ele_id in enumerate(self.beam_elements):
            try:
                forces = ops.eleResponse(ele_id, 'force')  # 已是 kN / kN·m
                axial_force = forces[0]
                shear_force_i = forces[1]
                moment_i = forces[2]
                shear_force_j = forces[4]
                moment_j = forces[5]

                # 获取该梁的荷载值和H型钢规格
                load_value = self.beam_loads.get(ele_id, self.current_analysis_data['default_load'])

                # 计算总荷载（包括自重）
                total_load = load_value
                if self.current_analysis_data.get('include_self_weight', False):
                    beam_dimension = self.element_steels.get(ele_id, "HW200×200×8×12")
                    _, _, _, beam_weight = self.get_steel_properties(beam_dimension)
                    beam_self_weight = beam_weight * 9.81 / 1000  # kg/m * 9.81 m/s² → N/m → kN/m
                    total_load += beam_self_weight

                beam_dimension = self.element_steels.get(ele_id, "HW200×200×8×12")
                _, _, _, beam_weight = self.get_steel_properties(beam_dimension)

                result_text_widget.insert(tk.END,
                                          f"梁 {i + 1} (单元 {ele_id}, 荷载: {total_load} kN/m, 规格: {beam_dimension}):\n")
                if self.current_analysis_data.get('include_self_weight', False):
                    result_text_widget.insert(tk.END,
                                              f"  (其中自重: {beam_self_weight:.3f} kN/m, 每米重量: {beam_weight:.1f} kg/m)\n")
                result_text_widget.insert(tk.END, f"  轴力: {axial_force:.2f} kN\n")
                result_text_widget.insert(tk.END, f"  I端剪力: {shear_force_i:.2f} kN\n")
                result_text_widget.insert(tk.END, f"  J端剪力: {shear_force_j:.2f} kN\n")
                result_text_widget.insert(tk.END, f"  I端弯矩: {moment_i:.2f} kN·m\n")
                result_text_widget.insert(tk.END, f"  J端弯矩: {moment_j:.2f} kN·m\n\n")
            except:
                result_text_widget.insert(tk.END, f"梁 {i + 1} (单元 {ele_id}): 无法获取内力\n\n")

        # 节点位移
        result_text_widget.insert(tk.END, "节点位移:\n")
        result_text_widget.insert(tk.END, "-" * 15 + "\n")
        for node_tag in ops.getNodeTags():
            try:
                disp = ops.nodeDisp(node_tag)
                result_text_widget.insert(tk.END,
                                          f"节点 {node_tag}: UX={disp[0]:.6f}m, UY={disp[1]:.6f}m, RZ={disp[2]:.6f}rad\n")
            except:
                result_text_widget.insert(tk.END, f"节点 {node_tag}: 无法获取位移\n")




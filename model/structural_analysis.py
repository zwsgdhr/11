# model/structural_analysis.py
"""
钢框架结构分析核心算法包
包含结构分析、内力计算、规范验算等核心算法
"""
import math
import pandas as pd
import numpy as np
import os


def load_h_steel_data():
    """加载H型钢规格数据"""
    try:
        file_path = "H型钢规格参数表.xlsx"
        if os.path.exists(file_path):
            df = pd.read_excel(file_path)
            return df
    except Exception as e:
        print(f"加载H型钢规格表失败: {str(e)}")
        return None


def get_steel_properties(dimension, h_steel_data=None):
    """获取H型钢截面属性"""
    if h_steel_data is None:
        return 0.006353, 4.72e-5, 1.6e-5, 49.9

    row = h_steel_data[h_steel_data['Dimension'] == dimension]
    if row.empty:
        print(f"未找到H型钢规格: {dimension}")
        return 0.006353, 4.72e-5, 1.6e-5, 49.9

    area_cm2 = row.iloc[0]['A']
    ix_cm4 = row.iloc[0]['Ix']
    iy_cm4 = row.iloc[0]['Iy']
    weight_kg_m = row.iloc[0]['G']

    area_m2 = area_cm2 / 10000
    ix_m4 = ix_cm4 / 100000000
    iy_m4 = iy_cm4 / 100000000

    return area_m2, ix_m4, iy_m4, weight_kg_m


def get_steel_geometry(dimension, h_steel_data=None):
    """获取H型钢几何尺寸"""
    if h_steel_data is None:
        return 0.2, 0.2, 0.008, 0.012

    row = h_steel_data[h_steel_data['Dimension'] == dimension]
    if row.empty:
        print(f"未找到H型钢规格: {dimension}")
        return 0.2, 0.2, 0.008, 0.012

    h_mm = row.iloc[0]['H']
    b_mm = row.iloc[0]['B']
    tw_mm = row.iloc[0]['T']
    tf_mm = row.iloc[0]['Tf']

    h_m = h_mm / 1000
    b_m = b_mm / 1000
    tw_m = tw_mm / 1000
    tf_m = tf_mm / 1000

    return h_m, b_m, tw_m, tf_m


def get_steel_section_modulus(dimension, h_steel_data=None):
    """获取H型钢截面模量"""
    if h_steel_data is None:
        return 0.000756, 0.000267

    row = h_steel_data[h_steel_data['Dimension'] == dimension]
    if row.empty:
        print(f"未找到H型钢规格: {dimension}")
        return 0.000756, 0.000267

    wx_cm3 = row.iloc[0]['Wx']
    wy_cm3 = row.iloc[0]['Wy']

    wx_m3 = wx_cm3 / 1000000
    wy_m3 = wy_cm3 / 1000000

    return wx_m3, wy_m3


def get_steel_radii_of_gyration(dimension, h_steel_data=None):
    """获取H型钢回转半径"""
    if h_steel_data is None:
        return 0.0418, 0.0248

    row = h_steel_data[h_steel_data['Dimension'] == dimension]
    if row.empty:
        print(f"未找到H型钢规格: {dimension}")
        return 0.0418, 0.0248

    rx_cm = row.iloc[0]['rx']
    ry_cm = row.iloc[0]['ry']

    rx_m = rx_cm / 100
    ry_m = ry_cm / 100

    return rx_m, ry_m


def get_material_properties(grade):
    """获取材料属性"""
    properties = {
        "Q235B": 206e6,
        "Q355B": 206e6
    }
    return properties.get(grade, 206e6)


def phi_gb50017(lambda_val, section_class='b', fy=235, E=2.06e5):
    """计算轴心受压构件稳定系数"""
    if lambda_val <= 0:
        return 1.0

    lambda_bar = (lambda_val / math.pi) * math.sqrt(fy / E)

    alpha_dict = {'a': 0.21, 'b': 0.34, 'c': 0.49, 'd': 0.76}
    if section_class not in alpha_dict:
        raise ValueError("截面类别必须为 'a', 'b', 'c' 或 'd'")
    alpha = alpha_dict[section_class]

    if lambda_bar <= 0.215:
        return 1.0

    phi_prime = 0.5 * (1 + alpha * (lambda_bar - 0.215) + lambda_bar ** 2)

    discriminant = phi_prime ** 2 - lambda_bar ** 2
    if discriminant < 0:
        if discriminant > -1e-10:
            discriminant = 0
        else:
            raise ValueError(f"计算异常：判别式为负 ({discriminant})，检查输入参数")

    phi = 1.0 / (phi_prime + math.sqrt(discriminant))
    return min(phi, 1.0)


def calculate_column_stability_factor(lambda_x, lambda_y, fy=235):
    """计算柱稳定系数"""
    E = 2.06e5

    phi_in = phi_gb50017(lambda_x, section_class='b', fy=fy, E=E)
    phi_out = phi_gb50017(lambda_y, section_class='c', fy=fy, E=E)

    phi = min(phi_in, phi_out)

    return phi, phi_in, phi_out


def get_lambda_limit(fy, is_compression_member=True):
    """获取长细比限值"""
    lambda_limit = 150.0

    if fy > 235:
        lambda_limit = 150 * math.sqrt(235.0 / fy)

    return lambda_limit


def get_steel_yield_strength(grade):
    """获取钢材屈服强度"""
    strengths = {
        "Q235B": 235,
        "Q355B": 355
    }
    return strengths.get(grade, 235)


def calculate_beam_strength_check(axial_force_kN, moment_kN_m, shear_kN,
                                  A_net_mm2, Wx_net_mm3, Aw,
                                  f, fv, gamma_x=1.05):
    """梁强度验算"""
    N = axial_force_kN * 1000
    M = moment_kN_m * 1e6
    V = shear_kN * 1000

    strength_ratio = (N / A_net_mm2 + M / (gamma_x * Wx_net_mm3)) / f
    shear_ratio = V / (Aw * fv)

    return strength_ratio, shear_ratio


def calculate_column_stability_check(axial_force_kN, moment_kN_m,
                                     A_net_mm2, Wx_net_mm3,
                                     phi_x, phi_y, f,
                                     lambda_x, gamma_x=1.05,
                                     beta_mx=1.0, eta=0.0,
                                     beta_ty=1.0):
    """柱稳定验算"""
    N = axial_force_kN * 1000
    M = moment_kN_m * 1e6

    E = 2.06e5
    N_ex = (math.pi ** 2 * E * A_net_mm2) / (lambda_x ** 2)

    if N_ex <= N:
        ratio_in = float('inf')
    else:
        term1 = N / (phi_x * A_net_mm2 * f)
        term2 = (beta_mx * M) / (
                gamma_x * Wx_net_mm3 * f * (1 - 0.8 * N / N_ex)
        )
        ratio_in = term1 + term2

    phi_b = 1.0
    N_ey = (math.pi ** 2 * E * A_net_mm2) / (lambda_x ** 2)

    if N_ey <= N:
        ratio_out = float('inf')
    else:
        term1_out = N / (phi_y * A_net_mm2 * f)
        denominator = (eta + (1 - eta) * phi_b) * Wx_net_mm3 * f * (1 - N / N_ey)
        if denominator <= 0:
            ratio_out = float('inf')
        else:
            term2_out = (beta_ty * M) / denominator
            ratio_out = term1_out + term2_out

    return ratio_in, ratio_out


def analyze_frame_with_ops(span_list, height_list, steel_grade, default_load,
                           include_self_weight, element_steels, beam_loads,
                           node_loads, beam_point_loads):
    """使用OpenSees进行框架分析"""
    import openseespy.opensees as ops

    floors = len(height_list)
    E = get_material_properties(steel_grade)
    ops.wipe()
    ops.model('basic', '-ndm', 2, '-ndf', 3)

    node_id = 1
    total_bays = len(span_list)
    total_nodes_per_floor = total_bays + 1

    cum_heights = [0]
    for h in height_list:
        cum_heights.append(cum_heights[-1] + h)

    for floor in range(floors + 1):
        x_pos = 0
        for i in range(total_nodes_per_floor):
            ops.node(node_id, x_pos, cum_heights[floor])
            node_id += 1
            if i < total_bays:
                x_pos += span_list[i]

    for i in range(total_nodes_per_floor):
        ops.fix(i + 1, 1, 1, 1)

    ops.geomTransf('Linear', 1)

    ele_id = 1
    column_elements = []
    beam_elements = []

    # 创建柱子
    for floor in range(floors):
        for col_idx in range(total_nodes_per_floor):
            start_node = floor * total_nodes_per_floor + col_idx + 1
            end_node = (floor + 1) * total_nodes_per_floor + col_idx + 1
            col_dimension = element_steels.get(ele_id, "HW200×200×8×12")
            col_area, col_Ix, col_Iy, col_weight = get_steel_properties(col_dimension, load_h_steel_data())
            ops.element('elasticBeamColumn', ele_id, start_node, end_node,
                        col_area, E, col_Ix, 1)
            column_elements.append(ele_id)
            ele_id += 1

    # 创建梁
    for floor in range(1, floors + 1):
        base_node = floor * total_nodes_per_floor + 1
        for span_idx in range(total_bays):
            start_node = base_node + span_idx
            end_node = start_node + 1
            beam_dimension = element_steels.get(ele_id, "HW200×200×8×12")
            beam_area, beam_Ix, beam_Iy, beam_weight = get_steel_properties(beam_dimension, load_h_steel_data())
            ops.element('elasticBeamColumn', ele_id, start_node, end_node,
                        beam_area, E, beam_Ix, 1)
            beam_elements.append(ele_id)
            ele_id += 1

    ops.timeSeries('Constant', 1)
    ops.pattern('Plain', 1, 1)

    # 施加梁上荷载
    for i, beam_id in enumerate(beam_elements):
        load_value = beam_loads.get(beam_id, default_load)
        total_load = load_value
        if include_self_weight:
            beam_dimension = element_steels.get(beam_id, "HW200×200×8×12")
            _, _, _, beam_weight = get_steel_properties(beam_dimension, load_h_steel_data())
            beam_self_weight = beam_weight * 9.81 / 1000
            total_load += beam_self_weight
        ops.eleLoad('-ele', beam_id,
                    '-type', '-beamUniform', -total_load, 0.0)

    # 施加柱自重
    if include_self_weight:
        for col_id in column_elements:
            col_dimension = element_steels.get(col_id, "HW200×200×8×12")
            _, _, _, col_weight = get_steel_properties(col_dimension, load_h_steel_data())
            ele_nodes = ops.eleNodes(col_id)
            start_node = ele_nodes[0]
            end_node = ele_nodes[1]
            start_coord = ops.nodeCoord(start_node)
            end_coord = ops.nodeCoord(end_node)
            length = ((end_coord[0] - start_coord[0]) ** 2 + (end_coord[1] - start_coord[1]) ** 2) ** 0.5
            col_self_weight = col_weight * 9.81 / 1000
            total_column_load = col_self_weight * length
            ops.load(end_node, 0.0, -total_column_load, 0.0)

    # 施加节点荷载
    for node_id, (fx, fy, mz) in node_loads.items():
        ops.load(node_id, fx, fy, mz)

    # 施加梁集中荷载
    for ele_id, point_loads in beam_point_loads.items():
        for pos_ratio, fx, fy in point_loads:
            ops.eleLoad('-ele', ele_id, '-type', '-beamPoint', fy, pos_ratio, fx, pos_ratio)

    ops.constraints('Transformation')
    ops.numberer('RCM')
    ops.system('BandGeneral')
    ops.test('NormDispIncr', 1.0e-6, 6, 2)
    ops.algorithm('Linear')
    ops.integrator('LoadControl', 1)
    ops.analysis('Static')
    ops.analyze(1)

    analysis_data = {
        'spans': span_list,
        'heights': height_list,
        'floors': floors,
        'E': E,
        'steel_grade': steel_grade,
        'default_load': default_load,
        'include_self_weight': include_self_weight,
        'column_elements': column_elements,
        'beam_elements': beam_elements
    }

    return analysis_data


def get_element_forces(element_id):
    """获取单元内力"""
    import openseespy.opensees as ops
    try:
        forces = ops.eleResponse(element_id, 'force')
        return forces
    except:
        return None


def get_node_displacements(node_id):
    """获取节点位移"""
    import openseespy.opensees as ops
    try:
        disp = ops.nodeDisp(node_id)
        return disp
    except:
        return None


def get_node_coordinates(node_id):
    """获取节点坐标"""
    import openseespy.opensees as ops
    try:
        coord = ops.nodeCoord(node_id)
        return coord
    except:
        return None


def get_element_nodes(element_id):
    """获取单元节点"""
    import openseespy.opensees as ops
    try:
        nodes = ops.eleNodes(element_id)
        return nodes
    except:
        return None
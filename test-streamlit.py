import streamlit as st
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import plotly.graph_objects as go
import plotly.express as px
import io
import math
from model.structural_analysis import *
from streamlit.components.v1 import html
import json
# 设置中文字体
plt.rcParams['font.sans-serif'] = ['SimHei', 'DejaVu Sans', 'Arial Unicode MS', 'Microsoft YaHei']
plt.rcParams['axes.unicode_minus'] = False

# 全局状态初始化
if 'analyzer_state' not in st.session_state:
    st.session_state.analyzer_state = {
        'def_scale': 50.0,
        'axial_scale': 0.05,
        'shear_scale': 0.05,
        'moment_scale': 0.1,
        'h_steel_data': load_h_steel_data(),
        'column_elements': [],
        'beam_elements': [],
        'current_analysis_data': None,
        'beam_loads': {},
        'element_steels': {},
        'node_loads': {},
        'beam_point_loads': {},
        'selected_element': None,
        'selected_node': None,
        'diagram_var': "模型图"
    }

# 初始化可视化状态
if 'model_data' not in st.session_state:
    st.session_state.model_data = {
        'spans': [6.0, 9.0],
        'heights': [4.0, 3.0],
        'nodes': [],
        'elements': [],
        'supports': []
    }

st.set_page_config(layout="wide")
def generate_model_data(spans, heights):
    """生成框架节点和单元数据"""
    nodes = {}
    elements = []
    supports = []

    node_id = 1
    # 生成节点 - 按立面方向（Z轴为高度方向）
    for j, h in enumerate(heights):
        for i, s in enumerate([0] + spans):
            x = sum(spans[:i])
            y = 0  # 固定Y坐标为0
            z = sum(heights[:j])  # Z轴表示高度
            nodes[(i, j)] = (node_id, x, y, z)
            node_id += 1

    # 顶部节点
    for i, s in enumerate([0] + spans):
        x = sum(spans[:i])
        y = 0
        z = sum(heights)  # 最高层高度
        nodes[(i, len(heights))] = (node_id, x, y, z)
        node_id += 1

    # 生成柱单元 - 从下到上
    for j in range(len(heights)):
        for i in range(len(spans) + 1):
            start_node = nodes[(i, j)]
            end_node = nodes[(i, j + 1)]
            elements.append({
                'id': len(elements) + 1,
                'type': 'column',
                'start': start_node[0],
                'end': end_node[0],
                'start_coord': (start_node[1], start_node[2], start_node[3]),  # (x, y, z)
                'end_coord': (end_node[1], end_node[2], end_node[3])
            })

    # 生成梁单元 - 每层水平连接
    for j in range(1, len(heights) + 1):  # 从第1层开始（第0层是地面，不需要梁）
        for i in range(len(spans)):
            start_node = nodes[(i, j)]
            end_node = nodes[(i + 1, j)]
            elements.append({
                'id': len(elements) + 1,
                'type': 'beam',
                'start': start_node[0],
                'end': end_node[0],
                'start_coord': (start_node[1], start_node[2], start_node[3]),
                'end_coord': (end_node[1], end_node[2], end_node[3])
            })

    # 底部节点为固定支座（Z=0的节点）
    for i in range(len(spans) + 1):
        supports.append(nodes[(i, 0)][0])

    return {
        'nodes': nodes,
        'elements': elements,
        'supports': supports,
        'spans': spans,
        'heights': heights
    }


THREEJS_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <style>
        body { margin: 0; overflow: hidden; }
        #container { width: 100%; height: 100%; }
    </style>
</head>
<body>
    <div id="container"></div>
    <script src="https://cdn.jsdelivr.net/npm/three@0.132.2/build/three.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/three@0.132.2/examples/js/controls/OrbitControls.js"></script>
    <script>
        // 初始化场景
        const container = document.getElementById('container');
        const scene = new THREE.Scene();
        scene.background = new THREE.Color(0xf0f0f0);

        // 初始化相机
        const camera = new THREE.PerspectiveCamera(45, container.clientWidth / container.clientHeight, 0.1, 1000);
        camera.position.set(15, 10, 15);

        // 初始化渲染器
        const renderer = new THREE.WebGLRenderer({ antialias: true });
        renderer.setSize(container.clientWidth, container.clientHeight);
        renderer.shadowMap.enabled = true;
        container.appendChild(renderer.domElement);

        // 控制器
        const controls = new THREE.OrbitControls(camera, renderer.domElement);
        controls.enableDamping = true;

        // 灯光
        const ambientLight = new THREE.AmbientLight(0xffffff, 0.6);
        scene.add(ambientLight);

        const dirLight = new THREE.DirectionalLight(0xffffff, 1);
        dirLight.position.set(10, 20, 10);
        dirLight.castShadow = true;
        scene.add(dirLight);

        // 辅助对象
        const gridHelper = new THREE.GridHelper(50, 50);
        scene.add(gridHelper);

        const axesHelper = new THREE.AxesHelper(2);
        scene.add(axesHelper);

        // 钢结构材料
        const steelMaterial = new THREE.MeshStandardMaterial({
            color: 0x2c3e50,
            roughness: 0.4,
            metalness: 0.6
        });

        // 创建结构组
        const structureGroup = new THREE.Group();
        scene.add(structureGroup);

        // 从Streamlit接收数据
        function updateModel(data) {
            // 清除旧模型
            while(structureGroup.children.length > 0) {
                structureGroup.remove(structureGroup.children[0]);
            }

            const modelData = JSON.parse(data);
            const sectionSize = 0.3;

            // 创建柱子
            for (const elem of modelData.elements) {
                if (elem.type === 'column') {
                    const start = elem.start_coord;
                    const end = elem.end_coord;
                    const length = Math.sqrt(
                        Math.pow(end[0]-start[0], 2) + 
                        Math.pow(end[1]-start[1], 2) + 
                        Math.pow(end[2]-start[2], 2)
                    );

                    const geometry = new THREE.BoxGeometry(sectionSize, length, sectionSize);
                    const column = new THREE.Mesh(geometry, steelMaterial.clone());

                    // 计算中心位置和旋转
                    column.position.set(
                        (start[0] + end[0]) / 2,
                        (start[1] + end[1]) / 2,
                        (start[2] + end[2]) / 2
                    );

                    // 计算旋转
                    const direction = new THREE.Vector3(
                        end[0] - start[0],
                        end[1] - start[1],
                        end[2] - start[2]
                    ).normalize();

                    const up = new THREE.Vector3(0, 1, 0);
                    const axis = new THREE.Vector3().crossVectors(up, direction).normalize();
                    const angle = Math.acos(up.dot(direction));

                    column.quaternion.setFromAxisAngle(axis, angle);
                    column.castShadow = true;
                    column.receiveShadow = true;

                    structureGroup.add(column);
                }
            }

            // 创建梁
            for (const elem of modelData.elements) {
                if (elem.type === 'beam') {
                    const start = elem.start_coord;
                    const end = elem.end_coord;
                    const length = Math.sqrt(
                        Math.pow(end[0]-start[0], 2) + 
                        Math.pow(end[1]-start[1], 2) + 
                        Math.pow(end[2]-start[2], 2)
                    );

                    const geometry = new THREE.BoxGeometry(length, sectionSize, sectionSize);
                    const beam = new THREE.Mesh(geometry, steelMaterial.clone());

                    // 计算中心位置和旋转
                    beam.position.set(
                        (start[0] + end[0]) / 2,
                        (start[1] + end[1]) / 2,
                        (start[2] + end[2]) / 2
                    );

                    // 计算旋转
                    const direction = new THREE.Vector3(
                        end[0] - start[0],
                        end[1] - start[1],
                        end[2] - start[2]
                    ).normalize();

                    const up = new THREE.Vector3(0, 1, 0);
                    const axis = new THREE.Vector3().crossVectors(up, direction).normalize();
                    const angle = Math.acos(up.dot(direction));

                    beam.quaternion.setFromAxisAngle(axis, angle);
                    beam.castShadow = true;
                    beam.receiveShadow = true;

                    structureGroup.add(beam);
                }
            }

            // 调整相机位置
            const allCoords = [];
            for (const elem of modelData.elements) {
                allCoords.push(elem.start_coord);
                allCoords.push(elem.end_coord);
            }

            const xCoords = allCoords.map(c => c[0]);
            const yCoords = allCoords.map(c => c[1]);
            const zCoords = allCoords.map(c => c[2]);

            const centerX = (Math.min(...xCoords) + Math.max(...xCoords)) / 2;
            const centerY = (Math.min(...yCoords) + Math.max(...yCoords)) / 2;
            const centerZ = (Math.min(...zCoords) + Math.max(...zCoords)) / 2;

            controls.target.set(centerX, centerY, centerZ);
            camera.position.set(centerX, centerY, centerZ + 15);
            controls.update();
        }

        // 动画循环
        function animate() {
            requestAnimationFrame(animate);
            controls.update();
            renderer.render(scene, camera);
        }

        animate();

        // 监听窗口大小变化
        window.addEventListener('resize', () => {
            camera.aspect = container.clientWidth / container.clientHeight;
            camera.updateProjectionMatrix();
            renderer.setSize(container.clientWidth, container.clientHeight);
        });

        // 暴露更新函数给父窗口
        window.updateThreeJSModel = updateModel;
    </script>
</body>
</html>
"""


def plot_model_diagram():
    import openseespy.opensees as ops
    import opsvis as opsv

    fig, ax = plt.subplots(figsize=(12, 8))

    try:
        opsv.plot_model(ax=ax)

        for beam_id in st.session_state.analyzer_state['beam_elements']:
            try:
                ele_nodes = ops.eleNodes(beam_id)
                start_node = ele_nodes[0]
                end_node = ele_nodes[1]

                start_x, start_y = ops.nodeCoord(start_node)
                end_x, end_y = ops.nodeCoord(end_node)

                mid_x = (start_x + end_x) / 2
                mid_y = (start_y + end_y) / 2

                load_value = st.session_state.analyzer_state['beam_loads'].get(beam_id, 5.0)
                total_load = load_value
                if st.session_state.analyzer_state['current_analysis_data'] and st.session_state.analyzer_state[
                    'current_analysis_data'].get(
                    'include_self_weight', False):
                    beam_dimension = st.session_state.analyzer_state['element_steels'].get(beam_id, "HW200×200×8×12")
                    _, _, _, beam_weight = get_steel_properties(beam_dimension,
                                                                st.session_state.analyzer_state['h_steel_data'])
                    beam_self_weight = beam_weight * 9.81 / 1000
                    total_load += beam_self_weight

                beam_dimension = st.session_state.analyzer_state['element_steels'].get(beam_id, "HW200×200×8×12")

                load_label = f'{total_load:.2f}kN/m'
                if st.session_state.analyzer_state['current_analysis_data'] and st.session_state.analyzer_state[
                    'current_analysis_data'].get(
                    'include_self_weight', False):
                    load_label += f'\n(含{beam_self_weight:.2f}kN/m自重)'

                ax.text(
                    mid_x, mid_y - 0.2,
                    f'{load_label}\n{beam_dimension}',
                    ha='center',
                    va='top',
                    fontsize=8,
                    bbox=dict(boxstyle="round,pad=0.2", facecolor='yellow', alpha=0.7)
                )

                if beam_id in st.session_state.analyzer_state['beam_point_loads']:
                    for pos_ratio, fx, fy in st.session_state.analyzer_state['beam_point_loads'][beam_id]:
                        point_x = start_x + (end_x - start_x) * pos_ratio
                        point_y = start_y + (end_y - start_y) * pos_ratio

                        ax.arrow(point_x, point_y + 0.3, -fx * 0.01, -fy * 0.01,
                                 head_width=0.05, head_length=0.05, fc='red', ec='red')

                        ax.text(point_x, point_y + 0.5, f'F({fx:.1f}, {fy:.1f})',
                                ha='center', va='bottom', fontsize=7,
                                bbox=dict(boxstyle="round,pad=0.1", facecolor='orange', alpha=0.7))
            except:
                continue

        for col_id in st.session_state.analyzer_state['column_elements']:
            try:
                ele_nodes = ops.eleNodes(col_id)
                start_node = ele_nodes[0]
                end_node = ele_nodes[1]

                start_x, start_y = ops.nodeCoord(start_node)
                end_x, end_y = ops.nodeCoord(end_node)

                mid_x = (start_x + end_x) / 2
                mid_y = (start_y + end_y) / 2

                col_dimension = st.session_state.analyzer_state['element_steels'].get(col_id, "HW200×200×8×12")

                ax.text(mid_x + 0.3, mid_y, f'{col_dimension}',
                        ha='left', va='center', fontsize=8,
                        bbox=dict(boxstyle="round,pad=0.2", facecolor='lightgreen', alpha=0.7))
            except:
                continue

        for node_id, (fx, fy, mz) in st.session_state.analyzer_state['node_loads'].items():
            try:
                node_x, node_y = ops.nodeCoord(node_id)

                if fx != 0 or fy != 0:
                    ax.arrow(node_x, node_y, -fx * 0.01, -fy * 0.01,
                             head_width=0.05, head_length=0.05, fc='red', ec='red')

                load_text = f'F({fx:.1f}, {fy:.1f})'
                if mz != 0:
                    load_text += f'\nMz:{mz:.1f}'

                ax.text(node_x, node_y + 0.3, load_text,
                        ha='center', va='bottom', fontsize=7,
                        bbox=dict(boxstyle="round,pad=0.1", facecolor='cyan', alpha=0.7))
            except:
                continue

        if st.session_state.analyzer_state['current_analysis_data'] and st.session_state.analyzer_state[
            'current_analysis_data'].get('include_self_weight',
                                         False):
            ax.text(0.02, 0.98, "考虑梁柱自重",
                    transform=ax.transAxes,
                    fontsize=10,
                    verticalalignment='top',
                    bbox=dict(boxstyle="round,pad=0.3", facecolor='lightcoral', alpha=0.7))

        ax.set_title("钢框架结构模型图")
        ax.axis('equal')
        ax.grid(True)
    except Exception as e:
        ax.text(0.5, 0.5, f"模型图绘制失败: {str(e)}",
                horizontalalignment='center', verticalalignment='center',
                transform=ax.transAxes, fontsize=12)

    return fig


def plot_load_diagram():
    import openseespy.opensees as ops
    import opsvis as opsv

    fig, ax = plt.subplots(figsize=(12, 8))

    try:
        opsv.plot_load(ax=ax, nep=11, node_supports=True)

        for beam_id in st.session_state.analyzer_state['beam_elements']:
            try:
                ele_nodes = ops.eleNodes(beam_id)
                start_node = ele_nodes[0]
                end_node = ele_nodes[1]

                start_x, start_y = ops.nodeCoord(start_node)
                end_x, end_y = ops.nodeCoord(end_node)

                mid_x = (start_x + end_x) / 2
                mid_y = (start_y + end_y) / 2

                load_value = st.session_state.analyzer_state['beam_loads'].get(beam_id, 5.0)

                total_load = load_value
                if st.session_state.analyzer_state['current_analysis_data'] and st.session_state.analyzer_state[
                    'current_analysis_data'].get(
                    'include_self_weight', False):
                    beam_dimension = st.session_state.analyzer_state['element_steels'].get(beam_id, "HW200×200×8×12")
                    _, _, _, beam_weight = get_steel_properties(beam_dimension,
                                                                st.session_state.analyzer_state['h_steel_data'])
                    beam_self_weight = beam_weight * 9.81 / 1000
                    total_load += beam_self_weight

                beam_dimension = st.session_state.analyzer_state['element_steels'].get(beam_id, "HW200×200×8×12")

                load_label = f'{total_load:.2f}kN/m'
                if st.session_state.analyzer_state['current_analysis_data'] and st.session_state.analyzer_state[
                    'current_analysis_data'].get(
                    'include_self_weight', False):
                    load_label += f'\n(含{beam_self_weight:.2f}kN/m自重)'

                ax.text(mid_x, mid_y + 0.2, f'{load_label}\n{beam_dimension}',
                        ha='center', va='bottom', fontsize=8,
                        bbox=dict(boxstyle="round,pad=0.2", facecolor='yellow', alpha=0.7))
            except:
                continue

        for col_id in st.session_state.analyzer_state['column_elements']:
            try:
                ele_nodes = ops.eleNodes(col_id)
                start_node = ele_nodes[0]
                end_node = ele_nodes[1]

                start_x, start_y = ops.nodeCoord(start_node)
                end_x, end_y = ops.nodeCoord(end_node)

                mid_x = (start_x + end_x) / 2
                mid_y = (start_y + end_y) / 2

                col_dimension = st.session_state.analyzer_state['element_steels'].get(col_id, "HW200×200×8×12")

                ax.text(mid_x + 0.3, mid_y, f'{col_dimension}',
                        ha='left', va='center', fontsize=8,
                        bbox=dict(boxstyle="round,pad=0.2", facecolor='lightgreen', alpha=0.7))
            except:
                continue

        if st.session_state.analyzer_state['current_analysis_data'] and st.session_state.analyzer_state[
            'current_analysis_data'].get(
            'include_self_weight', False):
            ax.text(0.02, 0.98, "考虑梁柱自重",
                    transform=ax.transAxes,
                    fontsize=10,
                    verticalalignment='top',
                    bbox=dict(boxstyle="round,pad=0.3", facecolor='lightcoral', alpha=0.7))

        ax.set_title("荷载分布图 (kN/m)")
        ax.axis('equal')
        ax.grid(True)
    except Exception as e:
        ax.text(0.5, 0.5, f"荷载图绘制失败: {str(e)}",
                horizontalalignment='center', verticalalignment='center',
                transform=ax.transAxes, fontsize=12)

    return fig


def plot_reaction_diagram():
    import openseespy.opensees as ops
    import opsvis as opsv

    fig, ax = plt.subplots(figsize=(12, 8))

    try:
        opsv.plot_reactions(ax=ax)
        if st.session_state.analyzer_state['current_analysis_data'] and st.session_state.analyzer_state[
            'current_analysis_data'].get(
            'include_self_weight', False):
            ax.text(0.02, 0.98, "考虑梁柱自重",
                    transform=ax.transAxes,
                    fontsize=10,
                    verticalalignment='top',
                    bbox=dict(boxstyle="round,pad=0.3", facecolor='lightcoral', alpha=0.7))
        ax.set_title("支座反力图 (kN, kN·m)")
        ax.axis('equal')
        ax.grid(True)
    except Exception as e:
        ax.text(0.5, 0.5, f"反力图绘制失败: {str(e)}",
                horizontalalignment='center', verticalalignment='center',
                transform=ax.transAxes, fontsize=12)

    return fig


def plot_deformation_diagram():
    import openseespy.opensees as ops
    import opsvis as opsv

    fig, ax = plt.subplots(figsize=(12, 8))

    try:
        opsv.plot_defo(ax=ax, sfac=st.session_state.analyzer_state['def_scale'], unDefoFlag=1,
                       fmt_undefo={'color': 'gray', 'linestyle': '--'})
        if st.session_state.analyzer_state['current_analysis_data'] and st.session_state.analyzer_state[
            'current_analysis_data'].get('include_self_weight',
                                         False):
            ax.text(0.02, 0.98, "考虑梁柱自重",
                    transform=ax.transAxes,
                    fontsize=10,
                    verticalalignment='top',
                    bbox=dict(boxstyle="round,pad=0.3", facecolor='lightcoral', alpha=0.7))
        ax.set_title(f"结构变形图 (放大{st.session_state.analyzer_state['def_scale']:.1f}倍)")
        ax.axis('equal')
        ax.grid(True)

        for node_tag in ops.getNodeTags():
            try:
                disp = ops.nodeDisp(node_tag)
                ux = disp[0] * 1000
                uy = disp[1] * 1000
                x, y = ops.nodeCoord(node_tag)
                ax.annotate(f'U({ux:.2f}, {uy:.2f})mm', (x, y),
                            xytext=(5, 5), textcoords='offset points',
                            fontsize=8, color='red', weight='bold',
                            bbox=dict(boxstyle="round,pad=0.2", fc="yellow", alpha=0.7))
            except:
                continue

        for ele_id in st.session_state.analyzer_state['beam_elements']:
            try:
                ele_nodes = ops.eleNodes(ele_id)
                start_node = ele_nodes[0]
                end_node = ele_nodes[1]

                start_coord = np.array(ops.nodeCoord(start_node))
                end_coord = np.array(ops.nodeCoord(end_node))

                mid_coord = (start_coord + end_coord) / 2

                start_disp = np.array(ops.nodeDisp(start_node))
                end_disp = np.array(ops.nodeCoord(end_node))

                mid_disp = (start_disp + end_disp) / 2
                mid_uy = mid_disp[1] * 1000

                ax.annotate(f'δ_mid={mid_uy:.2f}mm', (mid_coord[0], mid_coord[1]),
                            xytext=(0, 10), textcoords='offset points',
                            fontsize=8, color='blue', weight='bold',
                            bbox=dict(boxstyle="round,pad=0.2", fc="lightblue", alpha=0.7))
            except:
                continue
    except Exception as e:
        ax.text(0.5, 0.5, f"变形图绘制失败: {str(e)}",
                horizontalalignment='center', verticalalignment='center',
                transform=ax.transAxes, fontsize=12)

    return fig


def plot_axial_force_diagram():
    import openseespy.opensees as ops
    import opsvis as opsv

    fig, ax = plt.subplots(figsize=(12, 8))

    try:
        opsv.section_force_diagram_2d('N', st.session_state.analyzer_state['axial_scale'], ax=ax, number_format='.1f')
        if st.session_state.analyzer_state['current_analysis_data'] and st.session_state.analyzer_state[
            'current_analysis_data'].get(
            'include_self_weight', False):
            ax.text(0.02, 0.98, "考虑梁柱自重",
                    transform=ax.transAxes,
                    fontsize=10,
                    verticalalignment='top',
                    bbox=dict(boxstyle="round,pad=0.3", facecolor='lightcoral', alpha=0.7))
        ax.set_title(f"轴力图 (单位: kN, 比例: {st.session_state.analyzer_state['axial_scale']:.3f})")
        ax.axis('equal')
        ax.grid(True)
    except Exception as e:
        ax.text(0.5, 0.5, f"轴力图绘制失败: {str(e)}",
                horizontalalignment='center', verticalalignment='center',
                transform=ax.transAxes, fontsize=12)

    return fig


def plot_shear_force_diagram():
    import openseespy.opensees as ops
    import opsvis as opsv

    fig, ax = plt.subplots(figsize=(12, 8))

    try:
        opsv.section_force_diagram_2d('V', st.session_state.analyzer_state['shear_scale'], ax=ax, number_format='.1f')
        if st.session_state.analyzer_state['current_analysis_data'] and st.session_state.analyzer_state[
            'current_analysis_data'].get(
            'include_self_weight', False):
            ax.text(0.02, 0.98, "考虑梁柱自重",
                    transform=ax.transAxes,
                    fontsize=10,
                    verticalalignment='top',
                    bbox=dict(boxstyle="round,pad=0.3", facecolor='lightcoral', alpha=0.7))
        ax.set_title(f"剪力图 (单位: kN, 比例: {st.session_state.analyzer_state['shear_scale']:.3f})")
        ax.axis('equal')
        ax.grid(True)
    except Exception as e:
        ax.text(0.5, 0.5, f"剪力图绘制失败: {str(e)}",
                horizontalalignment='center', verticalalignment='center',
                transform=ax.transAxes, fontsize=12)

    return fig


def plot_moment_diagram():
    import openseespy.opensees as ops
    import opsvis as opsv

    fig, ax = plt.subplots(figsize=(12, 8))

    try:
        opsv.section_force_diagram_2d('M', st.session_state.analyzer_state['moment_scale'], ax=ax, number_format='.1f')
        if st.session_state.analyzer_state['current_analysis_data'] and st.session_state.analyzer_state[
            'current_analysis_data'].get(
            'include_self_weight', False):
            ax.text(0.02, 0.98, "考虑梁柱自重",
                    transform=ax.transAxes,
                    fontsize=10,
                    verticalalignment='top',
                    bbox=dict(boxstyle="round,pad=0.3", facecolor='lightcoral', alpha=0.7))
        ax.set_title(f"弯矩图 (单位: kN·m, 比例: {st.session_state.analyzer_state['moment_scale']:.3f})")
        ax.axis('equal')
        ax.grid(True)
    except Exception as e:
        ax.text(0.5, 0.5, f"弯矩图绘制失败: {str(e)}",
                horizontalalignment='center', verticalalignment='center',
                transform=ax.transAxes, fontsize=12)

    return fig


def display_results():
    import openseespy.opensees as ops

    if not st.session_state.analyzer_state['current_analysis_data']:
        st.warning("请先进行分析")
        return

    analysis_data = st.session_state.analyzer_state['current_analysis_data']

    st.subheader("钢框架分析结果")
    st.write("=" * 50)

    st.write(f"**钢材强度等级:** {analysis_data['steel_grade']}")
    st.write(f"**钢材弹性模量:** {analysis_data['E'] / 1e6:.0f} GPa")

    if analysis_data.get('include_self_weight', False):
        st.write("**自重信息:**")
        st.write("- 梁柱自重已计入分析")
        st.write("- 钢材容重: 78.5 kN/m³ (7850 kg/m³ × 9.81 m/s²)")

    if st.session_state.analyzer_state['node_loads']:
        st.write("**节点荷载:**")
        for node_id, (fx, fy, mz) in st.session_state.analyzer_state['node_loads'].items():
            st.write(f"- 节点 {node_id}: FX={fx}kN, FY={fy}kN, MZ={mz}kN·m")

    if st.session_state.analyzer_state['beam_point_loads']:
        st.write("**梁集中荷载:**")
        for ele_id, point_loads in st.session_state.analyzer_state['beam_point_loads'].items():
            for pos_ratio, fx, fy in point_loads:
                st.write(f"- 梁 {ele_id}: 位置={pos_ratio:.2f}, FX={fx}kN, FY={fy}kN")

    st.write("**柱内力:**")
    for i, ele_id in enumerate(st.session_state.analyzer_state['column_elements']):
        try:
            forces = get_element_forces(ele_id)
            axial_force = forces[1]
            shear_force = forces[0]
            moment_i = forces[2]
            moment_j = forces[5]

            col_dimension = st.session_state.analyzer_state['element_steels'].get(ele_id, "HW200×200×8×12")
            _, _, _, col_weight = get_steel_properties(col_dimension, st.session_state.analyzer_state['h_steel_data'])
            col_self_weight = col_weight * 9.81 / 1000

            with st.expander(f"柱 {i + 1} (单元 {ele_id}, 规格: {col_dimension})"):
                st.write(f"  - 每米重量: {col_weight:.1f} kg/m")
                st.write(f"  - 每米自重: {col_self_weight:.3f} kN/m")
                st.write(f"  - 轴力: {axial_force:.2f} kN")
                st.write(f"  - 剪力: {shear_force:.2f} kN")
                st.write(f"  - I端弯矩: {moment_i:.2f} kN·m")
                st.write(f"  - J端弯矩: {moment_j:.2f} kN·m")
        except:
            st.write(f"柱 {i + 1} (单元 {ele_id}): 无法获取内力")

    st.write("**梁内力:**")
    for i, ele_id in enumerate(st.session_state.analyzer_state['beam_elements']):
        try:
            forces = get_element_forces(ele_id)
            axial_force = forces[0]
            shear_force_i = forces[1]
            moment_i = forces[2]
            shear_force_j = forces[4]
            moment_j = forces[5]

            load_value = st.session_state.analyzer_state['beam_loads'].get(ele_id,
                                                                           analysis_data['default_load'])

            total_load = load_value
            if analysis_data.get('include_self_weight', False):
                beam_dimension = st.session_state.analyzer_state['element_steels'].get(ele_id, "HW200×200×8×12")
                _, _, _, beam_weight = get_steel_properties(beam_dimension,
                                                            st.session_state.analyzer_state['h_steel_data'])
                beam_self_weight = beam_weight * 9.81 / 1000
                total_load += beam_self_weight

            beam_dimension = st.session_state.analyzer_state['element_steels'].get(ele_id, "HW200×200×8×12")
            _, _, _, beam_weight = get_steel_properties(beam_dimension, st.session_state.analyzer_state['h_steel_data'])

            with st.expander(f"梁 {i + 1} (单元 {ele_id}, 荷载: {total_load} kN/m, 规格: {beam_dimension})"):
                if analysis_data.get('include_self_weight', False):
                    st.write(f"  - (其中自重: {beam_self_weight:.3f} kN/m, 每米重量: {beam_weight:.1f} kg/m)")
                st.write(f"  - 轴力: {axial_force:.2f} kN")
                st.write(f"  - I端剪力: {shear_force_i:.2f} kN")
                st.write(f"  - J端剪力: {shear_force_j:.2f} kN")
                st.write(f"  - I端弯矩: {moment_i:.2f} kN·m")
                st.write(f"  - J端弯矩: {moment_j:.2f} kN·m")
        except Exception as e:
            st.write(f"梁 {i + 1} (单元 {ele_id}): 无法获取内力 - {str(e)}")

    st.write("**节点位移:**")
    for node_tag in ops.getNodeTags():
        try:
            disp = get_node_displacements(node_tag)
            st.write(f"- 节点 {node_tag}: UX={disp[0]:.6f}m, UY={disp[1]:.6f}m, RZ={disp[2]:.6f}rad")
        except:
            st.write(f"节点 {node_tag}: 无法获取位移")


def perform_verification():
    if not st.session_state.analyzer_state['current_analysis_data']:
        st.warning("请先进行分析")
        return

    try:
        fy = get_steel_yield_strength(st.session_state.analyzer_state['current_analysis_data']['steel_grade'])
        f = round(fy / 1.1 / 5) * 5
        fv = round(0.58 * f / 5) * 5

        net_to_gross_ratio = st.session_state.net_to_gross_ratio

        column_in_plane_k = st.session_state.column_in_plane_k
        column_out_plane_k = st.session_state.column_out_plane_k

        st.subheader("钢结构规范验算结果 (GB 50017-2017)")
        st.write("=" * 50)

        st.write(f"**钢材强度等级:** {st.session_state.analyzer_state['current_analysis_data']['steel_grade']}")
        st.write(f"**钢材屈服强度:** {fy} MPa")
        st.write(f"**钢材抗弯设计值:** {f:.1f} MPa")
        st.write(f"**钢材抗剪设计值:** {fv:.1f} MPa")
        st.write(f"**净截面/毛截面比值:** {net_to_gross_ratio}")

        st.write("**梁验算（强度）:**")

        for i, ele_id in enumerate(st.session_state.analyzer_state['beam_elements']):
            try:
                forces = get_element_forces(ele_id)
                axial_force_kN = abs(forces[0])
                shear_i_kN = abs(forces[1])
                moment_i_kN_m = abs(forces[2])
                shear_j_kN = abs(forces[4])
                moment_j_kN_m = abs(forces[5])

                max_moment_kN_m = max(moment_i_kN_m, moment_j_kN_m)
                max_shear_kN = max(shear_i_kN, shear_j_kN)

                beam_spec = st.session_state.analyzer_state['element_steels'].get(ele_id, "HW200×200×8×12")
                A_m2, Ix_m4, Iy_m4, weight = get_steel_properties(beam_spec,
                                                                  st.session_state.analyzer_state['h_steel_data'])
                h_m, b_m, tw_m, tf_m = get_steel_geometry(beam_spec, st.session_state.analyzer_state['h_steel_data'])
                Wx_m3, Wy_m3 = get_steel_section_modulus(beam_spec, st.session_state.analyzer_state['h_steel_data'])
                rx_m, ry_m = get_steel_radii_of_gyration(beam_spec, st.session_state.analyzer_state['h_steel_data'])

                A_mm2 = A_m2 * 1e6
                Wx_mm3 = Wx_m3 * 1e9
                h_mm = h_m * 1000
                b_mm = b_m * 1000
                tw_mm = tw_m * 1000
                tf_mm = tf_m * 1000

                A_net_mm2 = A_mm2 * net_to_gross_ratio
                Wx_net_mm3 = Wx_mm3 * net_to_gross_ratio

                gamma_x = 1.05
                N = axial_force_kN * 1000
                M = max_moment_kN_m * 1e6
                V = max_shear_kN * 1000

                Aw = h_mm * tw_mm

                strength_ratio, shear_ratio = calculate_beam_strength_check(
                    axial_force_kN, max_moment_kN_m, max_shear_kN,
                    A_net_mm2, Wx_net_mm3, Aw, f, fv, gamma_x
                )

                with st.expander(f"梁 {i + 1} (单元 {ele_id}, {beam_spec})"):
                    st.write(f"  - 最大弯矩: {max_moment_kN_m:.2f} kN·m")
                    st.write(f"  - 最大剪力: {max_shear_kN:.2f} kN")
                    st.write(f"  - 强度比: {strength_ratio:.3f}")
                    st.write(f"  - 剪切比: {shear_ratio:.3f}")

                    if strength_ratio <= 1.0 and shear_ratio <= 1.0:
                        st.success("  - 验算结果: 通过 ✓")
                    else:
                        st.error("  - 验算结果: 不通过！✗")

            except Exception as e:
                st.write(f"梁 {i + 1} (单元 {ele_id}): 验算失败 - {str(e)}")

        st.write("**柱验算（平面内 + 平面外稳定）:**")

        height_list = st.session_state.analyzer_state['current_analysis_data']['heights']

        for i, ele_id in enumerate(st.session_state.analyzer_state['column_elements']):
            try:
                forces = get_element_forces(ele_id)
                axial_force_kN = abs(forces[1])
                moment_i_kN_m = abs(forces[2])
                moment_j_kN_m = abs(forces[5])
                max_moment_kN_m = max(moment_i_kN_m, moment_j_kN_m)

                col_spec = st.session_state.analyzer_state['element_steels'].get(ele_id, "HW200×200×8×12")
                A_m2, Ix_m4, Iy_m4, weight = get_steel_properties(col_spec,
                                                                  st.session_state.analyzer_state['h_steel_data'])
                h_m, b_m, tw_m, tf_m = get_steel_geometry(col_spec, st.session_state.analyzer_state['h_steel_data'])
                Wx_m3, Wy_m3 = get_steel_section_modulus(col_spec, st.session_state.analyzer_state['h_steel_data'])
                rx_m, ry_m = get_steel_radii_of_gyration(col_spec, st.session_state.analyzer_state['h_steel_data'])

                A_mm2 = A_m2 * 1e6
                Wx_mm3 = Wx_m3 * 1e9
                rx_mm = rx_m * 1000
                ry_mm = ry_m * 1000

                A_net_mm2 = A_mm2 * net_to_gross_ratio
                Wx_net_mm3 = Wx_mm3 * net_to_gross_ratio

                floor_index = i // (len(height_list) + 1)
                if floor_index >= len(height_list):
                    floor_index = len(height_list) - 1
                L_col_m = height_list[floor_index]

                lambda_x = (L_col_m * column_in_plane_k) / rx_m
                lambda_y = (L_col_m * column_out_plane_k) / ry_m

                phi_x = phi_gb50017(lambda_x, section_class='b', fy=fy, E=2.06e5)
                phi_y = phi_gb50017(lambda_y, section_class='c', fy=fy, E=2.06e5)

                N = axial_force_kN * 1000
                M = max_moment_kN_m * 1e6
                beta_mx = 1.0
                gamma_x = 1.05

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
                eta = 0.0
                beta_ty = 1.0

                N_ey = (math.pi ** 2 * E * A_net_mm2) / (lambda_y ** 2)

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

                with st.expander(f"柱 {i + 1} (单元 {ele_id}, {col_spec})"):
                    st.write(f"  - 柱高: {L_col_m:.2f} m")
                    st.write(f"  - λx = {lambda_x:.1f} (φx={phi_x:.3f}, b类)")
                    st.write(f"  - λy = {lambda_y:.1f} (φy={phi_y:.3f}, c类)")
                    st.write(f"  - 平面内稳定比: {ratio_in:.3f}")
                    st.write(f"  - 平面外稳定比: {ratio_out:.3f}")

                    if ratio_in <= 1.0 and ratio_out <= 1.0:
                        st.success("  - 验算结果: 通过 ✓")
                    else:
                        st.error("  - 验算结果: 不通过！✗")

            except Exception as e:
                st.write(f"柱 {i + 1} (单元 {ele_id}): 验算失败 - {str(e)}")

    except Exception as e:
        st.error(f"验算过程中出现错误: {str(e)}")
def show_model_preview(model_data):
    """显示模型预览"""
    st.subheader("框架结构3D模型")

    # 准备模型数据
    model_data_for_json = {
        'elements': model_data['elements'],
        'spans': model_data['spans'],
        'heights': model_data['heights'],
        'supports': model_data['supports']
    }

    # 添加节点数据（简化格式）
    nodes_list = []
    for key, node_info in model_data['nodes'].items():
        nodes_list.append({
            'id': node_info[0],
            'x': node_info[1],
            'y': node_info[2],
            'z': node_info[3]
        })
    model_data_for_json['nodes'] = nodes_list

    model_json = json.dumps(model_data_for_json)

    # 创建完整的HTML内容
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <style>
            body {{ margin: 0; overflow: hidden; }}
            #container {{ width: 100%; height: 600px; }}
        </style>
    </head>
    <body>
        <div id="container"></div>
        <script src="https://cdn.jsdelivr.net/npm/three@0.132.2/build/three.min.js"></script>
        <script src="https://cdn.jsdelivr.net/npm/three@0.132.2/examples/js/controls/OrbitControls.js"></script>
        <script>
            // 初始化场景
            const container = document.getElementById('container');
            const scene = new THREE.Scene();
            scene.background = new THREE.Color(0xf0f0f0);

            // 初始化相机
            const camera = new THREE.PerspectiveCamera(45, container.clientWidth / container.clientHeight, 0.1, 1000);
            camera.position.set(15, 10, 15);

            // 初始化渲染器
            const renderer = new THREE.WebGLRenderer({{ antialias: true }});
            renderer.setSize(container.clientWidth, container.clientHeight);
            renderer.shadowMap.enabled = true;
            container.appendChild(renderer.domElement);

            // 控制器
            const controls = new THREE.OrbitControls(camera, renderer.domElement);
            controls.enableDamping = true;

            // 灯光
            const ambientLight = new THREE.AmbientLight(0xffffff, 0.6);
            scene.add(ambientLight);

            const dirLight = new THREE.DirectionalLight(0xffffff, 1);
            dirLight.position.set(10, 20, 10);
            dirLight.castShadow = true;
            scene.add(dirLight);

            // 辅助对象
            const gridHelper = new THREE.GridHelper(50, 50);
            scene.add(gridHelper);

            const axesHelper = new THREE.AxesHelper(2);
            scene.add(axesHelper);

            // 钢结构材料
            const steelMaterial = new THREE.MeshStandardMaterial({{
                color: 0x2c3e50,
                roughness: 0.4,
                metalness: 0.6
            }});

            // 创建结构组
            const structureGroup = new THREE.Group();
            scene.add(structureGroup);

            // 解析模型数据并创建模型
            const modelData = {model_json};

            function createModel() {{
                // 清除旧模型
                while(structureGroup.children.length > 0) {{
                    structureGroup.remove(structureGroup.children[0]);
                }}

                const sectionSize = 0.3;

                // 创建柱子和梁
                for (const elem of modelData.elements) {{
                    const startNode = modelData.nodes.find(n => n.id === elem.start);
                    const endNode = modelData.nodes.find(n => n.id === elem.end);

                    if (!startNode || !endNode) continue;

                    const start = [startNode.x, startNode.y, startNode.z];
                    const end = [endNode.x, endNode.y, endNode.z];

                    const length = Math.sqrt(
                        Math.pow(end[0]-start[0], 2) + 
                        Math.pow(end[1]-start[1], 2) + 
                        Math.pow(end[2]-start[2], 2)
                    );

                    let geometry;
                    if (elem.type === 'column') {{
                        geometry = new THREE.BoxGeometry(sectionSize, length, sectionSize);
                    }} else {{
                        geometry = new THREE.BoxGeometry(length, sectionSize, sectionSize);
                    }}

                    const mesh = new THREE.Mesh(geometry, steelMaterial.clone());

                    // 计算中心位置和旋转
                    mesh.position.set(
                        (start[0] + end[0]) / 2,
                        (start[1] + end[1]) / 2,
                        (start[2] + end[2]) / 2
                    );

                    // 计算旋转
                    const direction = new THREE.Vector3(
                        end[0] - start[0],
                        end[1] - start[1],
                        end[2] - start[2]
                    ).normalize();

                    const up = new THREE.Vector3(0, 1, 0);
                    const axis = new THREE.Vector3().crossVectors(up, direction).normalize();
                    const angle = Math.acos(up.dot(direction));

                    mesh.quaternion.setFromAxisAngle(axis, angle);
                    mesh.castShadow = true;
                    mesh.receiveShadow = true;

                    structureGroup.add(mesh);
                }}

                // 调整相机位置
                const allCoords = [];
                for (const node of modelData.nodes) {{
                    allCoords.push([node.x, node.y, node.z]);
                }}

                const xCoords = allCoords.map(c => c[0]);
                const yCoords = allCoords.map(c => c[1]);
                const zCoords = allCoords.map(c => c[2]);

                const centerX = (Math.min(...xCoords) + Math.max(...xCoords)) / 2;
                const centerY = (Math.min(...yCoords) + Math.max(...yCoords)) / 2;
                const centerZ = (Math.min(...zCoords) + Math.max(...zCoords)) / 2;

                controls.target.set(centerX, centerY, centerZ);
                camera.position.set(centerX + 10, centerY + 10, centerZ + 10);
                controls.update();
            }}

            // 初始创建模型
            createModel();

            // 动画循环
            function animate() {{
                requestAnimationFrame(animate);
                controls.update();
                renderer.render(scene, camera);
            }}

            animate();

            // 监听窗口大小变化
            window.addEventListener('resize', () => {{
                camera.aspect = container.clientWidth / container.clientHeight;
                camera.updateProjectionMatrix();
                renderer.setSize(container.clientWidth, container.clientHeight);
            }});
        </script>
    </body>
    </html>
    """

    # 注入HTML
    html(html_content, height=600)

def main():
    st.title("钢框架结构分析程序")

    # 侧边栏参数设置
    with st.sidebar:
        st.header("结构参数")
        spans_str = st.text_input("跨度 (mm, 逗号分隔)", "6000,9000")
        height_str = st.text_input("层高 (mm, 逗号分隔)", "4000,3000")

        steel_grade = st.selectbox("钢材强度等级", ["Q235B", "Q355B"], index=0)
        beam_spec = st.selectbox("钢梁规格", st.session_state.analyzer_state['h_steel_data']['Dimension'].tolist(),
                                 index=0)
        column_spec = st.selectbox("钢柱规格", st.session_state.analyzer_state['h_steel_data']['Dimension'].tolist(),
                                   index=0)

        net_to_gross_ratio = st.number_input("净截面/毛截面比值", value=0.85, min_value=0.1, max_value=1.0, step=0.01)
        st.session_state.net_to_gross_ratio = net_to_gross_ratio

        st.header("荷载参数")
        dead_load = st.number_input("恒荷载 (kN/m)", value=1.0, min_value=0.0, step=0.1)
        live_load = st.number_input("活荷载 (kN/m)", value=5.0, min_value=0.0, step=0.1)
        dead_load_factor = st.number_input("恒荷载组合系数", value=1.3, min_value=0.0, step=0.1)
        live_load_factor = st.number_input("活荷载组合系数", value=1.5, min_value=0.0, step=0.1)

        include_self_weight = st.checkbox("考虑梁柱自重", value=True)

        st.header("计算长度系数")
        column_in_plane_k = st.number_input("柱平面内计算长度系数", value=1.0, min_value=0.1, max_value=3.0, step=0.1)
        column_out_plane_k = st.number_input("柱平面外计算长度系数", value=1.0, min_value=0.1, max_value=3.0, step=0.1)
        st.session_state.column_in_plane_k = column_in_plane_k
        st.session_state.column_out_plane_k = column_out_plane_k

    # 主界面
    # 生成模型按钮
    if st.button("生成模型"):
        try:
            span_list = [float(x.strip()) / 1000 for x in spans_str.split(',')]
            height_list = [float(x.strip()) / 1000 for x in height_str.split(',')]

            model_data = generate_model_data(span_list, height_list)
            st.session_state.model_data = model_data

            # 初始化所有构件的默认截面
            for elem in model_data['elements']:
                if elem['type'] == 'beam':
                    st.session_state.analyzer_state['element_steels'][elem['id']] = beam_spec
                else:  # column
                    st.session_state.analyzer_state['element_steels'][elem['id']] = column_spec

            st.success(f"模型已生成！共{len(model_data['nodes'])}个节点，{len(model_data['elements'])}个单元")
            show_model_preview(model_data)
        except Exception as e:
            st.error(f"生成模型失败: {str(e)}")


    # 显示模型预览
    if 'model_data' in st.session_state and st.session_state.model_data['elements']:
        st.subheader("框架结构3D模型")

        # 创建Three.js可视化
        html(THREEJS_TEMPLATE, height=600)

        # 将模型数据传递给Three.js
        model_data_for_json = st.session_state.model_data.copy()
        if 'nodes' in model_data_for_json:
            # 将 (0, 1) 这样的元组键转换为字符串 "(0, 1)"
            model_data_for_json['nodes'] = {str(k): v for k, v in model_data_for_json['nodes'].items()}

        model_json = json.dumps(model_data_for_json)
        html(f"""
        {THREEJS_TEMPLATE}

        <script>
            const modelData = {model_json};
            if (window.updateThreeJSModel) {{
                window.updateThreeJSModel(JSON.stringify(modelData));
            }}
        </script>
        """, height=600)

        # 添加选择状态管理
        if 'selected_element_id' not in st.session_state:
            st.session_state.selected_element_id = None
        if 'selected_node_id' not in st.session_state:
            st.session_state.selected_node_id = None

        # 添加一个下拉菜单来选择要修改的单元（只显示梁）
        all_elements = [(elem['id'], elem['type']) for elem in st.session_state.model_data['elements'] if
                        elem['type'] == 'beam']
        element_options = [f"{elem_id} ({elem_type})" for elem_id, elem_type in all_elements]
        selected_element_option = st.selectbox("选择要修改的梁", [""] + element_options,
                                               on_change=lambda: st.session_state.update({'selected_element_id': int(
                                                   selected_element_option.split()[
                                                       0]) if selected_element_option else None}) if selected_element_option else st.session_state.update(
                                                   {'selected_element_id': None}))

        if selected_element_option:
            selected_element_id = int(selected_element_option.split()[0])
            st.session_state.selected_element_id = selected_element_id

            # 获取当前单元类型
            current_element = None
            for elem in st.session_state.model_data['elements']:
                if elem['id'] == selected_element_id:
                    current_element = elem
                    break

            if current_element:
                element_type = current_element['type']

                # 显示当前参数
                current_load = st.session_state.analyzer_state['beam_loads'].get(selected_element_id,
                                                                                 5.0) if element_type == 'beam' else 0
                current_section = st.session_state.analyzer_state['element_steels'].get(selected_element_id,
                                                                                        beam_spec if element_type == 'beam' else column_spec)

                col1, col2 = st.columns(2)

                with col1:
                    if element_type == 'beam':
                        new_load = st.number_input(f"修改梁荷载 (kN/m)", value=float(current_load), min_value=0.0,
                                                   step=0.1, key=f"load_{selected_element_id}")
                    else:
                        st.info(f"柱单元 {selected_element_id} 无需设置荷载")
                        new_load = 0

                with col2:
                    new_section = st.selectbox(f"修改截面",
                                               st.session_state.analyzer_state['h_steel_data']['Dimension'].tolist(),
                                               index=st.session_state.analyzer_state['h_steel_data'][
                                                   'Dimension'].tolist().index(current_section) if current_section in
                                                                                                   st.session_state.analyzer_state[
                                                                                                       'h_steel_data'][
                                                                                                       'Dimension'].tolist() else 0,
                                               key=f"section_{selected_element_id}")

                if st.button(f"更新单元 {selected_element_id} 参数", key=f"update_elem_{selected_element_id}"):
                    # 更新荷载
                    if element_type == 'beam':
                        st.session_state.analyzer_state['beam_loads'][selected_element_id] = new_load
                    # 更新截面
                    st.session_state.analyzer_state['element_steels'][selected_element_id] = new_section
                    st.success(f"单元 {selected_element_id} 参数已更新！")
        else:
            st.session_state.selected_element_id = None

        # 添加节点荷载修改功能（不显示底层节点）
        st.subheader("节点荷载修改")
        all_nodes = [val[0] for val in st.session_state.model_data['nodes'].values()]
        # 过滤掉底层节点（Z坐标为0的节点）
        non_ground_nodes = []
        for key, val in st.session_state.model_data['nodes'].items():
            node_id, x, y, z = val
            if z > 0:  # 只显示非地面节点
                non_ground_nodes.append(node_id)
        node_options = [str(node_id) for node_id in non_ground_nodes]
        selected_node_option = st.selectbox("选择要修改的节点", [""] + node_options,
                                            on_change=lambda: st.session_state.update({'selected_node_id': int(
                                                selected_node_option) if selected_node_option else None}) if selected_node_option else st.session_state.update(
                                                {'selected_node_id': None}))

        if selected_node_option:
            selected_node_id = int(selected_node_option)
            st.session_state.selected_node_id = selected_node_id

            # 获取当前节点荷载
            current_fx, current_fy, current_mz = st.session_state.analyzer_state['node_loads'].get(selected_node_id,
                                                                                                   (0, 0, 0))

            col1, col2, col3 = st.columns(3)

            with col1:
                new_fx = st.number_input(f"FX (kN)", value=float(current_fx), step=0.1, key=f"fx_{selected_node_id}")

            with col2:
                new_fy = st.number_input(f"FY (kN)", value=float(current_fy), step=0.1, key=f"fy_{selected_node_id}")

            with col3:
                new_mz = st.number_input(f"MZ (kN·m)", value=float(current_mz), step=0.1, key=f"mz_{selected_node_id}")

            if st.button(f"更新节点 {selected_node_id} 荷载", key=f"update_node_{selected_node_id}"):
                # 更新节点荷载
                st.session_state.analyzer_state['node_loads'][selected_node_id] = (new_fx, new_fy, new_mz)
                st.success(f"节点 {selected_node_id} 荷载已更新！")
        else:
            st.session_state.selected_node_id = None

    # 分析按钮 - 只有在模型生成后才显示
    if st.session_state.model_data['elements']:
        if st.button("开始分析", type="primary"):
            try:
                span_list = [float(x.strip()) / 1000 for x in spans_str.split(',')]
                height_list = [float(x.strip()) / 1000 for x in height_str.split(',')]

                floors = len(height_list)
                if floors == 0:
                    st.error("至少需要输入一个层高")
                    return

                combined_load = dead_load * dead_load_factor + live_load * live_load_factor

                # 使用全局状态中的element_steels和beam_loads
                element_steels = st.session_state.analyzer_state['element_steels'].copy()
                beam_loads = st.session_state.analyzer_state['beam_loads'].copy()
                node_loads = st.session_state.analyzer_state['node_loads'].copy()

                # 分析结构并获取梁柱单元列表
                analysis_data = analyze_frame_with_ops(
                    span_list, height_list, steel_grade, combined_load, include_self_weight,
                    element_steels,
                    beam_loads,
                    node_loads,
                    st.session_state.analyzer_state['beam_point_loads']
                )

                # 获取梁柱单元列表
                column_elements = analysis_data['column_elements']
                beam_elements = analysis_data['beam_elements']

                # 更新全局状态
                st.session_state.analyzer_state['column_elements'] = column_elements
                st.session_state.analyzer_state['beam_elements'] = beam_elements
                st.session_state.analyzer_state['current_analysis_data'] = analysis_data
                st.session_state.analyzer_state['element_steels'] = element_steels
                st.session_state.analyzer_state['beam_loads'] = beam_loads
                st.session_state.analyzer_state['node_loads'] = node_loads

                st.success("分析完成！")

                # 显示荷载信息
                st.write("**荷载信息:**")
                st.write(f"- 恒荷载: {dead_load} kN/m")
                st.write(f"- 活荷载: {live_load} kN/m")
                st.write(f"- 恒荷载组合系数: {dead_load_factor}")
                st.write(f"- 活荷载组合系数: {live_load_factor}")
                st.write(f"- 荷载组合值: {combined_load} kN/m")

                st.write("**结构信息:**")
                st.write(f"- 层数: {floors}")
                st.write(f"- 跨数: {len(span_list)}")

            except Exception as e:
                st.error(f"分析过程中出现错误: {str(e)}")

    # 显示分析结果
    if st.session_state.analyzer_state['current_analysis_data']:
        diagram_type = st.selectbox("选择图表类型",
                                    ["模型图", "荷载图", "反力图", "变形图", "轴力图", "剪力图", "弯矩图"],
                                    index=0)

        fig = None
        if diagram_type == "模型图":
            fig = plot_model_diagram()
        elif diagram_type == "荷载图":
            fig = plot_load_diagram()
        elif diagram_type == "反力图":
            fig = plot_reaction_diagram()
        elif diagram_type == "变形图":
            fig = plot_deformation_diagram()
        elif diagram_type == "轴力图":
            fig = plot_axial_force_diagram()
        elif diagram_type == "剪力图":
            fig = plot_shear_force_diagram()
        elif diagram_type == "弯矩图":
            fig = plot_moment_diagram()

        if fig:
            st.pyplot(fig)

        # 显示结果
        display_results()

        # 规范验算
        if st.button("规范验算"):
            perform_verification()
    else:
        st.info("请先生成模型并点击'开始分析'")


if __name__ == "__main__":
    main()




# VSTain - 视觉脚本工具

一个基于 PyQt5 和 qfluentwidgets 的现代化视觉脚本工具，旨在帮助用户通过图像识别和自动化技术创建强大的视觉脚本。持续开发中...

## 功能特性

- 🎨 现代化的 Fluent Design 界面 - 使用 qfluentwidgets 构建美观且易用的用户界面
- 🖼️ 图片查看和管理 - 支持多种格式的图片查看和基本管理功能
- 📸 屏幕截图功能 - 可捕获指定窗口或屏幕区域的截图用于分析
- 🧠 ONNX模型支持（DirectML后端） - 利用 ONNX Runtime DirectML 在 Windows 上实现高效的模型推理
- ⚙️ 灵活的配置选项 - 提供丰富的配置选项以满足不同用户需求
- 🔧 窗口句柄管理 - 能够获取和管理 Windows 系统中的窗口句柄信息
- 📐 图像标注工具 - 提供完善的图像标注功能，支持YOLO格式导入导出
- 🎯 通用图像查看器 - 支持缩放、平移、十字准星等高级功能
- 🤖 自动化脚本执行 - 支持创建和执行基于视觉识别的自动化脚本
- 🔀 可视化流程图编辑器 - 节点式编辑器，支持拖拽、连线、撤销重做、框选、复制粘贴
- 📊 流程图执行引擎 - 支持循环、条件判断、变量、子流程等控制流
- ⌨️ 按键捕获 - 键盘输入节点支持可视化按键录入
- 🗂️ 连接优先级 - 多输出连接支持执行顺序指定与可视化标记
- 🎛️ 主题化组件 - 可复用的 QSS 驱动主题组件（如 ThemedSplitter）

## 项目结构

```
VSTain/
├── src/                          # 源代码目录
│   └── vstain/                   # 主包
│       ├── __init__.py           # 包初始化
│       ├── app.py                # 应用入口点
│       ├── common/               # 公共模块
│       │   ├── config.py         # 全局配置
│       │   ├── cons.py           # 常量定义（按键映射等）
│       │   ├── settings.py       # 应用配置常量
│       │   └── style_sheet.py    # QSS 样式表管理
│       ├── components/           # 可复用组件
│       │   ├── __init__.py
│       │   ├── image_viewer.py   # 通用图像查看器
│       │   ├── flow_editor.py    # 流程图可视化编辑器
│       │   └── themed_splitter.py # 主题化分割条组件
│       ├── engine/               # 执行引擎
│       │   ├── __init__.py
│       │   └── flow_executor.py  # 流程图执行引擎
│       ├── models/               # 数据模型
│       │   ├── __init__.py
│       │   └── flow_model.py     # 流程图模型（节点/连接/流程图）
│       ├── utils/                # 工具函数
│       │   ├── __init__.py
│       │   ├── logger.py         # 日志工具
│       │   └── platform.py       # 平台相关工具
│       ├── widgets/              # UI 页面组件
│       │   ├── __init__.py
│       │   ├── home_widget.py             # 主页（配置/流程图运行）
│       │   ├── script_flow_widget.py      # 流程图编排页面
│       │   ├── annotation_widget.py       # 图像标注组件
│       │   ├── feature_capture_widget.py  # 特征捕获组件
│       │   ├── hwnd_list_widget.py        # 窗口列表组件
│       │   ├── image_card_widget.py       # 图片卡片组件
│       │   └── settings_widget.py         # 设置页面组件
│       └── windows/              # 窗口类
│           ├── __init__.py
│           └── main_window.py    # 主窗口
├── resource/                     # 资源文件
│   ├── qss/                      # QSS 主题样式
│   │   ├── dark/                 # 暗色主题
│   │   └── light/                # 亮色主题
│   ├── modules/                  # ONNX 模型文件
│   ├── scripts/                  # 录制的操作脚本
│   └── flows/                    # 流程图 JSON 文件
├── logs/                         # 日志文件
├── tests/                        # 测试文件
├── main.py                       # 入口点
├── pyproject.toml                # 项目配置
└── README.md
```

## 快速开始

### 系统要求

- Windows 10 或更高版本（推荐 Windows 11）
- Python 3.13+
- Visual C++ 2015-2022 Redistributable 14.0+

### 安装

推荐使用 uv 来管理依赖：

```bash
# 安装 uv（如果尚未安装）
pip install uv

# 安装项目依赖
uv sync
```

或者使用传统的 pip 方式：

```bash
pip install -e .
```

### 检查 VC++ 运行时

ONNX Runtime 1.23.2 需要 VC++ 2015-2022 Redistributable 14.0+版本：

```bash
# 检查系统 VC++ 运行时:
powershell "Get-ItemProperty HKLM:\SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64"

# 安装正确的 VC++ 运行时
winget install Microsoft.VCRedist.2015+.x64
```

### 运行

```bash
python main.py
```

或者使用 uv 运行：

```bash
uv run main.py
```

## 开发

### 技术栈

项目使用以下技术栈：

- Python 3.13+
- PyQt5 - GUI框架
- qfluentwidgets - 美观的UI组件库
- ONNX Runtime DirectML - 高性能机器学习推理引擎
- OpenCV - 计算机视觉库
- uv - 快速的Python包管理器和项目管理工具

### 项目架构

项目采用模块化设计，主要分为以下几个部分：

1. **app.py** - 应用程序入口点，负责初始化和启动应用
2. **widgets/** - 页面级 UI 组件，每个组件负责特定的功能模块
3. **components/** - 可复用的 UI 组件（流程图编辑器、图像查看器、主题化分割条等）
4. **engine/** - 执行引擎，负责流程图的解释执行
5. **models/** - 数据模型，定义节点、连接、流程图等数据结构
6. **windows/** - 窗口管理模块，包含主窗口和其他窗口类
7. **utils/** - 工具函数模块，提供日志、平台检测等通用功能
8. **common/** - 公共模块，包含配置、常量、按键映射和 QSS 样式表管理
9. **resource/** - 资源文件，存放 QSS 主题、模型、脚本、流程图等

### 开发环境设置

1. Fork 项目仓库
2. 克隆到本地
3. 安装依赖：`uv sync`
4. 进行修改和开发
5. 提交 Pull Request

## 使用指南

### 主要功能模块

1. **窗口句柄管理**：
   - 通过窗口标题和类名查找窗口句柄
   - 查看系统中所有可用窗口的信息

2. **图像捕获**：
   - 截取指定窗口的内容
   - 对截图进行查看和标注

3. **ONNX模型集成**：
   - 支持多种ONNX格式的模型
   - 可选择不同的执行提供者（CPU、CUDA、DirectML）

4. **图像标注工具**：
   - 支持手动绘制边界框进行标注
   - 支持自动检测模型辅助标注
   - 支持YOLO格式导入导出
   - 支持数据集组织和管理

5. **流程图编排**：
   - 可视化节点编辑器创建自动化流程
   - 支持 14 种节点类型覆盖常见自动化场景
   - 多输出连接指定执行顺序
   - 流程图保存/加载（JSON 格式）
   - 调试运行 + 实时变量监视面板

### 配置说明

应用的主要配置存储在配置文件中，用户可以通过设置界面或直接修改配置进行自定义。

### 开发规范

- 项目名称应体现个人标识 `tainanle`，增强唯一性
- 代码风格遵循PEP8规范
- 组件命名清晰，便于理解功能
- 主题色通过 QSS 文件管理，dark/light 各一套

## 许可证

MIT License

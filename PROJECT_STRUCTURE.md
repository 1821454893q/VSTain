# 项目结构说明

## 当前项目结构

```
VSTain/
├── src/                          # 源代码目录
│   └── vstain/                   # 主包
│       ├── __init__.py           # 包初始化
│       ├── app.py                # 应用入口点
│       ├── common/               # 公共模块
│       │   ├── config.py         # 全局配置
│       │   └── style_sheet.py    # 样式表
│       ├── config/               # 配置模块
│       │   ├── __init__.py
│       │   └── settings.py       # 应用配置常量
│       ├── utils/                # 工具函数模块
│       │   ├── __init__.py
│       │   ├── logger.py         # 日志工具
│       │   └── platform.py       # 平台相关工具
│       ├── widgets/              # UI 组件
│       │   ├── __init__.py
│       │   ├── home_widget.py           # 主页组件
│       │   ├── image_card_widget.py     # 图片卡片组件
│       │   ├── settings_widget.py       # 设置页面组件
│       │   ├── hwnd_list_widget.py      # 窗口列表组件
│       │   ├── annotation_widget.py     # 注释组件
│       │   └── feature_capture_widget.py # 特征捕获组件
│       └── windows/              # 窗口类
│           ├── __init__.py
│           └── main_window.py    # 主窗口
├── resource/                     # 资源文件目录
├── logs/                         # 日志文件目录
├── main.py                       # 应用入口点
├── pyproject.toml                # 项目配置
├── logging_config.json           # 日志配置
├── README.md                     # 项目说明
└── .gitignore                    # Git 忽略文件
```

## 模块详细说明

### `src/vstain/app.py`
应用主入口点，负责创建和配置QApplication实例，并启动主窗口。

### `src/vstain/common/`
存放项目通用的配置和样式：

- `config.py`: 全局配置参数
- `style_sheet.py`: 应用程序样式表

### `src/vstain/config/settings.py`
存放应用基础配置常量，如窗口大小、标题等基本设置。

### `src/vstain/utils/`
工具函数模块，提供各种辅助功能：

- `logger.py`: 日志记录工具，封装了日志的记录和管理功能
- `platform.py`: 平台相关工具函数，如系统版本检测

### `src/vstain/widgets/`
所有 UI 组件的集合：
- `home_widget.py`: 主页组件，应用程序的起始界面
- `image_card_widget.py`: 图片卡片组件，用于展示单个图片项
- `settings_widget.py`: 设置页面组件，提供应用设置功能
- `hwnd_list_widget.py`: 窗口列表组件，显示可用的应用窗口列表
- `annotation_widget.py`: 注释组件，用于在图片上添加注释
- `feature_capture_widget.py`: 特征捕获组件，提供窗口特征捕获功能

### `src/vstain/windows/main_window.py`
主窗口类，负责整体窗口布局、组件管理和导航控制。

## 导入路径

项目中使用相对导入的方式引用模块：

```python
# 从配置模块导入
from ..config.settings import CONFIG_ITEM

# 从工具模块导入
from ..utils.platform import is_win11

# 从组件模块导入
from .image_card_widget import ImageCardWidget
```

## 运行方式

1. 直接运行：
   ```bash
   python main.py
   ```

2. 使用 uv：
   ```bash
   uv run VSTain
   ```
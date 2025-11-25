# 命名规范

本项目遵循 Python 标准命名规范（PEP 8）。

## 文件命名规范

### 模块文件（.py）
- 使用小写字母和下划线（snake_case）
- 组件文件统一使用 `_widget.py` 后缀
- 窗口文件统一使用 `_window.py` 后缀

### 命名规则

#### 组件文件（widgets/）
- `home_widget.py` - 主页组件
- `image_card_widget.py` - 图片卡片窗口组件
- `settings_widget.py` - 设置页面组件
- `hwnd_list_widget.py` - 窗口列表组件
- `annotation_widget.py` - 注释组件
- `feature_capture_widget.py` - 特征捕获组件

#### 窗口文件（windows/）
- `main_window.py` - 主窗口

#### 工具文件（utils/）
- `logger.py` - 日志工具
- `platform.py` - 平台相关工具

#### 配置文件（config/）
- `settings.py` - 应用配置

#### 公共文件（common/）
- `config.py` - 全局配置
- `style_sheet.py` - 样式表

#### 应用入口
- `app.py` - 应用入口和配置

## 类命名规范

- 使用大驼峰命名（PascalCase）
- 组件类统一使用 `Widget` 后缀
- 窗口类统一使用 `Window` 后缀

### 示例
- `HomeWidget` - 主页组件类
- `ImageCardWidget` - 图片卡片窗口类
- `SettingsWidget` - 设置页面组件类
- `HwndListWidget` - 窗口列表组件类
- `AnnotationWidget` - 注释组件类
- `WindowFeatureCaptureWidget` - 特征捕获组件类
- `MainWindow` - 主窗口类

## 函数和变量命名规范

- 使用小写字母和下划线（snake_case）
- 私有函数和变量使用单下划线前缀（`_private`）
- 常量使用全大写字母和下划线（`CONSTANT_NAME`）

### 示例
- `is_win11()` - 检查是否为 Windows 11
- `setup_logger()` - 设置日志记录器
- `create_app()` - 创建应用
- `init_window()` - 初始化窗口
- `WINDOW_WIDTH` - 窗口宽度常量
- `RESOURCE_DIR` - 资源目录常量

## 目录命名规范

- 使用小写字母和下划线（snake_case）
- 单数形式（如 `widget` 而不是 `widgets`，但本项目使用 `widgets` 表示多个组件的集合）

### 示例
- `src/vstain/` - VSTain 主包目录
- `config/` - 配置模块
- `utils/` - 工具函数模块
- `widgets/` - UI 组件模块
- `windows/` - 窗口类模块
- `common/` - 公共模块

## 导入规范

- 使用相对导入（`from .module import Class`）
- 按标准库、第三方库、本地模块的顺序组织导入
- 使用 `__all__` 明确导出内容

### 示例
```
# 标准库
import os
import sys

# 第三方库
from PyQt5.QtCore import Qt
from qfluentwidgets import FluentIcon

# 本地模块
from ..config.settings import RESOURCE_DIR
from ..utils.platform import is_win11
from .image_card_widget import ImageCardWidget
```

## 总结

所有文件名和类名都遵循以下原则：
1. **一致性** - 同类文件使用统一的后缀
2. **清晰性** - 文件名能清楚表达其功能
3. **规范性** - 遵循 Python PEP 8 标准
4. **可维护性** - 便于查找和理解


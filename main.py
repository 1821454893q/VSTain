"""应用入口点"""

# 在导入任何其他包之前先导入 ONNX Runtime
try:
    import onnxruntime as ort

    print(f"✅ ONNX Runtime 预加载成功: {ort.__version__}")
except ImportError as e:
    print(f"❌ ONNX Runtime 预加载失败: {e}")

from src.vstain.app import main

if __name__ == "__main__":
    main()

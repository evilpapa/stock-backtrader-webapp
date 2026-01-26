"""
快速验证脚本 - 检查ETF动量策略代码语法和导入
"""

import sys
import importlib.util

def check_module(module_path, module_name):
    """检查模块是否可以导入"""
    try:
        spec = importlib.util.spec_from_file_location(module_name, module_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        print(f"✅ {module_name}: 语法正确，可以导入")
        return True
    except Exception as e:
        print(f"❌ {module_name}: 错误 - {e}")
        return False

def main():
    """主验证函数"""
    print("=" * 60)
    print("ETF动量策略代码验证")
    print("=" * 60)
    
    modules = [
        ("strategy/etf_momentum.py", "etf_momentum"),
        ("tests/etf_momentum_test.py", "etf_momentum_test"),
    ]
    
    all_passed = True
    for path, name in modules:
        if not check_module(path, name):
            all_passed = False
    
    print("=" * 60)
    if all_passed:
        print("✅ 所有模块验证通过！")
        print("\n可以运行:")
        print("  python strategy/etf_momentum/backtest_etf_momentum.py")
        print("  python -m unittest tests.etf_momentum_test.EtfMomentumTest")
    else:
        print("❌ 部分模块存在问题，请检查错误信息")
    print("=" * 60)

if __name__ == "__main__":
    main()

from pathlib import Path

import matplotlib.font_manager as font_manager
import matplotlib.pyplot as plt

DEFAULT_FONT_PATH = Path(__file__).with_name("SarasaTermSC-Regular.ttf")


def configure_matplotlib_chinese_font(font_path: str | Path = DEFAULT_FONT_PATH) -> str:
    """配置 matplotlib 使用内置字体渲染中文，并返回字体名称。"""
    font_path = Path(font_path)
    font_manager.fontManager.addfont(font_path)
    font_name = font_manager.FontProperties(fname=font_path).get_name()
    # 同时关闭 unicode 负号，避免中文字体环境下负数符号显示异常。
    plt.rcParams["font.family"] = font_name
    plt.rcParams["axes.unicode_minus"] = False
    return font_name

from pathlib import Path

import matplotlib.font_manager as font_manager
import matplotlib.pyplot as plt

DEFAULT_FONT_PATH = Path(__file__).with_name("SarasaTermSC-Regular.ttf")


def configure_matplotlib_chinese_font(font_path: str | Path = DEFAULT_FONT_PATH) -> str:
    """Configure matplotlib to render Chinese text with the bundled font."""
    font_path = Path(font_path)
    font_manager.fontManager.addfont(font_path)
    font_name = font_manager.FontProperties(fname=font_path).get_name()
    plt.rcParams["font.family"] = font_name
    plt.rcParams["axes.unicode_minus"] = False

    fig, ax = plt.subplots()
    fig.set_tight_layout(False)
    return font_name

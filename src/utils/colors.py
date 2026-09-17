"""终端彩色输出辅助工具。"""

#===========颜色设置================
# 常用颜色代码（前景色）
RED = '\033[91m'
GREEN = '\033[92m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
MAGENTA = '\033[95m'
CYAN = '\033[96m'
WHITE = '\033[97m'
RESET = '\033[0m'  # 重置

def colorize(text, color):
    """使用指定 ANSI 颜色打印文本，并在结尾恢复默认样式。"""
    print(color + text + RESET)

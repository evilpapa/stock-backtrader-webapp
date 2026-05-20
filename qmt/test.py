#encoding:gbk
'''
测试
'''
import sys
import os
import time
from datetime import datetime




ts_fmt="%H:%M:%S"
def init(ctx):
	print(sys.version)
	print("=== Python 运行环境信息 ===")
	# 1. Python 解释器的执行路径
	print(f"解释器路径: {sys.executable}")
	print(f"真实路径:   {os.path.realpath(sys.executable)}")

	# 2. Python 安装的根目录
	print(f"安装根目录: {sys.prefix}")

	# 3. 模块搜索路径 (sys.path)
	print("\n=== 模块搜索路径 (sys.path) ===")
	for path in sys.path:
		print(f"- {path}")

	try:
		while True:
			# 获取当前时间并格式化 (例如: 2026-04-03 16:50:00)
			current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
			print(f"当前时间: {current_time}")

			# 暂停 10 秒
			time.sleep(10)

	except KeyboardInterrupt:
		print("\n程序已停止。")

def get_current_datetime(ctx, fmt="%Y-%m-%d %H:%M:%S"):
	return timetag_to_datetime(ctx.get_bar_timetag(ctx.barpos), fmt)


def execution(ctx):
	current_ts = get_current_datetime(ctx, ts_fmt)
	print(current_ts)





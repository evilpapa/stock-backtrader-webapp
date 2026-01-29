import os
import pandas as pd
import yfinance as yf
from pathlib import Path

DATA_CACHE_DIR = "datas"  # 数据缓存目录

# ==================== 数据获取 ====================
def fetch_etf_data(symbols, start_date, end_date, strategy_name=None):
	"""
	从Yahoo Finance获取ETF数据，支持本地缓存

	优先使用本地缓存文件，如果不存在则从网络下载并保存到本地。
	缓存文件命名格式: {symbol}_{start_date}_{end_date}.pkl

	Args:
		symbols: ETF代码列表
		start_date: 开始日期
		end_date: 结束日期

	Returns:
		dict: {symbol: DataFrame}
	"""
	print("正在获取ETF数据...")

	# 确保缓存目录存在
	data_dir = Path(__file__).resolve().parent.parent / DATA_CACHE_DIR / (strategy_name if strategy_name else "")
	os.makedirs(data_dir, exist_ok=True)

	data_dict = {}

	for symbol in symbols:
		# 生成缓存文件名（去除特殊字符）
		safe_symbol = symbol.replace(".", "_")
		cache_filename = f"{safe_symbol}_{start_date}_{end_date}.pkl"
		cache_filepath = os.path.join(data_dir, cache_filename)

		# 检查缓存文件是否存在
		if os.path.exists(cache_filepath):
			try:
				df = pd.read_pickle(cache_filepath)
				if not df.empty:
					data_dict[symbol] = df
					print(f"  ✓ {symbol}: {len(df)} 条数据 (来自缓存)")
					continue
			except Exception as e:
				print(f"  ⚠ {symbol}: 缓存文件读取失败 ({e})，将重新下载")

		# 从网络下载数据
		try:
			df = yf.download(symbol, start=start_date, end=end_date, progress=False)
			if not df.empty:
				data_dict[symbol] = df
				# 保存到缓存
				try:
					df.to_pickle(cache_filepath)
					print(f"  ✓ {symbol}: {len(df)} 条数据 (已下载并缓存)")
				except Exception as e:
					print(f"  ✓ {symbol}: {len(df)} 条数据 (已下载，缓存保存失败: {e})")
			else:
				print(f"  ✗ {symbol}: 无数据")
		except Exception as e:
			print(f"  ✗ {symbol}: 获取失败 - {e}")

	return data_dict


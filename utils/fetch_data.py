import os
import pandas as pd
from pathlib import Path

from utils.qmt_data_client import QmtDataClient, to_backtrader_ohlcv

DATA_CACHE_DIR = "datas"  # 数据缓存目录

# ==================== 数据获取 ====================
def fetch_etf_data(
	symbols,
	start_date,
	end_date,
	strategy_name=None,
	client=None,
	base_url="http://127.0.0.1:8765",
	token=None,
	period="1d",
	dividend_type="front",
	fields=None,
	use_cache=True,
):
	"""
	从本地 QMT 数据服务获取 ETF 数据，支持本地缓存

	优先使用本地缓存文件，如果不存在则从 QMT 数据服务读取并保存到本地。
	缓存文件命名格式: {symbol}_{start_date}_{end_date}.pkl

	Args:
		symbols: ETF代码列表
		start_date: 开始日期
		end_date: 结束日期
		strategy_name: 缓存子目录
		client: 可选 QmtDataClient，测试或复用连接时传入
		base_url: QMT 数据服务地址
		token: QMT 数据服务 token
		period: QMT K线周期
		dividend_type: QMT 复权方式
		fields: QMT 字段列表
		use_cache: 是否使用本地缓存

	Returns:
		dict: {symbol: DataFrame}
	"""
	print("正在从QMT数据服务获取ETF数据...")

	# 确保缓存目录存在
	data_dir = Path(__file__).resolve().parent.parent / DATA_CACHE_DIR / (strategy_name if strategy_name else "")
	os.makedirs(data_dir, exist_ok=True)

	data_dict = {}
	qmt_client = client or QmtDataClient(base_url=base_url, token=token)
	fields = fields or ["open", "high", "low", "close", "volume"]

	for symbol in symbols:
		qmt_symbol = normalize_qmt_symbol(symbol)
		# 生成缓存文件名（去除特殊字符）
		safe_symbol = qmt_symbol.replace(".", "_")
		cache_filename = f"{safe_symbol}_{start_date}_{end_date}.pkl"
		cache_filepath = os.path.join(data_dir, cache_filename)

		# 检查缓存文件是否存在
		if use_cache and os.path.exists(cache_filepath):
			try:
				df = pd.read_pickle(cache_filepath)
				if not df.empty:
					data_dict[symbol] = df
					print(f"  ✓ {symbol}: {len(df)} 条数据 (来自缓存)")
					continue
			except Exception as e:
				print(f"  ⚠ {symbol}: 缓存文件读取失败 ({e})，将重新获取")

		# 从 QMT 数据服务读取数据
		try:
			df = qmt_client.get_market_data_ex_df(
				qmt_symbol,
				fields=fields,
				stock_code=[qmt_symbol],
				period=period,
				start_time=format_qmt_date(start_date),
				end_time=format_qmt_date(end_date),
				count=-1,
				dividend_type=dividend_type,
				subscribe=False,
			)
			df = to_title_case_ohlcv(to_backtrader_ohlcv(df))
			if not df.empty:
				data_dict[symbol] = df
				# 保存到缓存
				if use_cache:
					try:
						df.to_pickle(cache_filepath)
						print(f"  ✓ {symbol}: {len(df)} 条数据 (已从QMT获取并缓存)")
					except Exception as e:
						print(f"  ✓ {symbol}: {len(df)} 条数据 (已从QMT获取，缓存保存失败: {e})")
				else:
					print(f"  ✓ {symbol}: {len(df)} 条数据 (已从QMT获取)")
			else:
				print(f"  ✗ {symbol}: 无数据")
		except Exception as e:
			print(f"  ✗ {symbol}: 获取失败 - {e}")

	return data_dict


def normalize_qmt_symbol(symbol):
	"""Convert common Yahoo/A-share suffixes to QMT code.market format."""
	if symbol.endswith(".SS"):
		return symbol[:-3] + ".SH"
	if symbol.endswith(".SH") or symbol.endswith(".SZ"):
		return symbol
	if len(symbol) == 6 and symbol.startswith(("5", "6", "9")):
		return symbol + ".SH"
	if len(symbol) == 6:
		return symbol + ".SZ"
	return symbol


def format_qmt_date(value):
	"""Convert YYYY-MM-DD/date-like values to QMT YYYYMMDD strings."""
	if hasattr(value, "strftime"):
		return value.strftime("%Y%m%d")
	return str(value).replace("-", "")


def to_title_case_ohlcv(data_frame):
	"""Keep existing strategy examples working with Open/High/Low/Close/Volume columns."""
	frame = data_frame.copy()
	if "date" in frame.columns:
		frame.index = pd.to_datetime(frame["date"])
	return frame.rename(
		columns={
			"open": "Open",
			"high": "High",
			"low": "Low",
			"close": "Close",
			"volume": "Volume",
		}
	)[["Open", "High", "Low", "Close", "Volume"]]

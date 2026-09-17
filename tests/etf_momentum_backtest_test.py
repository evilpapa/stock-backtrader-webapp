from examples.etf_momentum import parse_data_source_params


def test_etf_momentum_backtest_uses_bigqmt_rpc_arguments():
	"""验证 ETF 动量示例能读取 Big QMT RPC 命令行参数。"""
	params = parse_data_source_params(["--bigqmt-account-id", "account-1", "--bigqmt-timeout", "7.5"])

	assert params.bigqmt_account_id == "account-1"
	assert params.bigqmt_timeout == 7.5

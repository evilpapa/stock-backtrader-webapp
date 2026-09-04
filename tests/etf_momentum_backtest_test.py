from examples.etf_momentum.backtest_etf_momentum import parse_data_source_params


def test_etf_momentum_backtest_uses_bigqmt_rpc_arguments():
	params = parse_data_source_params(["--bigqmt-account-id", "account-1", "--bigqmt-timeout", "7.5"])

	assert params.bigqmt_account_id == "account-1"
	assert params.bigqmt_timeout == 7.5

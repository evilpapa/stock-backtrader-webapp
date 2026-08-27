from examples.etf_momentum.backtest_etf_momentum import parse_data_source_params


def test_etf_momentum_backtest_uses_qmt_api_by_default():
    params = parse_data_source_params([])

    assert params.qmt_base_url == "http://127.0.0.1:10086"
    assert params.qmt_token == "123456789"

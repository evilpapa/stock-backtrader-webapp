import pandas as pd
import pytest

from src.utils.industry_history import build_industry_matrix
from scripts import fetch_citic_industry_history as fetcher
from scripts import fetch_citic_industry_by_stock as stock_fetcher


def test_point_in_time_membership_and_conflicts():
    members = pd.DataFrame([
        ('000001.SZ', '银行', '2020-01-01', '2020-02-01'),
        ('000001.SZ', '电子', '2020-02-01', None),
        ('000002.SZ', '银行', '2020-01-01', None),
        ('000002.SZ', '银行', '2020-01-10', None),
        ('000003.SZ', '银行', None, None),
        ('000004.SZ', '银行', '2020-01-01', None),
        ('000004.SZ', '电子', '2020-01-15', None),
    ], columns=['ts_code', 'l1_name', 'in_date', 'out_date'])
    matrix = build_industry_matrix(members, pd.to_datetime(['2019-12-31', '2020-01-15', '2020-02-01']))
    assert pd.isna(matrix.loc['2019-12-31', '000001.SZ'])
    assert matrix.loc['2020-01-15', '000001.SZ'] == '银行'
    assert matrix.loc['2020-02-01', '000001.SZ'] == '电子'
    assert matrix.loc['2020-01-15', '000002.SZ'] == '银行'
    assert '000003.SZ' not in matrix.columns
    assert pd.isna(matrix.loc['2020-01-15', '000004.SZ'])


def test_missing_columns_fail():
    with pytest.raises(ValueError):
        build_industry_matrix(pd.DataFrame(), pd.DatetimeIndex(['2024-01-01']))


def test_fetch_each_industry_and_both_statuses(tmp_path, monkeypatch):
    monkeypatch.setattr(fetcher, 'PAGE_SIZE', 2)
    calls = []

    class FakeClient:
        def query(self, api, **kwargs):
            calls.append((api, kwargs.copy()))
            offset = kwargs['offset']
            rows = [{'l1_code': kwargs['l1_code'], 'is_new': kwargs['is_new'], 'ts_code': str(i)}
                    for i in range(offset, min(offset + 2, 3))]
            return pd.DataFrame(rows)

    data, records = fetcher.fetch_all(FakeClient(), ['B', 'A'], tmp_path)
    assert len(data) == 12
    assert len(records) == 4
    assert len(calls) == 8
    assert {(c[1]['l1_code'], c[1]['is_new']) for c in calls} == {('A', 'Y'), ('A', 'N'), ('B', 'Y'), ('B', 'N')}
    before = len(calls)
    fetcher.fetch_all(FakeClient(), ['B', 'A'], tmp_path)
    assert len(calls) == before


def test_fetch_by_stock_and_resume(tmp_path, monkeypatch):
    monkeypatch.setattr(stock_fetcher, 'PAGE_SIZE', 2)
    calls = []
    class FakeClient:
        def query(self, api, **kwargs):
            calls.append(kwargs.copy())
            offset = kwargs['offset']
            return pd.DataFrame([{'ts_code': kwargs['ts_code'], 'is_new': kwargs['is_new'], 'n': i}
                                 for i in range(offset, min(offset + 2, 3))])
        def close(self):
            pass
    codes = ['000001.SZ', '600000.SH']
    data, records = stock_fetcher.fetch_all(codes, FakeClient, tmp_path, workers=1)
    assert len(data) == 12
    assert len(records) == 4
    assert len(calls) == 8
    stock_fetcher.fetch_all(codes, FakeClient, tmp_path, workers=1)
    assert len(calls) == 8


def test_stock_filter_rejects_dirty_codes():
    frame = pd.DataFrame({'ts_code': ['000001.SZ', '833243!1.BJ', '600000.SH', '000001.SZ', None]})
    assert stock_fetcher.stock_codes(frame) == ['000001.SZ', '600000.SH']


def test_fetch_rejects_repeated_page(monkeypatch):
    monkeypatch.setattr(fetcher, 'PAGE_SIZE', 1)
    class FakeClient:
        def query(self, api, **kwargs):
            return pd.DataFrame([{'l1_code': 'A', 'ts_code': '000001.SZ'}])
    with pytest.raises(RuntimeError, match='分页响应重复'):
        fetcher.fetch_batch(FakeClient(), 'A', 'Y')

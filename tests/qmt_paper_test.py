import tempfile
import unittest
from unittest.mock import patch
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from src.trading.qmt_paper import plan_digest, submit_plan, validate_plan

NOW = datetime(2026, 11, 6, 10, 0, tzinfo=ZoneInfo('Asia/Shanghai'))


def plan():
    return {'environment': 'broker_simulation', 'account_id': '86962531', 'trade_date': '2026-11-06',
            'signal_date': '2026-11-05', 'orders': [{'symbol': '000001.SZ', 'quantity': 100, 'limit_price': 10.0}]}


class FakeBroker:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    def snapshot(self):
        return {'account_id': '86962531', 'cash': 200000, 'positions': [], 'orders': []}

    def buy_limit(self, *args):
        self.calls.append(args)
        if self.fail:
            raise TimeoutError('timeout')
        return 123


class PaperTest(unittest.TestCase):
    def test_submission_disabled_by_default(self):
        p, b = plan(), FakeBroker()
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaisesRegex(RuntimeError, '尚未启用'):
                submit_plan(b, p, Path(d) / 'j.db', now=NOW, confirmation=plan_digest(p), simulation_verified=True)
        self.assertFalse(b.calls)

    def test_validate_rejects_lots_stale_and_budget(self):
        p = plan()
        self.assertEqual(validate_plan(p, NOW), 1005)
        p['orders'][0]['quantity'] = 101
        with self.assertRaises(ValueError):
            validate_plan(p, NOW)
        p = plan()
        p['signal_date'] = '2026-09-01'
        with self.assertRaises(ValueError):
            validate_plan(p, NOW)
        p = plan()
        p['orders'][0]['quantity'] = 100000
        with self.assertRaises(ValueError):
            validate_plan(p, NOW)

    @patch('src.trading.qmt_paper._SUBMISSION_ENABLED', True)
    def test_submit_once_and_block_duplicate(self):
        b, p = FakeBroker(), plan()
        with tempfile.TemporaryDirectory() as d:
            j = Path(d) / 'journal.db'
            result = submit_plan(b, p, j, now=NOW, confirmation=plan_digest(p), simulation_verified=True)
            self.assertEqual(result[0]['order_id'], 123)
            with self.assertRaises(RuntimeError):
                submit_plan(b, p, j, now=NOW, confirmation=plan_digest(p), simulation_verified=True)
            p['orders'][0]['quantity'] = 200
            with self.assertRaises(RuntimeError):
                submit_plan(b, p, j, now=NOW, confirmation=plan_digest(p), simulation_verified=True)
            self.assertEqual(len(b.calls), 1)

    @patch('src.trading.qmt_paper._SUBMISSION_ENABLED', True)
    def test_timeout_cannot_retry(self):
        b, p = FakeBroker(True), plan()
        with tempfile.TemporaryDirectory() as d:
            j = Path(d) / 'journal.db'
            with self.assertRaisesRegex(RuntimeError, '未知'):
                submit_plan(b, p, j, now=NOW, confirmation=plan_digest(p), simulation_verified=True)
            with self.assertRaises(RuntimeError):
                submit_plan(b, p, j, now=NOW, confirmation=plan_digest(p), simulation_verified=True)
            self.assertEqual(len(b.calls), 1)

    @patch('src.trading.qmt_paper._SUBMISSION_ENABLED', True)
    def test_requires_confirmation(self):
        b, p = FakeBroker(), plan()
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                submit_plan(b, p, Path(d) / 'j.db', now=NOW, confirmation='', simulation_verified=False)
            self.assertFalse(b.calls)


if __name__ == '__main__':
    unittest.main()

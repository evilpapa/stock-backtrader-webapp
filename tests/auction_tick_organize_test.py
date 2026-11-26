"""验证集合竞价原始行情整理的格式和日期校验。"""
import io
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from scripts.organize_auction_ticks import FIELDS, convert_stream
from src.datahub.duckdb_frames import read_frame_with_metadata


class AuctionTickOrganizeTest(unittest.TestCase):
    def test_preserves_fields_and_values(self):
        raw = (','.join(FIELDS) + '\n' +
               '000001.SZ,20260331,91500000,9.89,12.09,10.99,10.99,0,0,0,0,10.99,0,53,0,10.99,0,53,15\n').encode()
        source = {'archive':'202603.rar','member':'202603/20260331.csv','archive_sha256':'abc'}
        with TemporaryDirectory() as root:
            output = Path(root) / '20260331.duckdb'
            result = convert_stream(io.BytesIO(raw), output, '20260331', source)
            data, metadata = read_frame_with_metadata(output)
        self.assertEqual(list(data.columns), FIELDS)
        self.assertEqual(data['security_id'].iloc[0], '000001.SZ')
        self.assertEqual(data['md_time'].iloc[0], 91500000)
        self.assertEqual(result['rows'], 1)
        self.assertEqual(metadata['archive_sha256'], 'abc')

    def test_preserves_fractional_quantities(self):
        raw = (','.join(FIELDS) + '\n' +
               '000001.SZ,20260331,91500000,9.89,12.09,10.99,10.99,0,0,234.8,80771.2,10.99,0,1687.2,0,10.99,0,1687.2,15\n').encode()
        with TemporaryDirectory() as root:
            output = Path(root) / '20260331.duckdb'
            convert_stream(io.BytesIO(raw), output, '20260331', {'archive':'a','member':'b','archive_sha256':'c'})
            data, _ = read_frame_with_metadata(output)
        self.assertAlmostEqual(data['total_volume_trade'].iloc[0], 234.8)
        self.assertAlmostEqual(data['bid_size1'].iloc[0], 1687.2)

    def test_rejects_other_date(self):
        raw = (','.join(FIELDS) + '\n' +
               '000001.SZ,20260330,91500000,9.89,12.09,10.99,10.99,0,0,0,0,10.99,0,53,0,10.99,0,53,15\n').encode()
        with TemporaryDirectory() as root, self.assertRaisesRegex(ValueError, '行情日期'):
            convert_stream(io.BytesIO(raw), Path(root) / '20260331.duckdb', '20260331',
                           {'archive':'a','member':'b','archive_sha256':'c'})

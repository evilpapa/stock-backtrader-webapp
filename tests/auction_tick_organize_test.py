"""验证集合竞价原始行情整理的格式和日期校验。"""
import io
import unittest
import pyarrow as pa
import pyarrow.parquet as pq
from scripts.organize_auction_ticks import FIELDS, convert_stream


class AuctionTickOrganizeTest(unittest.TestCase):
    def test_preserves_fields_and_values(self):
        raw = (','.join(FIELDS) + '\n' +
               '000001.SZ,20260331,91500000,9.89,12.09,10.99,10.99,0,0,0,0,10.99,0,53,0,10.99,0,53,15\n').encode()
        source = {'archive':'202603.rar','member':'202603/20260331.csv','archive_sha256':'abc'}
        output = pa.BufferOutputStream()
        result = convert_stream(io.BytesIO(raw), output, '20260331', source)
        data = pq.read_table(pa.BufferReader(output.getvalue()))
        self.assertEqual(data.column_names, FIELDS)
        self.assertEqual(data['security_id'][0].as_py(), '000001.SZ')
        self.assertEqual(data['md_time'][0].as_py(), 91500000)
        self.assertEqual(result['rows'], 1)
        self.assertEqual(data.schema.metadata[b'archive_sha256'], b'abc')

    def test_preserves_fractional_quantities(self):
        raw = (','.join(FIELDS) + '\n' +
               '000001.SZ,20260331,91500000,9.89,12.09,10.99,10.99,0,0,234.8,80771.2,10.99,0,1687.2,0,10.99,0,1687.2,15\n').encode()
        output = pa.BufferOutputStream()
        convert_stream(io.BytesIO(raw), output, '20260331', {'archive':'a','member':'b','archive_sha256':'c'})
        data = pq.read_table(pa.BufferReader(output.getvalue()))
        self.assertAlmostEqual(data['total_volume_trade'][0].as_py(), 234.8)
        self.assertAlmostEqual(data['bid_size1'][0].as_py(), 1687.2)

    def test_rejects_other_date(self):
        raw = (','.join(FIELDS) + '\n' +
               '000001.SZ,20260330,91500000,9.89,12.09,10.99,10.99,0,0,0,0,10.99,0,53,0,10.99,0,53,15\n').encode()
        with self.assertRaisesRegex(ValueError, '行情日期'):
            convert_stream(io.BytesIO(raw), pa.BufferOutputStream(), '20260331',
                           {'archive':'a','member':'b','archive_sha256':'c'})

"""读取已有 DataHub/Tushare 研究日线、ST 和证券基础信息缓存。"""
from __future__ import annotations
from pathlib import Path
import pandas as pd
from .duckdb_frames import file_sha256, frame_exists, promote_frame, read_frame
from .models import DataKind, DataRequest, DataResult


class ResearchDailyRepository:
    source='tushare_research_duckdb'

    def __init__(self,root: str | Path):
        self.root=Path(root)

    def query(self,kind: DataKind | str,request: DataRequest,*,source: str | None=None):
        kind=DataKind(kind)
        if source not in (None, self.source, 'tushare_research_parquet'):
            raise ValueError('不支持该来源')
        if kind==DataKind.STOCK_BASIC:
            path=self.root/'reference'/'stock_basic.duckdb'
            day=None
        elif kind in (DataKind.ST,DataKind.DAILY_BULK):
            if request.start is None or request.end is None or pd.Timestamp(request.start)!=pd.Timestamp(request.end):
                raise ValueError('需要单日请求')
            day=pd.Timestamp(request.start).strftime('%Y%m%d')
            path=self.root/'raw'/('stock_st' if kind==DataKind.ST else 'daily')/(day+'.duckdb')
        else:
            raise ValueError('不支持该数据类型')
        if not frame_exists(path):
            return None
        path=promote_frame(path)
        frame=read_frame(path)
        if day is not None and (frame.empty or 'trade_date' not in frame or not frame.trade_date.astype(str).eq(day).all()):
            raise ValueError(f'缓存为空或交易日期不一致: {path}')
        version=file_sha256(path)
        if request.symbols:
            if 'ts_code' not in frame:
                raise ValueError(f'缺少证券代码: {path}')
            frame=frame[frame.ts_code.isin(request.symbols)].copy()
        actual_source = self.source if path.suffix == '.duckdb' else 'tushare_research_parquet'
        meta={'source':actual_source,'data_version':version,'path':str(path),'storage':path.suffix[1:],
              'frequency':'1d','adjust':'none'}
        frame.attrs.update(meta)
        return DataResult(frame,actual_source,kind,request.request_id,metadata=meta)

    def save(self,result,request):
        raise NotImplementedError('研究缓存只读')

    def close(self):
        pass

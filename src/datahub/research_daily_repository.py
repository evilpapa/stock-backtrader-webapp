"""读取已有 DataHub/Tushare 研究日线、ST 和证券基础信息缓存。"""
from __future__ import annotations
import hashlib
from pathlib import Path
import pandas as pd
from .models import DataKind, DataRequest, DataResult


class ResearchDailyRepository:
    source='tushare_research_parquet'

    def __init__(self,root: str | Path):
        self.root=Path(root)

    def query(self,kind: DataKind | str,request: DataRequest,*,source: str | None=None):
        kind=DataKind(kind)
        if source and source!=self.source:
            raise ValueError('不支持该来源')
        if kind==DataKind.STOCK_BASIC:
            path=self.root/'reference'/'stock_basic.parquet'
            day=None
        elif kind in (DataKind.ST,DataKind.DAILY_BULK):
            if request.start is None or request.end is None or pd.Timestamp(request.start)!=pd.Timestamp(request.end):
                raise ValueError('需要单日请求')
            day=pd.Timestamp(request.start).strftime('%Y%m%d')
            path=self.root/'raw'/('stock_st' if kind==DataKind.ST else 'daily')/(day+'.parquet')
        else:
            raise ValueError('不支持该数据类型')
        if not path.exists():
            return None
        frame=pd.read_parquet(path)
        if day is not None and (frame.empty or 'trade_date' not in frame or not frame.trade_date.astype(str).eq(day).all()):
            raise ValueError(f'缓存为空或交易日期不一致: {path}')
        version=hashlib.sha256(path.read_bytes()).hexdigest()
        if request.symbols:
            if 'ts_code' not in frame:
                raise ValueError(f'缺少证券代码: {path}')
            frame=frame[frame.ts_code.isin(request.symbols)].copy()
        meta={'source':self.source,'data_version':version,'path':str(path),'storage':'parquet',
              'frequency':'1d','adjust':'none'}
        frame.attrs.update(meta)
        return DataResult(frame,self.source,kind,request.request_id,metadata=meta)

    def save(self,result,request):
        raise NotImplementedError('研究缓存只读')

    def close(self):
        pass

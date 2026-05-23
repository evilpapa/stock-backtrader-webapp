# -*- coding: utf-8 -*-
"""
申请开通QMT请添加微信咨询gjquant，获取更多资料访问https://miniqmt.com/
此代码脚本仅用于软件测试，不能用于实盘交易，以此代码进行交易本人不承担任何损失
通过get_local_data获取本地已经保存的，可用历史数据
通过get_full_tick获取最新的行情报价信息
"""
from xtquant import xtdata
import pandas as pd
import numpy as np

# 分析历史数据
stock_code = "510300.SH"
historical_data = xtdata.get_local_data([], [stock_code], period="1d", count=-1)

if stock_code in historical_data:
    df = historical_data[stock_code]
    
    # 正确转换时间戳（假设时间戳是毫秒级）
    if "time" in df.columns:
        # 将时间列转换为datetime
        df["datetime"] = pd.to_datetime(df["time"], unit="ms")
        start_time = df["datetime"].min()
        end_time = df["datetime"].max()
    else:
        # 如果索引是时间戳
        try:
            start_time = pd.to_datetime(df.index.astype(np.int64), unit="ms").min()
            end_time = pd.to_datetime(df.index.astype(np.int64), unit="ms").max()
        except:
            start_time = "无法解析"
            end_time = "无法解析"
    
    print(f"历史数据时间范围: {start_time} 到 {end_time}")
    print(f"数据条数: {len(df)}")
    print(f"最新收盘价: {df['close'].iloc[-1] if len(df) > 0 else '无数据'}")
else:
    print("未获取到历史数据")

# 分析实时行情
realtime_data = xtdata.get_full_tick([stock_code])
if stock_code in realtime_data:
    tick_data = realtime_data[stock_code]
    print(f"\n实时行情时间: {tick_data['timetag']}")
    print(f"最新价格: {tick_data['lastPrice']}")
    print(f"涨跌幅: {(tick_data['lastPrice'] - tick_data['lastClose']) / tick_data['lastClose'] * 100:.2f}%")
else:
    print("未获取到实时行情数据")

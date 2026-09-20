CREATE TABLE IF NOT EXISTS instrument_master (
    symbol VARCHAR NOT NULL,
    market VARCHAR,
    asset_type VARCHAR NOT NULL,
    source_sectors VARCHAR,
    first_seen_at TIMESTAMP NOT NULL,
    last_seen_at TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS daily_bars (
    symbol VARCHAR NOT NULL,
    market VARCHAR,
    asset_type VARCHAR NOT NULL,
    trade_date DATE NOT NULL,
    open DOUBLE,
    high DOUBLE,
    low DOUBLE,
    close DOUBLE,
    volume DOUBLE,
    amount DOUBLE,
    dividend_type VARCHAR NOT NULL,
    source VARCHAR NOT NULL,
    ingested_at TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS trading_calendar (
    market VARCHAR NOT NULL,
    trade_date DATE NOT NULL,
    is_open BOOLEAN NOT NULL,
    source VARCHAR NOT NULL,
    ingested_at TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS sync_runs (
    run_id VARCHAR PRIMARY KEY,
    started_at TIMESTAMP NOT NULL,
    finished_at TIMESTAMP,
    status VARCHAR NOT NULL,
    start_date DATE,
    end_date DATE,
    dividend_type VARCHAR,
    instrument_count BIGINT DEFAULT 0,
    bar_count BIGINT DEFAULT 0,
    error_count BIGINT DEFAULT 0,
    message VARCHAR
);

CREATE TABLE IF NOT EXISTS sync_errors (
    run_id VARCHAR NOT NULL,
    symbol VARCHAR,
    error_type VARCHAR NOT NULL,
    error VARCHAR NOT NULL,
    created_at TIMESTAMP NOT NULL
);

COMMENT ON COLUMN instrument_master.symbol IS '证券代码，使用 QMT 的 code.market 格式，例如 600000.SH';
COMMENT ON COLUMN instrument_master.market IS '交易市场代码，例如 SH、SZ、BJ';
COMMENT ON COLUMN instrument_master.asset_type IS '资产类型：stock、index、fund、bond、repo、warrant 或 etf';
COMMENT ON COLUMN instrument_master.source_sectors IS '发现该证券的 QMT 板块名称，多个板块使用逗号分隔';
COMMENT ON COLUMN instrument_master.first_seen_at IS '首次发现该证券的时间';
COMMENT ON COLUMN instrument_master.last_seen_at IS '最近一次发现该证券的时间';

COMMENT ON COLUMN daily_bars.symbol IS '证券代码，使用 QMT 的 code.market 格式';
COMMENT ON COLUMN daily_bars.market IS '交易市场代码，例如 SH、SZ、BJ';
COMMENT ON COLUMN daily_bars.asset_type IS '资产类型：stock、index、fund、bond、repo、warrant 或 etf';
COMMENT ON COLUMN daily_bars.trade_date IS '交易日';
COMMENT ON COLUMN daily_bars.open IS '日开盘价';
COMMENT ON COLUMN daily_bars.high IS '日最高价';
COMMENT ON COLUMN daily_bars.low IS '日最低价';
COMMENT ON COLUMN daily_bars.close IS '日收盘价';
COMMENT ON COLUMN daily_bars.volume IS '日成交量，单位由 QMT 原始行情定义';
COMMENT ON COLUMN daily_bars.amount IS '日成交额，单位由 QMT 原始行情定义';
COMMENT ON COLUMN daily_bars.dividend_type IS '复权方式：none、front 或 back';
COMMENT ON COLUMN daily_bars.source IS '数据来源，例如 bigqmt';
COMMENT ON COLUMN daily_bars.ingested_at IS '该行情记录写入本地数据库的时间';

COMMENT ON COLUMN trading_calendar.market IS '交易市场代码，例如 SH、SZ、BJ';
COMMENT ON COLUMN trading_calendar.trade_date IS '日历日期';
COMMENT ON COLUMN trading_calendar.is_open IS '该市场在该日期是否开市';
COMMENT ON COLUMN trading_calendar.source IS '交易日历数据来源';
COMMENT ON COLUMN trading_calendar.ingested_at IS '该日历记录写入本地数据库的时间';

COMMENT ON COLUMN sync_runs.run_id IS '同步任务唯一标识';
COMMENT ON COLUMN sync_runs.started_at IS '同步任务开始时间';
COMMENT ON COLUMN sync_runs.finished_at IS '同步任务结束时间';
COMMENT ON COLUMN sync_runs.status IS '任务状态：running、success、partial 或 failed';
COMMENT ON COLUMN sync_runs.start_date IS '本次同步请求的开始日期';
COMMENT ON COLUMN sync_runs.end_date IS '本次同步请求的结束日期';
COMMENT ON COLUMN sync_runs.dividend_type IS '本次同步使用的复权方式';
COMMENT ON COLUMN sync_runs.instrument_count IS '本次发现的证券数量';
COMMENT ON COLUMN sync_runs.bar_count IS '本次写入或更新的日线记录数量';
COMMENT ON COLUMN sync_runs.error_count IS '本次同步错误数量';
COMMENT ON COLUMN sync_runs.message IS '任务摘要或错误说明';

COMMENT ON COLUMN sync_errors.run_id IS '产生该错误的同步任务唯一标识';
COMMENT ON COLUMN sync_errors.symbol IS '发生错误的证券代码';
COMMENT ON COLUMN sync_errors.error_type IS '错误类型，例如 universe、batch_request 或 empty_data';
COMMENT ON COLUMN sync_errors.error IS '错误详细信息';
COMMENT ON COLUMN sync_errors.created_at IS '错误记录创建时间';

CREATE INDEX IF NOT EXISTS daily_bars_symbol_date_idx ON daily_bars(symbol, trade_date);
CREATE INDEX IF NOT EXISTS daily_bars_asset_date_idx ON daily_bars(asset_type, trade_date);

/ KDB-X tables used by scripts.duckdb.sync.
/ Tables are keyed so repeated synchronisation upserts the same bar.

if[not `instrument_master in key `.;
  instrument_master:`symbol xkey ([]
    symbol:`symbol$(); market:`symbol$(); asset_type:`symbol$();
    source_sectors:`symbol$(); first_seen_at:`timestamp$(); last_seen_at:`timestamp$())]

if[not `market_bars in key `.;
  market_bars:`symbol`period`bar_time`dividend_type xkey ([]
    symbol:`symbol$(); market:`symbol$(); asset_type:`symbol$(); period:`symbol$();
    bar_time:`timestamp$(); open:`float$(); high:`float$(); low:`float$(); close:`float$();
    last_price:`float$(); volume:`float$(); amount:`float$(); bid:`float$(); ask:`float$();
    bid_volume:`float$(); ask_volume:`float$(); dividend_type:`symbol$();
    source:`symbol$(); ingested_at:`timestamp$());
  market_bars:`symbol`period`bar_time`dividend_type`market`asset_type`open`high`low`close`last`volume`amount`bid`ask`bid_volume`ask_volume`source`ingested_at xcol market_bars]

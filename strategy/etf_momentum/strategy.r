# 加载必要的R包
library(quantmod) # 金融数据获取与分析
library(PerformanceAnalytics) # 投资组合绩效分析
library(ggplot2) # 高级绘图
library(dplyr) # 数据处理
library(tidyr) # 数据整理
library(scales) # 图形标度调整
library(patchwork) # 图形组合
library(cowplot) # 图形组合（更精细的控制）

# 1. 数据获取与预处理
# 设置回测时间段 - 确保使用正确的日期格式
backtest_start <- "2024-01-01"
backtest_end <- Sys.Date()

# 转换为日期类型
start_date <- as.Date(backtest_start)
end_date <- as.Date(backtest_end)

# 定义ETF代码 (基于常识的常见代码，Yahoo Finance格式)
# 沪市纳指ETF: 513100.SS
# 沪深300ETF: 510300.SS
# 黄金ETF: 518880.SS
etf_symbols <- c("513100.SS", "510300.SS", "518880.SS")
etf_names <- c("纳指ETF", "沪深300ETF", "黄金ETF")

# 从Yahoo Finance获取数据
cat("正在从Yahoo Finance获取数据...\n")
getSymbols(etf_symbols,
  from = start_date,
  to = end_date,
  src = "yahoo",
  auto.assign = TRUE
)

# 提取调整后收盘价（已考虑分红配股）
prices <- list()
for (i in 1:length(etf_symbols)) {
  symbol_data <- get(etf_symbols[i])
  # 使用调整后收盘价
  prices[[i]] <- Ad(symbol_data)
}
names(prices) <- etf_names

# 合并所有价格数据
price_df <- do.call(merge, prices)
colnames(price_df) <- etf_names

# 2. 计算指标：动量、波动率、调整动量
calculate_metrics <- function(price_series, window = 20) {
  # 计算日收益率
  returns <- dailyReturn(price_series, type = "arithmetic")
  colnames(returns) <- "Return"

  # 计算20日平均收益率（动量）
  momentum <- rollapply(returns, width = window, FUN = mean, align = "right", fill = NA)
  colnames(momentum) <- "Momentum"

  # 计算20日收益率方差（波动率）
  volatility <- rollapply(returns, width = window, FUN = var, align = "right", fill = NA)
  colnames(volatility) <- "Volatility"

  # 计算调整动量（动量/波动率）
  # 注意：使用标准差进行标准化（方差的平方根）
  adj_momentum <- momentum / sqrt(volatility)
  colnames(adj_momentum) <- "Adj_Momentum"

  return(list(
    returns = returns,
    momentum = momentum,
    volatility = volatility,
    adj_momentum = adj_momentum
  ))
}

# 为每个ETF计算指标
cat("正在计算动量指标...\n")
metrics_list <- list()
for (etf in etf_names) {
  metrics_list[[etf]] <- calculate_metrics(price_df[, etf])
}

# 3. 生成交易信号和权重
generate_weights <- function(adj_momentum_df) {
  # 初始化权重数据框
  weights_df <- as.data.frame(adj_momentum_df)
  weights_df[] <- 0 # 所有值初始化为0

  # 对每一行（每个交易日）计算权重
  for (i in 1:nrow(adj_momentum_df)) {
    # 获取当日的调整动量值
    current_momentum <- as.numeric(adj_momentum_df[i, ])

    # 筛选调整动量大于0的标的
    positive_idx <- which(current_momentum > 0 & !is.na(current_momentum))

    if (length(positive_idx) > 0) {
      # 获取正的调整动量值
      positive_momentum <- current_momentum[positive_idx]

      # 按调整动量大小归一化计算权重
      normalized_weights <- positive_momentum / sum(positive_momentum)

      # 分配权重
      weights_df[i, positive_idx] <- normalized_weights
    }
  }

  # 转换为时间序列
  weights_xts <- xts(weights_df, order.by = index(adj_momentum_df))
  colnames(weights_xts) <- colnames(adj_momentum_df)

  return(weights_xts)
}

# 提取所有ETF的调整动量
adj_momentum_all <- do.call(merge, lapply(metrics_list, function(x) x$adj_momentum))
colnames(adj_momentum_all) <- etf_names

# 生成权重序列
cat("正在计算每日权重...\n")
weights <- generate_weights(adj_momentum_all)

# 4. 将权重数据整理到数据框中
# 创建每日权重数据框（包含日期）
daily_weights_df <- data.frame(Date = index(weights))
for (etf in etf_names) {
  daily_weights_df[[etf]] <- as.numeric(weights[, etf])
}

# 计算每个交易日的权重合计（应为1或0）
daily_weights_df$权重合计 <- rowSums(daily_weights_df[, etf_names], na.rm = TRUE)

# 创建每个ETF的单独权重数据框
etf_weight_dfs <- list()
for (etf in etf_names) {
  etf_weight_dfs[[etf]] <- data.frame(
    Date = index(weights),
    ETF = etf,
    Weight = as.numeric(weights[, etf])
  )
}

# 合并所有ETF权重数据框
all_etf_weights_df <- do.call(rbind, etf_weight_dfs)

# 5. 回测计算
# 计算每个ETF的日收益率
returns_all <- do.call(merge, lapply(metrics_list, function(x) x$returns))
colnames(returns_all) <- etf_names

# 调整权重的时间索引，确保与收益率对齐
# 使用T日的权重在T+1日交易
lagged_weights <- lag(weights, 1) # 权重滞后一天
lagged_weights <- lagged_weights[index(returns_all)] # 对齐索引

# 处理缺失值
lagged_weights[is.na(lagged_weights)] <- 0

# 计算策略日收益率（按T+1日开盘价计算，这里用平均价近似）
strategy_returns <- rowSums(returns_all * lagged_weights, na.rm = TRUE)
strategy_returns <- xts(strategy_returns, order.by = index(returns_all))
colnames(strategy_returns) <- "动量策略"

# 6. 绩效指标计算
cat("正在计算绩效指标...\n")
# 策略绩效
strategy_perf <- table.AnnualizedReturns(strategy_returns)
strategy_dd <- table.DownsideRisk(strategy_returns)
max_dd <- maxDrawdown(strategy_returns)
strategy_calmar <- CalmarRatio(strategy_returns)
strategy_sortino <- SortinoRatio(strategy_returns)
strategy_positive_returns <- sum(strategy_returns > 0, na.rm = TRUE)
strategy_total_returns <- sum(!is.na(strategy_returns))
strategy_win_rate <- strategy_positive_returns / strategy_total_returns

# 基准绩效（沪深300ETF）
benchmark_returns <- returns_all[, "沪深300ETF"]
colnames(benchmark_returns) <- "沪深300ETF"
benchmark_perf <- table.AnnualizedReturns(benchmark_returns)
benchmark_dd <- table.DownsideRisk(benchmark_returns)
benchmark_max_dd <- maxDrawdown(benchmark_returns)
benchmark_calmar <- CalmarRatio(benchmark_returns)
benchmark_sortino <- SortinoRatio(benchmark_returns)
benchmark_positive_returns <- sum(benchmark_returns > 0, na.rm = TRUE)
benchmark_total_returns <- sum(!is.na(benchmark_returns))
benchmark_win_rate <- benchmark_positive_returns / benchmark_total_returns

# 等权重组合绩效
equal_weights <- matrix(1 / 3, nrow = nrow(returns_all), ncol = ncol(returns_all))
equal_weights <- xts(equal_weights, order.by = index(returns_all))
colnames(equal_weights) <- etf_names
equal_returns <- rowSums(returns_all * equal_weights, na.rm = TRUE)
equal_returns <- xts(equal_returns, order.by = index(returns_all))
colnames(equal_returns) <- "等权重组合"
equal_perf <- table.AnnualizedReturns(equal_returns)
equal_max_dd <- maxDrawdown(equal_returns)
equal_calmar <- CalmarRatio(equal_returns)
equal_sortino <- SortinoRatio(equal_returns)
equal_positive_returns <- sum(equal_returns > 0, na.rm = TRUE)
equal_total_returns <- sum(!is.na(equal_returns))
equal_win_rate <- equal_positive_returns / equal_total_returns

# 7. 创建绩效指标汇总数据框
# 准备回测期间字符串
backtest_period <- paste0(
  format(as.Date(backtest_start), "%Y-%m-%d"),
  " 至 ",
  format(end_date, "%Y-%m-%d")
)

performance_metrics_df <- data.frame(
  策略 = c("动量策略", "沪深300ETF", "等权重组合"),
  年化收益率 = c(
    round(strategy_perf[1, 1] * 100, 2),
    round(benchmark_perf[1, 1] * 100, 2),
    round(equal_perf[1, 1] * 100, 2)
  ),
  年化波动率 = c(
    round(strategy_perf[2, 1] * 100, 2),
    round(benchmark_perf[2, 1] * 100, 2),
    round(equal_perf[2, 1] * 100, 2)
  ),
  夏普比率 = c(
    round(strategy_perf[3, 1], 3),
    round(benchmark_perf[3, 1], 3),
    round(equal_perf[3, 1], 3)
  ),
  最大回撤 = c(
    round(max_dd * 100, 2),
    round(benchmark_max_dd * 100, 2),
    round(equal_max_dd * 100, 2)
  ),
  卡尔马比率 = c(
    round(strategy_calmar, 3),
    round(benchmark_calmar, 3),
    round(equal_calmar, 3)
  ),
  索提诺比率 = c(
    round(strategy_sortino, 3),
    round(benchmark_sortino, 3),
    round(equal_sortino, 3)
  ),
  胜率 = c(
    round(strategy_win_rate * 100, 2),
    round(benchmark_win_rate * 100, 2),
    round(equal_win_rate * 100, 2)
  ),
  正收益天数 = c(
    strategy_positive_returns,
    benchmark_positive_returns,
    equal_positive_returns
  ),
  总交易天数 = c(
    strategy_total_returns,
    benchmark_total_returns,
    equal_total_returns
  ),
  回测期间 = c(backtest_period, backtest_period, backtest_period)
)

# 8. 绩效指标输出
cat("==================== 绩效指标汇总数据框 ====================\n\n")
print(performance_metrics_df)
cat("\n")

# 9. 输出权重数据
cat("==================== 每日组合权重数据框 ====================\n\n")
cat("每日组合权重数据框（前10行）:\n")
print(head(daily_weights_df, 10))
cat("\n")

cat("每日组合权重数据框（后10行）:\n")
print(tail(daily_weights_df, 10))
cat("\n")

cat("组合权重统计信息:\n")
cat("总交易日数:", nrow(daily_weights_df), "\n")
cat("有权重分配的交易日数:", sum(daily_weights_df$权重合计 > 0), "\n")
cat("无权重分配的交易日数:", sum(daily_weights_df$权重合计 == 0), "\n\n")

# 计算每个ETF的权重统计
cat("各ETF权重统计:\n")
for (etf in etf_names) {
  etf_weights <- daily_weights_df[[etf]]
  cat(etf, ":\n")
  cat("  平均权重:", round(mean(etf_weights) * 100, 2), "%\n")
  cat("  最大权重:", round(max(etf_weights) * 100, 2), "%\n")
  cat("  最小权重:", round(min(etf_weights) * 100, 2), "%\n")
  cat("  正权重天数:", sum(etf_weights > 0), "\n")
  cat("  零权重天数:", sum(etf_weights == 0), "\n\n")
}

# 10. 输出每个ETF的权重数据框
cat("==================== 每个ETF的权重数据框 ====================\n\n")
for (etf in etf_names) {
  cat(etf, "权重数据框（前5行）:\n")
  etf_df <- etf_weight_dfs[[etf]]
  print(head(etf_df, 5))
  cat("\n")
}

# 11. 绘制图表
cat("正在生成图表...\n")

# 准备累计收益率数据
cumulative_returns <- merge(
  cumprod(1 + na.fill(strategy_returns, 0)) - 1,
  cumprod(1 + na.fill(benchmark_returns, 0)) - 1,
  cumprod(1 + na.fill(equal_returns, 0)) - 1
)
colnames(cumulative_returns) <- c("动量策略", "沪深300ETF", "等权重组合")

# 转换为数据框用于ggplot
cumulative_df <- data.frame(
  Date = index(cumulative_returns),
  as.data.frame(cumulative_returns)
)

# 计算最大回撤数据
calculate_drawdown <- function(returns) {
  cum_returns <- cumprod(1 + na.fill(returns, 0))
  drawdown <- cum_returns / cummax(cum_returns) - 1
  return(drawdown)
}

# 计算各策略的回撤
drawdowns <- merge(
  calculate_drawdown(strategy_returns),
  calculate_drawdown(benchmark_returns),
  calculate_drawdown(equal_returns)
)
colnames(drawdowns) <- c("动量策略", "沪深300ETF", "等权重组合")

# 转换为数据框用于ggplot
drawdown_df <- data.frame(
  Date = index(drawdowns),
  as.data.frame(drawdowns)
)

# 定义颜色方案
colors_strategies <- c(
  "动量策略" = "#E41A1C", # 红色
  "沪深300ETF" = "#377EB8", # 蓝色
  "等权重组合" = "#4DAF4A" # 绿色
)

# 设置面积图的透明度
area_alpha <- 0.3

# ============================================================
# 图表1: 动量策略 vs 沪深300ETF 组合图
# ============================================================
# 筛选数据
vs_benchmark_cumulative <- cumulative_df %>%
  select(Date, 动量策略, 沪深300ETF) %>%
  pivot_longer(cols = -Date, names_to = "策略", values_to = "累计收益率")

vs_benchmark_drawdown <- drawdown_df %>%
  select(Date, 动量策略, 沪深300ETF) %>%
  pivot_longer(cols = -Date, names_to = "策略", values_to = "回撤")

# 累计收益率图（隐藏X轴，图例放在左上角，上下排列）
p1_cumulative <- ggplot(
  vs_benchmark_cumulative,
  aes(x = Date, y = 累计收益率, color = 策略)
) +
  geom_line(size = 1.2) +
  labs(
    title = "动量策略 vs 沪深300ETF: 累计收益率",
    x = "", y = "累计收益率"
  ) +
  scale_y_continuous(labels = percent_format()) +
  scale_color_manual(values = colors_strategies[c("动量策略", "沪深300ETF")]) +
  theme_minimal() +
  theme(
    legend.position = c(0.02, 0.98), # 图例在左上角
    legend.justification = c(0, 1), # 对齐到左上角
    legend.direction = "vertical", # 图例上下排列
    legend.title = element_blank(),
    legend.background = element_rect(fill = "white", color = "gray", size = 0.3),
    legend.box.margin = margin(5, 5, 5, 5), # 图例内边距
    legend.spacing.y = unit(0.2, "cm"), # 图例项之间的垂直间距
    legend.text = element_text(size = 10),
    plot.title = element_text(hjust = 0.5, size = 14, face = "bold"),
    axis.title.x = element_blank(),
    axis.text.x = element_blank(),
    axis.ticks.x = element_blank()
  )

# 最大回撤面积图（隐藏标题和X轴，删除图例）
p1_drawdown <- ggplot(
  vs_benchmark_drawdown,
  aes(x = Date, y = 回撤, fill = 策略)
) +
  geom_area(position = "identity", alpha = area_alpha) + # 使用面积图
  labs(
    title = "",
    x = "日期", y = "回撤"
  ) +
  scale_y_continuous(labels = percent_format()) +
  scale_fill_manual(values = colors_strategies[c("动量策略", "沪深300ETF")]) +
  theme_minimal() +
  theme(
    legend.position = "none", # 删除图例
    plot.title = element_blank(),
    axis.title.x = element_text(size = 12)
  )

# 使用cowplot组合图表
p1_combined <- plot_grid(p1_cumulative, p1_drawdown,
  ncol = 1, align = "v",
  rel_heights = c(1, 0.9)
)

# ============================================================
# 图表2: 动量策略 vs 等权重组合 组合图
# ============================================================
# 筛选数据
vs_equal_cumulative <- cumulative_df %>%
  select(Date, 动量策略, 等权重组合) %>%
  pivot_longer(cols = -Date, names_to = "策略", values_to = "累计收益率")

vs_equal_drawdown <- drawdown_df %>%
  select(Date, 动量策略, 等权重组合) %>%
  pivot_longer(cols = -Date, names_to = "策略", values_to = "回撤")

# 累计收益率图（隐藏X轴，图例放在左上角，上下排列）
p2_cumulative <- ggplot(
  vs_equal_cumulative,
  aes(x = Date, y = 累计收益率, color = 策略)
) +
  geom_line(size = 1.2) +
  labs(
    title = "动量策略 vs 等权重组合: 累计收益率",
    x = "", y = "累计收益率"
  ) +
  scale_y_continuous(labels = percent_format()) +
  scale_color_manual(values = colors_strategies[c("动量策略", "等权重组合")]) +
  theme_minimal() +
  theme(
    legend.position = c(0.02, 0.98), # 图例在左上角
    legend.justification = c(0, 1), # 对齐到左上角
    legend.direction = "vertical", # 图例上下排列
    legend.title = element_blank(),
    legend.background = element_rect(fill = "white", color = "gray", size = 0.3),
    legend.box.margin = margin(5, 5, 5, 5), # 图例内边距
    legend.spacing.y = unit(0.2, "cm"), # 图例项之间的垂直间距
    legend.text = element_text(size = 10),
    plot.title = element_text(hjust = 0.5, size = 14, face = "bold"),
    axis.title.x = element_blank(),
    axis.text.x = element_blank(),
    axis.ticks.x = element_blank()
  )

# 最大回撤面积图（隐藏标题和X轴，删除图例）
p2_drawdown <- ggplot(
  vs_equal_drawdown,
  aes(x = Date, y = 回撤, fill = 策略)
) +
  geom_area(position = "identity", alpha = area_alpha) + # 使用面积图
  labs(
    title = "",
    x = "日期", y = "回撤"
  ) +
  scale_y_continuous(labels = percent_format()) +
  scale_fill_manual(values = colors_strategies[c("动量策略", "等权重组合")]) +
  theme_minimal() +
  theme(
    legend.position = "none", # 删除图例
    plot.title = element_blank(),
    axis.title.x = element_text(size = 12)
  )

# 使用cowplot组合图表
p2_combined <- plot_grid(p2_cumulative, p2_drawdown,
  ncol = 1, align = "v",
  rel_heights = c(1, 0.9)
)

# ============================================================
# 图表3: 动量策略 vs 三个单独的ETF (Buy&Hold) 组合图
# ============================================================
# 计算各ETF的累计收益率
etf_cumulative <- do.call(
  merge,
  lapply(
    1:length(etf_names),
    function(i) cumprod(1 + na.fill(returns_all[, i], 0)) - 1
  )
)
colnames(etf_cumulative) <- etf_names

# 计算各ETF的回撤
etf_drawdowns <- do.call(
  merge,
  lapply(
    1:length(etf_names),
    function(i) calculate_drawdown(returns_all[, i])
  )
)
colnames(etf_drawdowns) <- etf_names

# 合并策略和各ETF的数据
all_cumulative <- merge(cumulative_returns[, "动量策略"], etf_cumulative)
all_drawdowns <- merge(calculate_drawdown(strategy_returns), etf_drawdowns)

# 转换为数据框用于ggplot
all_cumulative_df <- data.frame(
  Date = index(all_cumulative),
  as.data.frame(all_cumulative)
)
all_drawdowns_df <- data.frame(
  Date = index(all_drawdowns),
  as.data.frame(all_drawdowns)
)

# 转换为长格式
all_cumulative_long <- pivot_longer(all_cumulative_df,
  cols = -Date,
  names_to = "策略",
  values_to = "累计收益率"
)

all_drawdowns_long <- pivot_longer(all_drawdowns_df,
  cols = -Date,
  names_to = "策略",
  values_to = "回撤"
)

# 设置颜色方案 - 动量策略和三个ETF（确保每个都有不同颜色）
colors_buyhold <- c(
  "动量策略" = "#E41A1C", # 红色
  "纳指ETF" = "#377EB8", # 蓝色
  "沪深300ETF" = "#4DAF4A", # 绿色
  "黄金ETF" = "#984EA3" # 紫色
)

# 确保策略名称与颜色方案匹配
all_cumulative_long$策略 <- factor(all_cumulative_long$策略,
  levels = names(colors_buyhold)
)
all_drawdowns_long$策略 <- factor(all_drawdowns_long$策略,
  levels = names(colors_buyhold)
)

# 累计收益率图（隐藏X轴，图例放在左上角，上下排列）
p3_cumulative <- ggplot(
  all_cumulative_long,
  aes(x = Date, y = 累计收益率, color = 策略)
) +
  geom_line(size = 1.0) +
  labs(
    title = "动量策略 vs 各ETF买入持有策略: 累计收益率",
    x = "", y = "累计收益率"
  ) +
  scale_y_continuous(labels = percent_format()) +
  scale_color_manual(values = colors_buyhold) + # 确保应用颜色方案
  theme_minimal() +
  theme(
    legend.position = c(0.02, 0.98), # 图例在左上角
    legend.justification = c(0, 1), # 对齐到左上角
    legend.direction = "vertical", # 图例上下排列
    legend.title = element_blank(),
    legend.background = element_rect(fill = "white", color = "gray", size = 0.3),
    legend.box.margin = margin(5, 5, 5, 5), # 图例内边距
    legend.spacing.y = unit(0.15, "cm"), # 图例项之间的垂直间距
    legend.text = element_text(size = 9),
    plot.title = element_text(hjust = 0.5, size = 14, face = "bold"),
    axis.title.x = element_blank(),
    axis.text.x = element_blank(),
    axis.ticks.x = element_blank()
  )

# 最大回撤面积图（隐藏标题和X轴，删除图例）
p3_drawdown <- ggplot(
  all_drawdowns_long,
  aes(x = Date, y = 回撤, fill = 策略)
) +
  geom_area(position = "identity", alpha = area_alpha) + # 使用面积图
  labs(
    title = "",
    x = "日期", y = "回撤"
  ) +
  scale_y_continuous(labels = percent_format()) +
  scale_fill_manual(values = colors_buyhold) + # 确保应用颜色方案
  theme_minimal() +
  theme(
    legend.position = "none", # 删除图例
    plot.title = element_blank(),
    axis.title.x = element_text(size = 12)
  )

# 使用cowplot组合图表
p3_combined <- plot_grid(p3_cumulative, p3_drawdown,
  ncol = 1, align = "v",
  rel_heights = c(1, 0.9)
)

# ============================================================
# 图表4: 权重随时间变化图
# ============================================================
# 准备权重数据
weights_long <- pivot_longer(daily_weights_df,
  cols = all_of(etf_names),
  names_to = "ETF",
  values_to = "Weight"
)

# 权重图颜色方案
colors_weights <- c(
  "纳指ETF" = "#E41A1C", # 红色
  "沪深300ETF" = "#377EB8", # 蓝色
  "黄金ETF" = "#4DAF4A" # 绿色
)

p4 <- ggplot(weights_long, aes(x = Date, y = Weight, fill = ETF)) +
  geom_area(position = "stack", alpha = 0.7) +
  labs(
    title = "动量策略: 每日权重分配",
    x = "日期", y = "权重"
  ) +
  scale_y_continuous(labels = percent_format()) +
  scale_fill_manual(values = colors_weights) +
  theme_minimal() +
  theme(
    legend.position = "bottom",
    plot.title = element_text(hjust = 0.5, size = 14, face = "bold")
  )

# 12. 显示图表
cat("\n正在显示图表...\n")
print(p1_combined)
cat("\n\n")
print(p2_combined)
cat("\n\n")
print(p3_combined)
cat("\n\n")
print(p4)

# 13. 保存结果到文件
output_dir <- "momentum_strategy_backtest"
if (!dir.exists(output_dir)) {
  dir.create(output_dir)
}

# 保存绩效指标数据框
write.csv(performance_metrics_df,
  file = paste0(output_dir, "/performance_metrics.csv"),
  row.names = FALSE, fileEncoding = "UTF-8"
)

# 保存权重数据
write.csv(daily_weights_df,
  file = paste0(output_dir, "/daily_weights.csv"),
  row.names = FALSE, fileEncoding = "UTF-8"
)

# 保存每个ETF的权重数据
for (etf in etf_names) {
  write.csv(etf_weight_dfs[[etf]],
    file = paste0(output_dir, "/", etf, "_weights.csv"),
    row.names = FALSE, fileEncoding = "UTF-8"
  )
}

# 保存合并的ETF权重数据
write.csv(all_etf_weights_df,
  file = paste0(output_dir, "/all_etf_weights.csv"),
  row.names = FALSE, fileEncoding = "UTF-8"
)

# 保存累计收益率数据
write.csv(cumulative_df,
  file = paste0(output_dir, "/cumulative_returns.csv"),
  row.names = FALSE, fileEncoding = "UTF-8"
)

# 保存回撤数据
write.csv(drawdown_df,
  file = paste0(output_dir, "/drawdowns.csv"),
  row.names = FALSE, fileEncoding = "UTF-8"
)

# 保存Buy&Hold数据
write.csv(all_cumulative_df,
  file = paste0(output_dir, "/buyhold_cumulative.csv"),
  row.names = FALSE, fileEncoding = "UTF-8"
)

write.csv(all_drawdowns_df,
  file = paste0(output_dir, "/buyhold_drawdowns.csv"),
  row.names = FALSE, fileEncoding = "UTF-8"
)

# 保存图表
ggsave(paste0(output_dir, "/momentum_vs_benchmark.png"), p1_combined, width = 10, height = 8)
ggsave(paste0(output_dir, "/momentum_vs_equal_weight.png"), p2_combined, width = 10, height = 8)
ggsave(paste0(output_dir, "/momentum_vs_etfs_buyhold.png"), p3_combined, width = 10, height = 8)
ggsave(paste0(output_dir, "/daily_weights_plot.png"), p4, width = 10, height = 6)

cat("\n==================== 回测完成 ====================\n")
cat("结果已保存到文件夹:", output_dir, "\n")
cat("包含文件:\n")
cat("1. performance_metrics.csv - 绩效指标汇总数据框\n")
cat("2. daily_weights.csv - 每日权重分配数据框\n")
cat("3. [ETF名称]_weights.csv - 每个ETF的权重数据框\n")
cat("4. all_etf_weights.csv - 所有ETF合并的权重数据框\n")
cat("5. cumulative_returns.csv - 累计收益率数据\n")
cat("6. drawdowns.csv - 回撤数据\n")
cat("7. buyhold_cumulative.csv - Buy&Hold累计收益率数据\n")
cat("8. buyhold_drawdowns.csv - Buy&Hold回撤数据\n")
cat("9. momentum_vs_benchmark.png - 动量策略vs沪深300ETF组合图\n")
cat("10. momentum_vs_equal_weight.png - 动量策略vs等权重组合对比图\n")
cat("11. momentum_vs_etfs_buyhold.png - 动量策略vs各ETF买入持有策略组合图\n")
cat("12. daily_weights_plot.png - 每日权重分配图\n")
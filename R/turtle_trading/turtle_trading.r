library(quantmod)
library(TTR)
library(ggplot2)
library(dplyr)
library(tidyr)

# 海龟交易法则实现函数
turtle_strategy <- function(symbol, start_date, end_date, initial_capital = 100000) {
  # 1. 获取股票数据
  cat("获取", symbol, "数据中...\n")
  getSymbols(symbol, from = start_date, to = end_date, auto.assign = TRUE)
  data <- get(symbol)

  # 转换为数据框并添加日期列
  df <- as.data.frame(data)
  df$Date <- index(data)
  colnames(df) <- c("Open", "High", "Low", "Close", "Volume", "Adjusted", "Date")

  # 2. 计算海龟交易法则指标
  cat("计算技术指标...\n")

  # 计算20日高点和10日低点(入场信号)
  df$high20 <- runMax(df$High, n = 20)
  df$low10 <- runMin(df$Low, n = 10)

  # 计算10日低点和20日高点(离场信号)
  df$low10_exit <- runMin(df$Low, n = 10)
  df$high20_exit <- runMax(df$High, n = 20)

  # 计算波动率N(ATR的简化版)
  df$TR <- NA
  df$TR[1] <- df$High[1] - df$Low[1]
  for (i in 2:nrow(df)) {
    df$TR[i] <- max(df$High[i] - df$Low[i], 
                    abs(df$High[i] - df$Close[i-1]), 
                    abs(df$Low[i] - df$Close[i-1]))
  }
  df$N <- SMA(df$TR, n = 20)  # 20日平均真实波动范围

  # 3. 生成交易信号
  cat("生成交易信号...\n")

  # 初始化信号变量
  df$position <- 0  # 0:空仓, 1:多仓, -1:空仓
  df$signal <- 0    # 1:买入信号, -1:卖出信号, 0:无信号

  # 计算信号
  for (i in 21:nrow(df)) {  # 从有足够数据的行开始
    current_pos <- df$position[i-1]

    # 入场信号
    if (current_pos == 0) {
      # 突破20日高点，买入信号
      if (df$High[i] > df$high20[i-1]) {
        df$signal[i] <- 1
        df$position[i] <- 1
      }
      # 跌破10日低点，卖出信号
      else if (df$Low[i] < df$low10[i-1]) {
        df$signal[i] <- -1
        df$position[i] <- -1
      }
      else {
        df$position[i] <- 0
      }
    }
    # 离场信号 - 当前持有多仓
    else if (current_pos == 1) {
      if (df$Low[i] < df$low10_exit[i-1]) {
        df$signal[i] <- -1
        df$position[i] <- 0
      }
      else {
        df$position[i] <- 1
      }
    }
    # 离场信号 - 当前持有空仓
    else if (current_pos == -1) {
      if (df$High[i] > df$high20_exit[i-1]) {
        df$signal[i] <- 1
        df$position[i] <- 0
      }
      else {
        df$position[i] <- -1
      }
    }
  }

  # 4. 计算头寸规模和账户表现
  cat("计算账户表现...\n")

  # 初始设置
  df$shares <- 0        # 持股数量
  df$cash <- initial_capital  # 现金
  df$total_assets <- initial_capital  # 总资产

  # 计算每笔交易的头寸规模
  for (i in 2:nrow(df)) {
    # 继承前一天的资产
    df$cash[i] <- df$cash[i-1]
    df$shares[i] <- df$shares[i-1]

    # 有交易信号且有足够数据计算N值
    if (df$signal[i] != 0 && !is.na(df$N[i])) {
      # 计算每单位风险对应的资金
      risk_per_unit <- initial_capital * 0.01

      # 计算合约单位(头寸规模)
      if (df$N[i] > 0) {
        contract_units <- floor(risk_per_unit / (df$N[i] * 100))  # 假设每点价值100

        # 买入信号
        if (df$signal[i] == 1) {
          # 如果之前是空仓，先平仓
          if (df$shares[i] < 0) {
            df$cash[i] <- df$cash[i] + abs(df$shares[i]) * df$Close[i]
            df$shares[i] <- 0
          }
          # 买入新头寸
          cost <- contract_units * 100 * df$Close[i]
          if (cost <= df$cash[i]) {
            df$shares[i] <- contract_units * 100
            df$cash[i] <- df$cash[i] - cost
          }
        }
        # 卖出信号
        else if (df$signal[i] == -1) {
          # 如果之前是多仓，先平仓
          if (df$shares[i] > 0) {
            df$cash[i] <- df$cash[i] + df$shares[i] * df$Close[i]
            df$shares[i] <- 0
          }
          # 建立空仓
          if (contract_units > 0) {
            df$shares[i] <- -contract_units * 100
          }
        }
      }
    }

    # 计算总资产
    df$total_assets[i] <- df$cash[i] + df$shares[i] * df$Close[i]
  }

  # 计算每日收益率
  df$return <- c(NA, diff(df$total_assets) / df$total_assets[-nrow(df)])

  return(df)
}

# 策略评估函数
evaluate_strategy <- function(results) {
  cat("\n策略评估结果:\n")

  # 计算基本统计量
  total_return <- (last(results$total_assets) - first(results$total_assets)) / first(results$total_assets) * 100
  num_trades <- sum(abs(results$signal) > 0, na.rm = TRUE)
  start_date <- first(results$Date)
  end_date <- last(results$Date)
  days <- as.numeric(end_date - start_date)
  annual_return <- (1 + total_return/100)^(365/days) - 1

  # 计算最大回撤
  cumulative_max <- cummax(results$total_assets)
  drawdown <- (results$total_assets - cumulative_max) / cumulative_max
  max_drawdown <- min(drawdown, na.rm = TRUE) * 100

  # 输出评估结果
  cat(paste("起始日期: ", start_date, "\n", sep = ""))
  cat(paste("结束日期: ", end_date, "\n", sep = ""))
  cat(paste("总收益率: ", sprintf("%.2f", total_return), "%\n", sep = ""))
  cat(paste("年化收益率: ", sprintf("%.2f", annual_return * 100), "%\n", sep = ""))
  cat(paste("总交易次数: ", num_trades, "\n", sep = ""))
  cat(paste("最大回撤: ", sprintf("%.2f", max_drawdown), "%\n", sep = ""))

  # 计算胜率
  trades <- results %>% filter(signal != 0)
  profitable <- 0
  if(nrow(trades) > 0) {
    for(i in 1:(nrow(trades)-1)) {
      entry <- trades$Close[i]
      exit <- trades$Close[i+1]
      if(trades$signal[i] == 1 && exit > entry) profitable <- profitable + 1
      if(trades$signal[i] == -1 && exit < entry) profitable <- profitable + 1
    }
    win_rate <- profitable / (nrow(trades)-1) * 100
    cat(paste("胜率: ", sprintf("%.2f", win_rate), "%\n", sep = ""))
  }

  return(list(
    total_return = total_return,
    annual_return = annual_return,
    num_trades = num_trades,
    max_drawdown = max_drawdown
  ))
}

# 可视化函数
plot_strategy <- function(results, symbol) {
  # 1. 价格和交易信号图
  p1 <- ggplot(results, aes(x = Date)) +
    geom_line(aes(y = Close, color = "价格")) +
    geom_point(aes(y = Close, color = "买入信号"), 
               data = results %>% filter(signal == 1), shape = 24, fill = "green", size = 3) +
    geom_point(aes(y = Close, color = "卖出信号"), 
               data = results %>% filter(signal == -1), shape = 25, fill = "red", size = 3) +
    labs(title = paste(symbol, "价格与交易信号"), y = "价格", color = "指标") +
    theme_minimal() +
    theme(legend.position = "top")

  # 2. 资产净值曲线
  p2 <- ggplot(results, aes(x = Date, y = total_assets)) +
    geom_line(color = "blue") +
    labs(title = "海龟策略资产净值", y = "资产价值") +
    theme_minimal()

  # 3. 头寸状态图
  results$position_label <- factor(
    results$position, 
    levels = c(-1, 0, 1),
    labels = c("空仓", "平仓", "多仓")
  )

  p3 <- ggplot(results, aes(x = Date, y = position)) +
    geom_step(color = "purple") +
    scale_y_continuous(limits = c(-1.5, 1.5), breaks = c(-1, 0, 1), 
                       labels = c("空仓", "平仓", "多仓")) +
    labs(title = "持仓状态", y = "状态") +
    theme_minimal()

  # 打印图形
  print(p1)
  print(p2)
  print(p3)

  # 返回图形对象(可选)
  return(list(p1, p2, p3))
}

# 主函数：运行海龟策略
run_turtle <- function(symbol, start_date, end_date) {
  # 运行策略
  results <- turtle_strategy(symbol, start_date, end_date)

  # 评估策略
  eval_stats <- evaluate_strategy(results)

  # 可视化结果
  plots <- plot_strategy(results, symbol)

  # 返回结果
  return(list(results = results, stats = eval_stats, plots = plots))
}

# 示例：运行策略
# 可以替换为其他股票代码，如"AAPL", "MSFT", "GOOG"等
turtle_results <- run_turtle("SPY", "2015-01-01", "2025-09-30")
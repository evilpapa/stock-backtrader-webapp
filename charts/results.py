import pandas as pd
from pyecharts import options as opts
from pyecharts.charts import Bar, Line


def draw_result_bar(df: pd.DataFrame, n_scors: int = 3) -> Bar:
	params_columns = df.columns[:-n_scors]
	scores_columns = df.columns[-n_scors:]
	x_data = (
		df[params_columns]
		.apply(
			lambda x: "\n".join([f"{name}_{value}" for name, value in zip(params_columns, x)]),
			axis=1,
		)
		.values.tolist()
	)
	bar = (
		Bar()
		.add_xaxis(x_data)
		.set_global_opts(
			tooltip_opts=opts.TooltipOpts(trigger="axis"),
			legend_opts=opts.LegendOpts(selected_mode="single"),
		)
	)
	for col in scores_columns:
		bar.add_yaxis(col, df[col].values.tolist())
	bar.set_series_opts(
		label_opts=opts.LabelOpts(is_show=False),
		markpoint_opts=opts.MarkPointOpts(
			data=[
				opts.MarkPointItem(type_="max", name="最大值"),
				opts.MarkPointItem(type_="min", name="最小值"),
			]
		),
	)

	return bar


def draw_multi_line(df: pd.DataFrame, title: str = "") -> Line:
	x_data = pd.to_datetime(df["Date"]).dt.strftime("%Y-%m-%d").tolist()
	line = (
		Line()
		.add_xaxis(x_data)
		.set_global_opts(
			title_opts=opts.TitleOpts(title=title),
			tooltip_opts=opts.TooltipOpts(trigger="axis"),
			legend_opts=opts.LegendOpts(type_="scroll", pos_top="8%"),
			datazoom_opts=[
				opts.DataZoomOpts(type_="inside"),
				opts.DataZoomOpts(type_="slider"),
			],
			yaxis_opts=opts.AxisOpts(is_scale=True),
		)
	)
	for column in df.columns:
		if column == "Date":
			continue
		line.add_yaxis(
			column,
			df[column].round(6).tolist(),
			is_smooth=True,
			is_symbol_show=False,
			label_opts=opts.LabelOpts(is_show=False),
		)
	return line


def draw_weight_area(df: pd.DataFrame) -> Line:
	plot_df = df.drop(columns=["权重合计"], errors="ignore")
	x_data = pd.to_datetime(plot_df["Date"]).dt.strftime("%Y-%m-%d").tolist()
	line = (
		Line()
		.add_xaxis(x_data)
		.set_global_opts(
			title_opts=opts.TitleOpts(title="每日权重"),
			tooltip_opts=opts.TooltipOpts(trigger="axis"),
			legend_opts=opts.LegendOpts(type_="scroll", pos_top="8%"),
			datazoom_opts=[
				opts.DataZoomOpts(type_="inside"),
				opts.DataZoomOpts(type_="slider"),
			],
			yaxis_opts=opts.AxisOpts(min_=0, max_=1),
		)
	)
	for column in plot_df.columns:
		if column == "Date":
			continue
		line.add_yaxis(
			column,
			plot_df[column].round(6).tolist(),
			stack="weights",
			is_symbol_show=False,
			areastyle_opts=opts.AreaStyleOpts(opacity=0.55),
			label_opts=opts.LabelOpts(is_show=False),
		)
	return line

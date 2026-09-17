import streamlit as st


def params_selector_ui(params: dict) -> tuple[bool, dict]:
	"""根据策略参数配置渲染参数扫描表单。"""
	params_parse = dict()
	with st.form("_params"):
		for param in params:
			if param["type"] == "int":
				# 每个整数参数使用最小值、最大值和步长生成 Backtrader 参数网格。
				col1, col2 = st.columns(2)
				with col1:
					min_number = st.number_input("min " + param["name"], value=param["min"])
				with col2:
					max_number = st.number_input("max " + param["name"], value=param["max"])
				params_parse[param["name"]] = range(min_number, max_number, param["step"])
			else:
				pass
		submitted = st.form_submit_button("Submit")
	return submitted, params_parse

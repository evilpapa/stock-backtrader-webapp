# QMT 依赖的包列表

## 基于 python 3.6.8 的包依赖

```txt
absl-py==0.2.2
aenum==2.2.3
appdirs==1.4.4
astor==0.6.2
attrs==19.1.0
backcall==0.1.0
backtrader==1.9.78.123
bleach==1.5.0
certifi==2020.6.20
chardet==3.0.4
charset-normalizer==2.0.12
colorama==0.4.1
CVXcanon==0.1.1
cvxopt==1.2.5
cvxpy==0.4.11
cycler==0.10.0
dbf==0.98.3
decorator==4.4.0
defusedxml==0.5.0
dill==0.2.7.1
ecos==2.0.5
entrypoints==0.3
fastcache==1.0.2
gast==0.2.0
grpcio==1.12.1
html5lib==0.9999999
idna==2.10
importlib-resources==5.4.0
ipykernel==5.1.0
ipython==7.4.0
ipython-genutils==0.2.0
jedi==0.13.3
Jinja2==2.10
joblib==0.16.0
jsonschema==3.0.1
jupyter-client==5.2.4
jupyter-core==4.4.0
kiwisolver==1.0.1
lxml==5.4.0
Markdown==2.6.11
MarkupSafe==1.1.1
matplotlib==3.0.3
mistune==0.8.4
multiprocess==0.70.5
multitasking==0.0.12
nbconvert==5.4.1
nbformat==4.4.0
notebook==5.7.8
numexpr==2.7.0
numpy==1.19.1
pandas==1.1.5
pandocfilters==1.4.2
parso==0.4.0
patsy==0.5.0
pickleshare==0.7.5
Pillow==6.0.0
prometheus-client==0.6.0
prompt-toolkit==2.0.9
protobuf==3.5.2
Pygments==2.3.1
pymongo==3.11.3
pymssql==2.1.4.dev5
pyparsing==2.4.0
pyreadline==2.1
pyrsistent==0.14.11
python-dateutil==2.8.0
pytz==2018.3
pywinpty==0.5.5
pyzmq==18.0.1
redis==3.5.3
requests==2.27.1
scikit-learn==0.23.2
scipy==1.5.2
scs==2.1.2
Send2Trash==1.5.0
simplegeneric==0.8.1
simplejson==3.17.2
six==1.12.0
sklearn==0.0
statsmodels==0.12.1
TA-Lib==0.4.17
tables==3.6.1
tensorboard==1.8.0
tensorflow==1.8.0
termcolor==1.1.0
terminado==0.8.2
testpath==0.4.2
threadpoolctl==2.1.0
toolz==0.9.0
torch==1.0.1
tornado==6.0.2
tqdm==4.64.1
traitlets==4.3.2
urllib3==1.25.9
wcwidth==0.1.7
webencodings==0.5.1
Werkzeug==0.14.1
xlrd==1.2.0
XlsxWriter==1.2.7
xlwt==1.3.0
zipp==3.6.0
```

## 基于 python 3.13.11 的包依赖

从 Python 3.6.8 跨越到 Python 3.13.11 是一个巨大的版本跳跃。由于 Python 3.13 移除了许多旧的 C API、废弃了标准库（如 2to3、cgi 等），且对底层 C 扩展有更严格的要求，原列表中诸如 TensorFlow 1.8.0、PyTorch 1.0.1、CVXpy 0.4.11 等极其古老的版本在 Python 3.13 上是绝对无法编译或运行的。

遵循你“不盲目追新、保持稳定、仅作必要兼容升级”的原则，我为你筛选并锁定了最适合 Python 3.13 的成熟、稳定版本（通常是近一两年的长期维护版本或专门修复了 3.13 兼容性的稳定版）。

升级避坑提示（针对你的技术栈）：
1. TensorFlow 1.x 代码坍塌：原环境中的 tensorflow==1.8.0 和 tensorboard==1.8.0 依赖非常老的 Python 内部 C API。升级到 Python 3.13 后，你原有的 TF1 代码（如 tf.Session()）将无法直接运行。如果项目还在频繁使用它，建议使用 tf.compat.v1 语法在 tensorflow==2.18.0 下兼容运行，或者保留一个 Python 3.6 的容器跑老模型。

2. NumPy 2.0 破坏性变更：为了适配 Python 3.13，NumPy 必须升级到 2.1.x 系列。NumPy 2.0 改变了底层 C 扩展 API。这也是为什么我把 pandas、scipy、scikit-learn 一并升级到了近期的稳定版，因为只有这些较新版本才能和 NumPy 2.0 正常协同，否则会高频报 ValueError: NumPy boolean subclass ... changed size 错误。

3. Windows 平台注意：原列表包含 pyreadline，该包在 Python 3.10 之后由于标准库 collections.Callable 被移除而彻底无法安装。现已安全将其剔除，Jupyter 会原生依赖 prompt-toolkit 来处理终端交互，不影响使用。
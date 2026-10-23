"""DataHub 统一异常层。"""

from __future__ import annotations


class DataHubError(RuntimeError):
    """所有数据访问错误的基类。"""


class ProviderUnavailable(DataHubError):
    """Provider 未安装、未连接或暂时不可用。"""


class ProviderPermissionError(DataHubError):
    """Provider 已连接，但当前账号没有所需权限。"""


class UnsupportedDataKind(DataHubError):
    """没有 Provider 支持请求的数据类型。"""


class TickerMappingError(DataHubError, ValueError):
    """证券代码无法识别或不符合统一规范。"""


class DataValidationError(DataHubError, ValueError):
    """Provider 返回的数据未通过统一质量校验。"""


class DataSourceTimeout(DataHubError, TimeoutError):
    """数据源请求超时。"""


class SubscriptionError(DataHubError):
    """实时行情订阅、取消订阅或重连失败。"""


class StorageError(DataHubError):
    """本地缓存或持久化操作失败。"""

"""统一证券代码映射。

代码转换采用显式市场别名表和证券代码段规则，不在业务层做后缀字符串替换。
XtQuant 的不同 API 可以通过 ``xtquant_formats`` 配置不同的市场后缀。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Mapping

from .exceptions import TickerMappingError


@dataclass
class TickerMapper:
    """Tushare 风格内部代码与外部代码格式之间的映射器。"""

    xtquant_formats: Mapping[str, Mapping[str, str]] = field(default_factory=dict)

    _exchange_aliases = {
        "SH": "SH", "SSE": "SH", "XSHG": "SH", "SS": "SH",
        "SZ": "SZ", "SZSE": "SZ", "XSHE": "SZ",
        "BJ": "BJ", "BSE": "BJ", "XBJ": "BJ", "XBJE": "BJ",
    }
    _code_pattern = re.compile(r"^(?P<code>[0-9]{6})(?:\.(?P<exchange>[A-Z0-9]+))?$")

    def normalize(self_or_symbol: "TickerMapper | str", symbol: str | None = None) -> str:
        """规范化代码。

        支持需求文档中的 ``TickerMapper.normalize("000001.XSHE")``，也支持
        ``TickerMapper(custom_formats).normalize(...)``。后者用于 Provider
        针对不同 XtQuant API 的配置。
        """

        mapper = self_or_symbol if isinstance(self_or_symbol, TickerMapper) else _DEFAULT_MAPPER
        value = symbol if isinstance(self_or_symbol, TickerMapper) else self_or_symbol
        return mapper._normalize(value)

    def _normalize(self, symbol: str) -> str:
        value = str(symbol).strip().upper()
        match = self._code_pattern.fullmatch(value)
        if not match:
            raise TickerMappingError(f"无法识别证券代码: {symbol!r}，需要 6 位代码及可选市场后缀")
        code = match.group("code")
        raw_exchange = match.group("exchange")
        if raw_exchange:
            exchange = self._exchange_aliases.get(raw_exchange)
            if exchange is None:
                raise TickerMappingError(f"不支持的证券市场后缀: {raw_exchange!r} ({symbol!r})")
        else:
            exchange = self._infer_exchange(code)
        return f"{code}.{exchange}"

    @classmethod
    def _infer_exchange(cls, code: str) -> str:
        first = code[0]
        if first in {"0", "1", "2", "3"}:
            return "SZ"
        if first in {"4", "8"}:
            return "BJ"
        if first in {"5", "6", "9"}:
            return "SH"
        raise TickerMappingError(f"无法从证券代码推断交易所: {code}")

    def to_tushare(self_or_symbol: "TickerMapper | str", symbol: str | None = None) -> str:
        """转换为 Tushare ``000001.SZ`` 格式。"""

        mapper = self_or_symbol if isinstance(self_or_symbol, TickerMapper) else _DEFAULT_MAPPER
        value = symbol if isinstance(self_or_symbol, TickerMapper) else self_or_symbol
        return mapper.normalize(value)

    def to_xtquant(
        self_or_symbol: "TickerMapper | str", symbol_or_api_type: str | None = None, api_type: str = "market_data"
    ) -> str:
        """按 API 类型配置转换为 XtQuant 代码。"""

        if isinstance(self_or_symbol, TickerMapper):
            mapper = self_or_symbol
            symbol = symbol_or_api_type
            selected_api_type = api_type
        else:
            mapper = _DEFAULT_MAPPER
            symbol = self_or_symbol
            selected_api_type = symbol_or_api_type or api_type
        normalized = mapper.normalize(symbol)
        code, exchange = normalized.split(".")
        formats = mapper.xtquant_formats.get(selected_api_type, mapper.xtquant_formats.get("default", {}))
        external_exchange = formats.get(exchange, exchange)
        return f"{code}.{external_exchange}"

    def to_exchange(self_or_symbol: "TickerMapper | str", symbol: str | None = None) -> str:
        mapper = self_or_symbol if isinstance(self_or_symbol, TickerMapper) else _DEFAULT_MAPPER
        value = symbol if isinstance(self_or_symbol, TickerMapper) else self_or_symbol
        return mapper.normalize(value).rsplit(".", maxsplit=1)[1]

    def validate(self_or_symbol: "TickerMapper | str", symbol: str | None = None) -> bool:
        mapper = self_or_symbol if isinstance(self_or_symbol, TickerMapper) else _DEFAULT_MAPPER
        value = symbol if isinstance(self_or_symbol, TickerMapper) else self_or_symbol
        try:
            mapper.normalize(value)
        except TickerMappingError:
            return False
        return True

    def normalize_many(self, symbols: tuple[str, ...] | list[str]) -> tuple[str, ...]:
        return tuple(self.normalize(item) for item in symbols)


_DEFAULT_MAPPER = TickerMapper()


def normalize(symbol: str) -> str:
    """函数式快捷入口。"""

    return _DEFAULT_MAPPER.normalize(symbol)

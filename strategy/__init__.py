from .etf_momentum import EtfMomentumStrategy
from .equal_weight import EqualWeightStrategy
from .just_buy_hold import JustBuyHoldStrategy
from .ma import MaStrategy
from .macross import MaCrossStrategy
from .leading_rotation import LeadingRotationStrategy
from .sector_rotation import SectorRotationStrategy
from .turtle_trading import TurtleTradingStrategy


__all__ = [
	"MaStrategy",
	"MaCrossStrategy",
	"EtfMomentumStrategy",
	"EqualWeightStrategy",
	"JustBuyHoldStrategy",
	"LeadingRotationStrategy",
	"SectorRotationStrategy",
	"TurtleTradingStrategy",
]

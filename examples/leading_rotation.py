"""龙头动量轮动策略回测。

运行：``uv run python examples/leading_rotation.py``
"""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from examples.rotation_example import main


if __name__ == "__main__":
	main("LeadingRotation", "leading")

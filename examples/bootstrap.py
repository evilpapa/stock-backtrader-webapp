from __future__ import annotations

from pathlib import Path

project_root = Path(__file__).resolve().parents[1]


def project_path(*parts: str) -> Path:
	"""返回项目根目录下的指定路径。"""
	return project_root.joinpath(*parts)

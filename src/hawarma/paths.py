"""
项目路径解析模块

提供统一的项目根目录计算和资源路径查找。
优先使用 CWD 相对路径（git-clone 模式下天然正确），
CWD 下找不到时回退到包安装路径。

⚠️ 一旦文件内容有更新，务必对开头注释进行相应的必要更新
"""

from pathlib import Path

_PROJECT_ROOT_CANDIDATES: list[Path] = [
    Path.cwd(),
    Path(__file__).resolve().parent.parent.parent,
]


def find_project_root() -> Path:
    """查找项目根目录。

    按优先级尝试候选路径，返回第一个包含 configs/config.yaml 的路径。
    如果都找不到，回退到 CWD。
    """
    for candidate in _PROJECT_ROOT_CANDIDATES:
        if (candidate / "configs" / "config.yaml").is_file():
            return candidate
    return Path.cwd()


PROJECT_ROOT: Path = find_project_root()


def config_path() -> Path:
    return PROJECT_ROOT / "configs" / "config.yaml"


def data_path(filename: str) -> Path:
    return PROJECT_ROOT / "data" / filename


def image_dir() -> Path:
    return PROJECT_ROOT / "static" / "img"


def log_dir() -> Path:
    return PROJECT_ROOT / "logs"


def resolve_path(relative_path: str) -> Path:
    """解析配置文件中的相对路径。

    优先尝试直接使用（CWD 相对），找不到则基于项目根目录解析。
    """
    p = Path(relative_path)
    if p.is_absolute() or p.exists():
        return p
    resolved = PROJECT_ROOT / relative_path
    if resolved.exists():
        return resolved
    return p
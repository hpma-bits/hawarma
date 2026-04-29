# hawarma/config.py
"""
配置管理模块

地位：负责从YAML文件加载和验证应用配置，提供类型安全的配置访问

输入：YAML配置文件路径
输出：AppConfig对象（包含ScreenConfig和MatchingConfig）

⚠️ 一旦文件内容有更新，务必对开头注释进行相应的必要更新，同时更新所属目录的md
"""

from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class ScreenConfig(BaseModel):
    resolution: tuple[int, int]
    save_screenshots: bool
    assembly_station_position: tuple[int, int]
    trash_position: tuple[int, int]
    timer_region: tuple[int, int, int, int] = (0, 0, 400, 140)
    raw_ingredients_positions: list[tuple[int, int]]
    cookers_positions: list[tuple[int, int]]
    stockpile_positions: list[tuple[int, int]]
    condiments_positions: list[tuple[int, int]]
    orders_regions: list[tuple[int, int, int, int]]
    ingredients_regions: list[tuple[int, int, int, int]]
    pickup_stations_positions: list[tuple[int, int]]


class MatchingConfig(BaseModel):
    ingredients_strategy: list[str]
    ingredients_threshold: float
    save_best_match_images: bool
    assembly_threshold: float = 0.9
    default_strategy: list[str] = Field(default_factory=list)


class GameConfig(BaseModel):
    cooker_retention: float = 5.0
    rush_red_threshold: int = 180
    rush_detection_positions: list[tuple[int, int]] = Field(default_factory=list)
    serve_verify_wait: float = 0.3
    swipe_params: dict[int, tuple[float, int]] = Field(
        default_factory=lambda: {
            400: (0.2, 10),
            600: (0.25, 12),
            800: (0.3, 15),
            1000: (0.35, 18),
        }
    )


class DebugConfig(BaseModel):
    save_order_screenshots: bool = False
    save_assembly_verify_screenshots: bool = False
    screenshot_directory: str = "logs/order_screenshots"


class AppConfig(BaseModel):
    image_directory: str
    log_directory: str
    recipes_data_path: str
    episode_duration: int
    cookers: tuple[str, ...]
    screen: ScreenConfig
    matching: MatchingConfig
    game: GameConfig = Field(default_factory=GameConfig)
    debug: DebugConfig = Field(default_factory=DebugConfig)
    strategy: str = "default"
    """策略名称，可选: default, cpm, cpm_v2, score_aware, score_preempt, visibility_aware, cooking_first_v2, stockpile_first"""


def load_config(config_path: Path | str = "configs/config.yaml") -> AppConfig:
    """Loads the application configuration from a YAML file."""
    with open(config_path, "r", encoding="utf-8") as f:
        config_data = yaml.safe_load(f)
    return AppConfig.model_validate(config_data)


# Example of how to use it (optional, for direct testing)
if __name__ == "__main__":
    config = load_config()
    print(config)

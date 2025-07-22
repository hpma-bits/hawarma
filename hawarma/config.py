# hawarma/config.py
from dataclasses import dataclass, field
from pathlib import Path
import yaml

@dataclass
class ScreenConfig:
    resolution: tuple[int, int]
    save_screenshots: bool
    assembly_station_position: tuple[int, int]
    raw_ingredients_positions: list[tuple[int, int]]
    cookers_positions: list[tuple[int, int]]
    condiments_positions: list[tuple[int, int]]
    orders_regions: list[tuple[int, int, int, int]]
    ingredients_regions: list[tuple[int, int, int, int]]
    pickup_stations_positions: list[tuple[int, int]]

@dataclass
class MatchingConfig:
    ingredients_strategy: list[str]
    ingredients_threshold: float
    save_best_match_images: bool
    default_strategy: list[str] = field(default_factory=list)

@dataclass
class AppConfig:
    image_directory: str
    log_directory: str
    episode_duration: int
    cookers: tuple[str, ...]
    ingredients: set[str]
    recipes: dict[int, str]
    screen: ScreenConfig
    matching: MatchingConfig

    @classmethod
    def from_dict(cls, data: dict) -> "AppConfig":
        screen_data = data.pop("screen")
        matching_data = data.pop("matching")
        return cls(
            screen=ScreenConfig(**screen_data),
            matching=MatchingConfig(**matching_data),
            **data,
        )

def load_config(config_path: Path | str = "configs/config.yaml") -> AppConfig:
    """Loads the application configuration from a YAML file."""
    with open(config_path, "r", encoding="utf-8") as f:
        config_data = yaml.safe_load(f)
    return AppConfig.from_dict(config_data)

# Example of how to use it (optional, for direct testing)
if __name__ == "__main__":
    config = load_config()
    print(config)

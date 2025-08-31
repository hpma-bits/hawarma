# hawarma/config.py
from pathlib import Path
import yaml
from pydantic import BaseModel, Field

class ScreenConfig(BaseModel):
    resolution: tuple[int, int]
    save_screenshots: bool
    assembly_station_position: tuple[int, int]
    raw_ingredients_positions: list[tuple[int, int]]
    cookers_positions: list[tuple[int, int]]
    condiments_positions: list[tuple[int, int]]
    orders_regions: list[tuple[int, int, int, int]]
    ingredients_regions: list[tuple[int, int, int, int]]
    pickup_stations_positions: list[tuple[int, int]]

class MatchingConfig(BaseModel):
    ingredients_strategy: list[str]
    ingredients_threshold: float
    save_best_match_images: bool
    default_strategy: list[str] = Field(default_factory=list)

class AppConfig(BaseModel):
    image_directory: str
    log_directory: str
    episode_duration: int
    cookers: tuple[str, ...]
    ingredients: set[str]
    recipes: dict[int, str]
    screen: ScreenConfig
    matching: MatchingConfig

def load_config(config_path: Path | str = "configs/config.yaml") -> AppConfig:
    """Loads the application configuration from a YAML file."""
    with open(config_path, "r", encoding="utf-8") as f:
        config_data = yaml.safe_load(f)
    return AppConfig.model_validate(config_data)

# Example of how to use it (optional, for direct testing)
if __name__ == "__main__":
    config = load_config()
    print(config)
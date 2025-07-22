import time
import cv2
from hawarma.config_loader import get_config

config = get_config()


def save_image_with_info(screenshot, info):
    cv2.imwrite(f"{config.log_dir}/{info}_{time.perf_counter():3f}.jpg", screenshot)  # type: ignore

# hawarma/utils/image_utils.py
"""
图像处理工具模块

地位：提供在屏幕指定区域中查找模板图像的工具函数

输入：Template对象、ROI区域、屏幕截图
输出：匹配结果坐标或None

⚠️ 一旦文件内容有更新，务必对开头注释进行相应的必要更新，同时更新所属目录的md
"""

import time

import cv2
from airtest.aircv import crop_image
from airtest.core.api import G, Template


def local_match(
    target: Template,
    roi: tuple | list,
    screen=None,
    save_cropped: bool = False,
    log_dir: str = "logs",
):
    """
    Check if a template exists in a specific region of the screen.

    :param target: Template object to search for.
    :param roi: Region of interest to search in.
    :param screen: Screen image to search in. If None, a new snapshot is taken.
    :param save_cropped: Whether to save the cropped image for debugging.
    :param log_dir: Directory to save debug images.
    :return: coordinate if the template exists, None otherwise.
    """
    if screen is None:
        screen = G.DEVICE.snapshot()

    cropped = crop_image(screen, roi)

    if save_cropped:
        cv2.imwrite(f"{log_dir}/{time.perf_counter()}.jpg", cropped)

    # The original code calls a private method `_cv_match`.
    # The public method is `match_in`, but it works on the whole screen.
    # To replicate the original behavior, we stick to the private one for now,
    # but acknowledge this is brittle and might break in future airtest versions.
    return target._cv_match(cropped)

# hawarma/utils/image_utils.py
import time
from airtest.core.api import G, Template
from airtest.aircv import crop_image
import cv2

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

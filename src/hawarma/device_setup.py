import time

from airtest.core.android.adb import ADB
from airtest.core.api import G, init_device
from airtest.core.settings import Settings as ST
from loguru import logger


def setup_device(adb_address: str) -> None:
    if G._DEVICE is not None:
        logger.info("Airtest device already initialized, skipping.")
        return

    ST.CVSTRATEGY = ["tpl"]
    ST.OPDELAY = 0.05
    ST.THRESHOLD = 0.7
    try:
        logger.info(f"Connecting to Airtest device at {adb_address}...")
        adb = ADB()
        adb.start_server()
        devices = adb.devices()
        if not devices:
            logger.warning("No ADB device found, attempting auto-connect...")
            result = adb.cmd(f"connect {adb_address}", device=False)
            logger.info(f"adb connect result: {result.strip()}")
            time.sleep(1)
            devices = adb.devices()
            if not devices:
                raise RuntimeError(
                    f"Still no ADB device after connecting to {adb_address}. "
                    f"Make sure the device is accessible."
                )
            logger.success(f"Auto-connected to {adb_address}")
        device = init_device(
            platform="Android",
            uuid=adb_address,
            cap_method="MINICAP_APK",
            touch_method="MAXTOUCH",
        )
        if hasattr(device, 'screen_proxy') and device.screen_proxy:
            screen_impl = device.screen_proxy.screen_method
            screen_class = type(screen_impl).__name__
            logger.info(f"Screenshot method: {screen_class}")
        else:
            logger.warning("Screenshot method: not initialized")
        if hasattr(device, 'touch_proxy') and device.touch_proxy:
            touch_impl = device.touch_proxy.touch_method
            if hasattr(touch_impl, 'base_touch') and touch_impl.base_touch:
                touch_class = type(touch_impl.base_touch).__name__
                logger.info(f"Touch method: {touch_class}")
            else:
                logger.warning("Touch base: not initialized")
        else:
            logger.warning("Touch method: not initialized")
        logger.info("Airtest device connected.")
    except Exception as e:
        logger.error(f"Failed to initialize Airtest device: {e}")
        raise

import time

from airtest.core.android.adb import ADB
from airtest.core.api import G, init_device
from airtest.core.settings import Settings as ST
from loguru import logger


def _device_is_offline(adb: ADB, target_address: str) -> bool:
    """检查目标设备是否处于 offline 状态"""
    devices = adb.devices()
    for serial, status in devices:
        if serial == target_address and status == "offline":
            return True
    return False


def _reconnect_adb(adb: ADB, adb_address: str) -> None:
    """adb kill-server → start-server → connect 重新建立 ADB 连接"""
    logger.warning(f"Device {adb_address} offline, restarting ADB server...")
    adb.cmd("kill-server", device=False)
    time.sleep(1)
    adb.start_server()
    time.sleep(1)
    result = adb.cmd(f"connect {adb_address}", device=False)
    logger.info(f"adb reconnect result: {result.strip()}")
    time.sleep(2)


def _ensure_device_connected(adb: ADB, adb_address: str) -> None:
    """确保 ADB 设备在线，必要时自动重连"""
    devices = adb.devices()
    if devices:
        for serial, status in devices:
            if serial == adb_address and status == "device":
                return
            if serial == adb_address and status == "offline":
                _reconnect_adb(adb, adb_address)
                return

    # 设备不在列表中 → 尝试连接
    logger.warning(f"Device {adb_address} not found, attempting connect...")
    result = adb.cmd(f"connect {adb_address}", device=False)
    logger.info(f"adb connect result: {result.strip()}")
    time.sleep(2)

    # 重连后仍然 offline → kill-server + 重试一次
    if _device_is_offline(adb, adb_address):
        _reconnect_adb(adb, adb_address)

    devices = adb.devices()
    if not devices or all(status != "device" for _, status in devices):
        raise RuntimeError(
            f"Still no device online after reconnecting to {adb_address}. "
            f"Make sure the device is accessible."
        )


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

        _ensure_device_connected(adb, adb_address)

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

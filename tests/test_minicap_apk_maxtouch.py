# -*- coding: utf-8 -*-
"""
Test init_device with MINICAP_APK screenshot and MAXTOUCH touch
"""
from airtest.core.api import init_device
from airtest.core.android.adb import ADB
from airtest.core.android.constant import CAP_METHOD, TOUCH_METHOD


def test_minicap_apk_and_maxtouch():
    """Test init_device with MINICAP_APK and MAxtouch"""
    adb = ADB()
    devices = adb.devices()
    if not devices:
        raise RuntimeError("At least one adb device required")
    serialno = devices[0][0]
    
    print("=== Test init_device with MINICAP_APK + MAxTOUCH ===")
    print(f"Device: {serialno}")
    
    # Init device with MINICAP_APK and MAxtouch
    device = init_device(
        platform="Android", 
        uuid=serialno, 
        cap_method="MINICAP_APK", 
        touch_method="MAXTOUCH"
    )
    
    print(f"SDK version: {device.sdk_version}")
    print(f"Cap method: {device._cap_method}")
    print(f"Touch method: {device._touch_method}")
    
    # Test screenshot
    print("\n--- Testing screenshot ---")
    try:
        screen = device.snapshot()
        if screen is not None:
            print(f"Screenshot captured: shape={screen.shape}")
            print("PASSED: snapshot works!")
        else:
            print("WARNING: screenshot returned None")
    except Exception as e:
        print(f"ERROR: snapshot failed: {e}")
    
    # Test touch
    print("\n--- Testing touch ---")
    try:
        device.touch((500, 500))
        print("PASSED: touch works!")
    except Exception as e:
        print(f"ERROR: touch failed: {e}")
    
    # Test swipe
    print("\n--- Testing swipe ---")
    try:
        device.swipe((200, 500), (600, 500), duration=0.2)
        print("PASSED: swipe works!")
    except Exception as e:
        print(f"ERROR: swipe failed: {e}")
    
    # Cleanup
    print("\n--- Cleanup ---")
    if hasattr(device, 'minicap_apk') and device.minicap_apk:
        device.minicap_apk.teardown_stream()
        print("minicap_apk cleaned up")
    if hasattr(device, 'maxtouch') and device.maxtouch:
        device.maxtouch.teardown()
        print("maxtouch cleaned up")
    
    print("\n=== Test completed! ===")
    return device


if __name__ == '__main__':
    test_minicap_apk_and_maxtouch()
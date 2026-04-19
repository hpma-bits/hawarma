#!/usr/bin/env python
"""Timer Detection Latency Test - 直接运行脚本"""

import asyncio
import logging
import time
from airtest.core.api import init_device, touch
from airtest.core.settings import Settings as ST
from loguru import logger

logging.getLogger("airtest").setLevel(logging.DEBUG)

from hawarma.config import load_config
from hawarma.services.recipe_manager import RecipeManager
from hawarma.bridge.scanner import OrderScanner


async def main():
    # 初始化 Airtest 设置
    ST.CVSTRATEGY = ["tpl"]
    ST.OPDELAY = 0.05
    ST.THRESHOLD = 0.7
    
    print("=" * 60)
    print("=== Timer Detection Latency Test ===")
    print("=" * 60)
    
    # 初始化设备
    print("\n[1/4] Initializing device...")
    device = init_device(
        platform="Android",
        uuid="127.0.0.1:16384",
        cap_method="minicap_apk",
    )
    touch((0, 0))
    
    # 打印截图方法
    if hasattr(device, 'screen_proxy') and device.screen_proxy:
        screen_class = type(device.screen_proxy.screen_method).__name__
        print(f"       Screenshot method: {screen_class}")
    
    # 加载配置和配方
    print("\n[2/4] Loading config and recipes...")
    config = load_config()
    recipe_manager = RecipeManager(recipes_path="data/recipes.json")
    all_recipes = recipe_manager.get_all_recipes()
    selected_recipes = all_recipes[:6]
    
    # 初始化 scanner
    print("\n[3/4] Initializing OrderScanner (lazy init)...")
    scanner = OrderScanner(config, selected_recipes)
    
    # main.py 已预热，这里跳过 prewarm
    print("\n[4/4] Stream already prewarmed by main.py")
    
    # 等待用户显示 timer 图标
    print("\n" + "=" * 60)
    print("请显示 timer 图标后，按回车键开始检测...")
    print("=" * 60)
    input("按回车键继续...")
    
    # 检测 timer
    print("\n开始检测 timer...")
    start_time = time.time()
    attempt = 0
    max_attempts = 20
    detected = False
    
    while attempt < max_attempts:
        attempt += 1
        loop_start = time.time()
        
        # 检测 timer
        detected = asyncio.run(scanner.detect_timer())
        
        loop_duration = time.time() - loop_start
        total_duration = time.time() - start_time
        
        status = "DETECTED!" if detected else "..."
        print(f"Attempt {attempt:2d}: {loop_duration:.3f}s (total: {total_duration:.3f}s) [{status}]")
        
        if detected:
            break
    
    # 结果
    print("\n" + "=" * 60)
    if detected:
        print(f"Timer detected after {attempt} attempts ({total_duration:.3f}s)")
        if total_duration < 1.0:
            print(f"OK: 检测延迟 {total_duration:.3f}s 在 1 秒以内")
        else:
            print(f"WARNING: 检测延迟 {total_duration:.3f}s 超过 1 秒!")
    else:
        print(f"FAILED: 在 {max_attempts} 次尝试内未检测到 timer")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
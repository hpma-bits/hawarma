"""
DirectMinitouch - 高性能触摸驱动

通过 ADB forward TCP 连接与设备上的 minitouch 守护进程通信，
绕过 ADB shell 的固有开销，实现精确的 swipe duration。

⚠️ 一旦文件内容有更新，务必对开头注释进行相应的必要更新，同时更新所属目录的md
"""

from __future__ import annotations

import socket
from pathlib import Path

from loguru import logger


class DirectMinitouch:
    """
    直接连接 minitouch 守护进程，执行高速触摸操作。
    
    minitouch 协议格式：
    - d <contact> <x> <y> [<pressure>]    (down/touch)
    - c                              (commit)
    - u <contact>                    (up)
    - w <contact> <duration_ms>      (wait)
    - r                              (reset)
    算法：interval = duration // (steps - 1)，确保总等待时间 = duration
    """
    
    DEFAULT_ABI = "arm64-v8a"
    
    def __init__(self, android_device):
        """
        初始化 DirectMinitouch
        
        Args:
            android_device: Airtest Android 设备对象 (airtest.core.android.device.Device)
        """
        self._android = android_device
        self._serial = getattr(android_device, 'serialno', None) or getattr(android_device.adb, 'serialno', 'unknown')
        self._sock: socket.socket | None = None
        self._localport: int | None = None
        self._contact = 0
        self._max_x = 32768
        self._max_y = 32768
        self._android_size_info: dict | None = None
        self._connect()
    
    def _connect(self) -> None:
        """建立与 minitouch 守护进程的连接"""
        self._push_and_start_minitouch()
        self._sock = self._create_socket_connection()
        _ = self._read_header()
        logger.info(f"DirectMinitouch connected to {self._serial}")
    
    def _push_and_start_minitouch(self) -> None:
        """尝试复用 Airtest 已启动的 minitouch"""
        from airtest.core.android.touch_methods.minitouch import Minitouch
        
        android = self._android
        
        try:
            touch_proxy = getattr(android, 'touch', None)
            if touch_proxy:
                base = getattr(touch_proxy, 'base_touch', None)
                if isinstance(base, Minitouch):
                    self._minitouch_base = base
                    logger.info("Using Airtest minitouch base")
                    return
        except Exception as e:
            logger.warning(f"Failed to get Airtest minitouch: {e}")
        
        raise RuntimeError("Airtest minitouch not initialized. Ensure device uses touch_method='minitouch'")
    
    def _reuse_airtest_minitouch(self, base) -> None:
        """复用 Airtest 已初始化的 minitouch"""
        from airtest.utils.safesocket import SafeSocket
        
        self._sock = SafeSocket()
        self._sock.sock = base.client.sock
        self._localport = base.localport
        self._max_x = base.max_x
        self._max_y = base.max_y
        
        size_info = {"width": 1920, "height": 1080}
        if hasattr(base, 'size_info') and base.size_info:
            size_info = base.size_info
        self._android_size_info = size_info
        
        _ = self._read_header()
        logger.info("Reusing Airtest minitouch connection")
    
    def _start_minitouch_fresh(self) -> None:
        """从头启动 minitouch"""
        import airtest.core.android.static as static_pkg
        
        abi = self._get_device_abi()
        binary_dir = Path(static_pkg.__path__[0]) / "stf_libs" / abi
        local_binary = binary_dir / "minitouch"
        
        if not local_binary.exists():
            for alt_abi in ["armeabi-v7a", "arm64-v8a", "x86_64"]:
                alt_path = binary_dir.parent / alt_abi / "minitouch"
                if alt_path.exists():
                    local_binary = alt_path
                    break
        
        self.remote_binary = f"/data/local/tmp/minitouch"
        self._android.adb.push(str(local_binary), self.remote_binary)
        self._android.adb.shell(f"chmod 755 {self.remote_binary}")
        
        self._localport, deviceport = self._android.adb.setup_forward(
            f"localabstract:minitouch_{self._serial[:8]}"
        )
        deviceport = deviceport[len("localabstract:"):]
        self._deviceport = deviceport
        
        self._android.adb.start_shell(
            f"{self.remote_binary} -n '{deviceport}' 2>&1",
        )
        
        import time
        time.sleep(0.2)
    
    def _get_device_abi(self) -> str:
        """获取设备 ABI"""
        try:
            abi = self._android.adb.shell("getprop ro.product.cpu.abi").strip()
            return abi if abi else self.DEFAULT_ABI
        except Exception:
            return self.DEFAULT_ABI
    
    def _create_socket_connection(self) -> socket.socket:
        """创建 TCP socket 连接到 minitouch（通过 ADB forward）"""
        import socket
        
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5.0)
        try:
            sock.connect(("127.0.0.1", self._localport))
            return sock
        except OSError as e:
            sock.close()
            raise RuntimeError(f"Failed to connect to minitouch: {e}")
    
    def _read_header(self) -> dict:
        """读取 minitouch 头信息"""
        line = b""
        while not line.endswith(b"\n"):
            chunk = self._sock.recv(256)
            if not chunk:
                break
            line += chunk
        
        parts = line.decode().strip().split(",")
        version = int(parts[0])
        max_contacts = int(parts[1])
        max_x = int(parts[2])
        max_y = int(parts[3])
        max_pressure = int(parts[4])
        return {
            "version": version,
            "max_contacts": max_contacts,
            "max_x": max_x,
            "max_y": max_y,
            "max_pressure": max_pressure,
        }
    
    def _send_command(self, cmd: str) -> None:
        """发送命令到 minitouch"""
        if self._sock:
            self._sock.sendall(f"{cmd}\n".encode())
    
    def touch(self, x: int, y: int, pressure: int = 50) -> None:
        """按下并释放（点击）"""
        if hasattr(self, '_minitouch_base') and self._minitouch_base:
            self._minitouch_base.touch((x, y), duration=0.01)
        else:
            raise RuntimeError("minitouch not initialized")
    
    def swipe(
        self,
        start: tuple[int, int],
        end: tuple[int, int],
        duration: float = 0.06,
        steps: int = 5,
    ) -> None:
        """
        执行 swipe 操作
        
        使用 Airtest minitouch 的 swipe 方法。
        duration 在设备端执行，Python 端等待命令发送完成。
        
        Args:
            start: 起始坐标 (x, y)
            end: 结束坐标 (x, y)
            duration: 持续时间（秒）
            steps: 路径步数
        """
        if hasattr(self, '_minitouch_base') and self._minitouch_base:
            self._minitouch_base.swipe(start, end, duration=duration, steps=steps)
        else:
            raise RuntimeError("minitouch not initialized")
    
    def long_press(self, x: int, y: int, duration: float = 0.5, pressure: int = 50) -> None:
        """长按"""
        if hasattr(self, '_minitouch_base') and self._minitouch_base:
            self._minitouch_base.touch((x, y), duration=duration)
        else:
            raise RuntimeError("minitouch not initialized")
    
    def multi_swipe(
        self,
        start1: tuple[int, int],
        end1: tuple[int, int],
        start2: tuple[int, int],
        end2: tuple[int, int],
        duration: float = 0.06,
        steps: int = 2,
    ) -> None:
        """双指滑动"""
        sx1, sy1 = start1
        ex1, ey1 = end1
        sx2, sy2 = start2
        ex2, ey2 = end2
        duration_ms = int(duration * 1000)
        
        self._send_command(f"d 0 {sx1} {sy1} 50")
        self._send_command(f"d 1 {sx2} {sy2} 50")
        
        for i in range(1, steps + 1):
            ratio = i / steps
            x1 = int(sx1 + (ex1 - sx1) * ratio)
            y1 = int(sy1 + (ey1 - sy1) * ratio)
            x2 = int(sx2 + (ex2 - sx2) * ratio)
            y2 = int(sy2 + (ey2 - sy2) * ratio)
            self._send_command(f"m 0 {x1} {y1} 50")
            self._send_command(f"m 1 {x2} {y2} 50")
            if i < steps:
                wait_ms = duration_ms // steps
                if wait_ms > 0:
                    self._send_command(f"w 0 {wait_ms}")
        
        self._send_command("c")
        self._send_command("u 0")
        self._send_command("u 1")
        self._send_command("c")
    
    def disconnect(self) -> None:
        """断开连接（仅清理引用）"""
        if hasattr(self, '_minitouch_base'):
            self._minitouch_base = None
        logger.info("DirectMinitouch disconnected")
    
    def __del__(self):
        """析构时确保关闭连接"""
        self.disconnect()

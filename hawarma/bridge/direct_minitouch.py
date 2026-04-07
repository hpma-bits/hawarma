"""
DirectMinitouch - 高性能触摸驱动

通过 Unix socket 直接与设备上的 minitouch 守护进程通信，
绕过 ADB shell 的固有开销，实现真正的亚毫秒级 swipe 操作。

⚠️ 一旦文件内容有更新，务必对开头注释进行相应的必要更新，同时更新所属目录的md
"""

from __future__ import annotations

import socket
import struct
from pathlib import Path

from loguru import logger


class DirectMinitouch:
    """
    直接连接 minitouch 守护进程，执行高速触摸操作。
    
    minitouch 通过 abstract Unix socket 通信，协议格式：
    - 命令行：d <contact> <x> <y> [<pressure>]    (down/touch)
    - c                                              (commit)
    - u <contact>                                    (up)
    - w <contact> <duration_ms>                      (wait)
    - r                                              (reset)
    """
    
    MINITOUCH_SOCKET = "minitouch"
    DEFAULT_ABI = "arm64-v8a"
    
    def __init__(self, android_device):
        """
        初始化 DirectMinitouch
        
        Args:
            android_device: Airtest Android 设备对象 (airtest.core.android.device.Device)
        """
        self._android = android_device
        self._serial = android_device.serial
        self._sock: socket.socket | None = None
        self._contact = 0
        self._connect()
    
    def _connect(self) -> None:
        """建立与 minitouch 守护进程的连接"""
        self._push_and_start_minitouch()
        self._sock = self._create_socket_connection()
        _ = self._read_header()
        logger.info(f"DirectMinitouch connected to {self._serial}")
    
    def _push_and_start_minitouch(self) -> None:
        """推送 minitouch 二进制到设备并启动守护进程"""
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
        
        remote_binary = f"/data/local/tmp/minitouch_{self._serial.replace(':', '_')}"
        self._android.adb.push(str(local_binary), remote_binary)
        self._android.adb.shell(f"chmod 755 {remote_binary}")
        
        self._android.adb.shell(
            f"STOPMINITOUCH=1 {remote_binary} -d 'abstract:{self.MINITOUCH_SOCKET}' &",
            adb_shell=False,
        )
        import time
        time.sleep(0.1)
    
    def _get_device_abi(self) -> str:
        """获取设备 ABI"""
        try:
            abi = self._android.adb.shell("getprop ro.product.cpu.abi").strip()
            return abi if abi else self.DEFAULT_ABI
        except Exception:
            return self.DEFAULT_ABI
    
    def _create_socket_connection(self) -> socket.socket:
        """创建 Unix socket 连接到 minitouch"""
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            sock.settimeout(5.0)
            sock.connect(f"\0minitouch")
        except OSError:
            sock.close()
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(5.0)
            sock.connect(f"\0{self.MINITOUCH_SOCKET}")
        return sock
    
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
        self._send_command(f"d 0 {x} {y} {pressure}")
        self._send_command("c")
        self._send_command("u 0")
        self._send_command("c")
    
    def swipe(
        self,
        start: tuple[int, int],
        end: tuple[int, int],
        duration: float = 0.06,
        steps: int = 2,
    ) -> None:
        """
        执行 swipe 操作
        
        duration 在设备端执行，Python 端几乎即时返回。
        
        Args:
            start: 起始坐标 (x, y)
            end: 结束坐标 (x, y)
            duration: 持续时间（秒）
            steps: 路径步数（越多越平滑）
        """
        sx, sy = start
        ex, ey = end
        duration_ms = int(duration * 1000)
        
        self._send_command(f"d 0 {sx} {sy} 50")
        
        for i in range(1, steps + 1):
            ratio = i / steps
            x = int(sx + (ex - sx) * ratio)
            y = int(sy + (ey - sy) * ratio)
            self._send_command(f"m 0 {x} {y} 50")
            if i < steps:
                wait_ms = duration_ms // steps
                if wait_ms > 0:
                    self._send_command(f"w 0 {wait_ms}")
        
        self._send_command("c")
        self._send_command("u 0")
        self._send_command("c")
    
    def long_press(
        self,
        x: int,
        y: int,
        duration: float = 0.5,
        pressure: int = 50,
    ) -> None:
        """长按"""
        duration_ms = int(duration * 1000)
        self._send_command(f"d 0 {x} {y} {pressure}")
        self._send_command(f"w 0 {duration_ms}")
        self._send_command("c")
        self._send_command("u 0")
        self._send_command("c")
    
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
        """断开连接"""
        if self._sock:
            try:
                self._send_command("r")
                self._sock.close()
            except Exception:
                pass
            self._sock = None
            logger.info("DirectMinitouch disconnected")
    
    def __del__(self):
        """析构时确保关闭连接"""
        self.disconnect()

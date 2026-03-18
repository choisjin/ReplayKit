# -*- coding: utf-8 -*-
"""VisionCamera DLL 제어 클라이언트.

MATVisionLib.dll을 통해 비전 카메라 연결/캡처/비교 등을 수행.
References/VisionCameraClient.py 기반으로 Robot Framework 의존성을 제거하고
플러그인 구조에 맞게 재구성.
"""

import os
import shutil
import logging
from ctypes import CDLL, WinDLL, c_wchar_p, windll
from pathlib import Path
from PIL import Image

logger = logging.getLogger(__name__)

# modules/ 디렉토리 (DLL 원본 위치)
_MODULES_DIR = Path(__file__).resolve().parent.parent / "modules"

# 의존 DLL을 프로세스에 미리 로드 (한 번만)
_deps_preloaded = False


def _preload_dependency_dlls():
    """MATVisionLib이 의존하는 DLL을 먼저 프로세스에 로드.

    Windows는 이미 로드된 DLL은 재검색하지 않으므로,
    의존 DLL을 먼저 로드하면 경로 문제를 우회할 수 있다.
    """
    global _deps_preloaded
    if _deps_preloaded:
        return
    modules_str = str(_MODULES_DIR)

    # 1) os.add_dll_directory — Python 3.8+
    if hasattr(os, "add_dll_directory"):
        try:
            os.add_dll_directory(modules_str)
        except OSError:
            pass

    # 2) PATH에 추가
    path_env = os.environ.get("PATH", "")
    if modules_str not in path_env:
        os.environ["PATH"] = modules_str + os.pathsep + path_env

    # 3) 의존 DLL을 명시적으로 먼저 로드 (핵심)
    dep_dll = _MODULES_DIR / "LikLGATSImgLib64.dll"
    if dep_dll.exists():
        try:
            CDLL(str(dep_dll), winmode=0)
            logger.info("Pre-loaded dependency: %s", dep_dll)
        except Exception as e:
            logger.warning("Failed to pre-load %s: %s", dep_dll.name, e)

    _deps_preloaded = True


class VisionCameraClient:
    """MATVisionLib.dll 기반 비전 카메라 제어."""

    def __init__(self, model: str, port: dict, context=None):
        """
        Args:
            model: 카메라 모델명 (예: "exo264CGE")
            port: {"Port": serial, "MACAddress": mac, "IP": ip, "Subnetmask": subnet}
            context: 사용하지 않음 (레거시 호환)
        """
        self._device = model
        self._isConnected = False
        self._port = port.get("Port", "")
        self._macaddress = port.get("MACAddress", "")

        # 의존 DLL을 프로세스에 미리 로드
        _preload_dependency_dlls()

        # DLL 로딩: MAC 주소별 복사본 생성 (동시 다중 카메라 지원)
        original_dll = _MODULES_DIR / "MATVisionLib.dll"
        if not original_dll.exists():
            original_dll = Path(__file__).parent / "MATVisionLib.dll"
        if not original_dll.exists():
            raise FileNotFoundError(f"MATVisionLib.dll not found in {_MODULES_DIR} or {Path(__file__).parent}")

        self.myDllPath = str(_MODULES_DIR / f"MATVisionLib_{self._macaddress}.dll")
        if not os.path.exists(self.myDllPath):
            shutil.copyfile(str(original_dll), self.myDllPath)

        self.myDll = CDLL(self.myDllPath, winmode=0)
        self._context = context
        logger.info("VisionCameraClient initialized: model=%s mac=%s dll=%s", model, self._macaddress, self.myDllPath)

    def md_VisionConnect(self) -> tuple[bool, str]:
        """카메라 연결."""
        if self._isConnected:
            return True, "[VisionCamera] Already connected"

        result = self.myDll.Vision_Connect(c_wchar_p(self._macaddress))
        if result == 0:
            self._isConnected = True
            return True, "[VisionCamera] Connect OK"
        else:
            self._isConnected = False
            return False, f"[VisionCamera] Connect fail (code={result})"

    def md_VisionDisconnect(self) -> tuple[bool, str]:
        """카메라 연결 해제."""
        if not self._isConnected:
            return True, "[VisionCamera] Already disconnected"

        result = self.myDll.Vision_Disconnect()
        if result == 0:
            self._isConnected = False
            return True, "[VisionCamera] Disconnect OK"
        else:
            return False, f"[VisionCamera] Disconnect fail (code={result})"

    def md_IsConnect(self) -> tuple[bool, str]:
        """연결 상태 확인."""
        if not self._isConnected:
            return False, "[VisionCamera] Not connected"

        result = self.myDll.isConnect()
        if result == 0:
            return True, "[VisionCamera] Connected"
        elif result == -2:
            self._isConnected = False
            return False, f"[VisionCamera] Connection lost (code={result})"
        else:
            self._isConnected = False
            return False, f"[VisionCamera] Error (code={result})"

    def md_VisionCapture(self, szPath: str, left=-1, top=-1, right=-1, bottom=-1) -> tuple[bool, str]:
        """이미지 캡처 → szPath에 저장. 크롭 좌표 지정 시 자동 크롭."""
        if not self._isConnected:
            return False, "[VisionCamera] Not connected"

        result = self.myDll.Vision_Capture(c_wchar_p(szPath))
        if result == 0:
            if left >= 0 and top >= 0 and right >= 0 and bottom >= 0:
                img = Image.open(szPath)
                cropped = img.crop((left, top, right, bottom))
                cropped.save(szPath)
            return True, "[VisionCamera] Capture OK"
        elif result == -2:
            self._isConnected = False
            return False, f"[VisionCamera] Connection lost (code={result})"
        else:
            return False, f"[VisionCamera] Capture fail (code={result})"

    @property
    def is_connected(self) -> bool:
        return self._isConnected

    def dispose(self):
        """리소스 정리."""
        try:
            if self.myDll is not None:
                self.md_VisionDisconnect()
                del self.myDll
                self.myDll = None
                if os.path.exists(self.myDllPath):
                    os.remove(self.myDllPath)
        except Exception:
            pass

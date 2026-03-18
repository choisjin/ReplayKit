# -*- coding: utf-8 -*-
"""VisionCamera DLL 제어 클라이언트.

MATVisionLib.dll을 통해 비전 카메라 연결/캡처/비교 등을 수행.
References/VisionCameraClient.py 기반으로 Robot Framework 의존성을 제거하고
플러그인 구조에 맞게 재구성.
"""

import os
import sys
import shutil
import logging
from ctypes import CDLL, c_wchar_p
from pathlib import Path
from PIL import Image

logger = logging.getLogger(__name__)

# modules/ 디렉토리 (DLL 원본 위치)
_MODULES_DIR = Path(__file__).resolve().parent.parent / "modules"

# DLL 의존성 검색 경로 등록 (LikLGATSImgLib64.dll 등)
# 한 번만 등록하면 프로세스 수명 동안 유효
_dll_dir_added = False


def _ensure_dll_search_path():
    """modules/ 디렉토리를 Windows DLL 검색 경로에 추가."""
    global _dll_dir_added
    if _dll_dir_added:
        return
    modules_str = str(_MODULES_DIR)
    # Python 3.8+: os.add_dll_directory (가장 안전한 방법)
    if hasattr(os, "add_dll_directory"):
        try:
            os.add_dll_directory(modules_str)
            logger.info("Added DLL directory via os.add_dll_directory: %s", modules_str)
        except OSError as e:
            logger.warning("os.add_dll_directory failed: %s", e)
    # PATH 환경변수에도 추가 (폴백 — 일부 DLL 로더가 참조)
    path_env = os.environ.get("PATH", "")
    if modules_str not in path_env:
        os.environ["PATH"] = modules_str + os.pathsep + path_env
        logger.info("Added modules dir to PATH: %s", modules_str)
    _dll_dir_added = True


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

        # 의존 DLL 검색 경로 등록 (LikLGATSImgLib64.dll 등)
        _ensure_dll_search_path()

        # DLL 로딩: MAC 주소별 복사본 생성 (동시 다중 카메라 지원)
        original_dll = _MODULES_DIR / "MATVisionLib.dll"
        if not original_dll.exists():
            # plugins/ 디렉토리에서도 탐색
            original_dll = Path(__file__).parent / "MATVisionLib.dll"
        if not original_dll.exists():
            raise FileNotFoundError(f"MATVisionLib.dll not found in {_MODULES_DIR} or {Path(__file__).parent}")

        self.myDllPath = str(_MODULES_DIR / f"MATVisionLib_{self._macaddress}.dll")
        if not os.path.exists(self.myDllPath):
            shutil.copyfile(str(original_dll), self.myDllPath)

        # winmode=0: Python 3.8+에서 DLL 자체 디렉토리의 의존 DLL 검색 활성화
        # (기본값은 LOAD_LIBRARY_SEARCH_DEFAULT_DIRS로 DLL 디렉토리를 검색하지 않음)
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

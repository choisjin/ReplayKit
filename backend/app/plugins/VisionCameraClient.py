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
import ctypes
from ctypes import CDLL, c_wchar_p
from pathlib import Path
from PIL import Image

logger = logging.getLogger(__name__)

# modules/ 디렉토리 (DLL 원본 위치)
_MODULES_DIR = Path(__file__).resolve().parent.parent / "modules"


def _load_dll_safe(dll_path: str):
    """여러 방법을 시도하여 DLL 로드. 실패 시 상세 에러 메시지."""
    modules_str = str(_MODULES_DIR)
    errors = []

    # 방법 1: SetDllDirectoryW로 검색 경로 지정 후 로드
    try:
        ctypes.windll.kernel32.SetDllDirectoryW(modules_str)
        dll = CDLL(dll_path)
        logger.info("DLL loaded (SetDllDirectory): %s", dll_path)
        return dll
    except Exception as e:
        errors.append(f"SetDllDirectory: {e}")
    finally:
        ctypes.windll.kernel32.SetDllDirectoryW(None)  # 복원

    # 방법 2: winmode=0 (Python 3.8+ LoadLibrary fallback)
    try:
        dll = CDLL(dll_path, winmode=0)
        logger.info("DLL loaded (winmode=0): %s", dll_path)
        return dll
    except Exception as e:
        errors.append(f"winmode=0: {e}")

    # 방법 3: os.add_dll_directory + 기본 로드
    if hasattr(os, "add_dll_directory"):
        try:
            cookie = os.add_dll_directory(modules_str)
            try:
                dll = CDLL(dll_path)
                logger.info("DLL loaded (add_dll_directory): %s", dll_path)
                return dll
            finally:
                cookie.close()
        except Exception as e:
            errors.append(f"add_dll_directory: {e}")

    # 방법 4: LoadLibraryW 직접 호출
    try:
        ctypes.windll.kernel32.SetDllDirectoryW(modules_str)
        handle = ctypes.windll.kernel32.LoadLibraryW(dll_path)
        ctypes.windll.kernel32.SetDllDirectoryW(None)
        if handle:
            logger.info("DLL loaded (LoadLibraryW): %s", dll_path)
            # handle을 CDLL로 래핑
            dll = CDLL(dll_path, handle=handle)
            return dll
        else:
            err_code = ctypes.get_last_error()
            errors.append(f"LoadLibraryW: Windows error code {err_code}")
    except Exception as e:
        errors.append(f"LoadLibraryW: {e}")

    # 모든 방법 실패
    detail = (
        f"DLL 로드 실패: {dll_path}\n"
        f"  modules dir: {modules_str} (exists={Path(modules_str).exists()})\n"
        f"  Python: {sys.version} ({'64bit' if sys.maxsize > 2**32 else '32bit'})\n"
        f"  시도한 방법:\n"
    )
    for err in errors:
        detail += f"    - {err}\n"

    # modules 디렉토리 내 DLL 목록
    if Path(modules_str).exists():
        dlls = [f.name for f in Path(modules_str).iterdir() if f.suffix.lower() == '.dll']
        detail += f"  modules 내 DLL: {dlls}\n"

    raise OSError(detail)


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

        # DLL 로딩: MAC 주소별 복사본 생성 (동시 다중 카메라 지원)
        original_dll = _MODULES_DIR / "MATVisionLib.dll"
        if not original_dll.exists():
            original_dll = Path(__file__).parent / "MATVisionLib.dll"
        if not original_dll.exists():
            raise FileNotFoundError(f"MATVisionLib.dll not found in {_MODULES_DIR} or {Path(__file__).parent}")

        self.myDllPath = str(_MODULES_DIR / f"MATVisionLib_{self._macaddress}.dll")
        if not os.path.exists(self.myDllPath):
            shutil.copyfile(str(original_dll), self.myDllPath)

        # 의존 DLL 먼저 로드 시도 (LikLGATSImgLib64.dll)
        dep_dll = _MODULES_DIR / "LikLGATSImgLib64.dll"
        if dep_dll.exists():
            try:
                _load_dll_safe(str(dep_dll))
                logger.info("Pre-loaded dependency: %s", dep_dll.name)
            except Exception as e:
                logger.warning("Failed to pre-load %s: %s", dep_dll.name, e)

        # 메인 DLL 로드
        self.myDll = _load_dll_safe(self.myDllPath)
        self._context = context
        logger.info("VisionCameraClient initialized: model=%s mac=%s dll=%s",
                     model, self._macaddress, self.myDllPath)

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

# -*- coding: utf-8 -*-
"""VisionCamera 클라이언트 — harvesters + Vimba GenTL 기반.

MATVisionLib.dll 대신 harvesters 라이브러리를 사용하여
Vimba GenTL producer (.cti)를 통해 GigE Vision 카메라에 접근.
"""

import os
import glob
import logging
import numpy as np
from pathlib import Path
from PIL import Image

logger = logging.getLogger(__name__)


def _find_cti_files() -> list[str]:
    """Vimba X GenTL producer (.cti) 파일을 자동 탐색."""
    search_dirs = [
        r"C:\Program Files\Allied Vision\Vimba X\cti",
        r"C:\Program Files\Allied Vision\VimbaX\cti",
        r"C:\Program Files (x86)\Allied Vision\Vimba X\cti",
    ]
    # 환경변수
    for var in ("VIMBA_X_HOME", "VIMBA_HOME"):
        val = os.environ.get(var, "")
        if val:
            search_dirs.append(os.path.join(val, "cti"))
    gentl = os.environ.get("GENICAM_GENTL64_PATH", "")
    if gentl:
        search_dirs.extend(gentl.split(os.pathsep))

    cti_files = []
    for d in search_dirs:
        if os.path.isdir(d):
            cti_files.extend(glob.glob(os.path.join(d, "*.cti")))
    return list(set(cti_files))


class VisionCameraClient:
    """harvesters 기반 GigE Vision 카메라 제어."""

    def __init__(self, model: str, port: dict, context=None):
        self._device = model
        self._isConnected = False
        self._macaddress = port.get("MACAddress", "")
        self._device_id = f"DEV_{self._macaddress}"

        self._harvester = None
        self._ia = None  # ImageAcquirer

        # CTI 파일 탐색
        self._cti_files = _find_cti_files()
        if not self._cti_files:
            raise FileNotFoundError(
                "GenTL producer (.cti) 파일을 찾을 수 없습니다. "
                "Vimba X SDK가 설치되어 있는지 확인하세요."
            )
        logger.info("VisionCameraClient: mac=%s, CTI files=%d",
                     self._macaddress, len(self._cti_files))

    def md_VisionConnect(self) -> tuple[bool, str]:
        """카메라 연결."""
        if self._isConnected and self._ia:
            return True, "[VisionCamera] Already connected"

        try:
            from harvesters.core import Harvester

            self._harvester = Harvester()
            for cti in self._cti_files:
                self._harvester.add_file(cti)
            self._harvester.update()

            # MAC 주소로 카메라 찾기
            idx = None
            for i, info in enumerate(self._harvester.device_info_list):
                if self._device_id in info.id_ or self._macaddress in info.id_:
                    idx = i
                    break

            if idx is None:
                cam_list = [info.id_ for info in self._harvester.device_info_list]
                self._harvester.reset()
                self._harvester = None
                return False, (
                    f"[VisionCamera] 카메라 {self._device_id} 를 찾을 수 없습니다. "
                    f"검색된 카메라: {cam_list}"
                )

            self._ia = self._harvester.create(idx)
            self._ia.start()
            self._isConnected = True
            logger.info("VisionCamera connected: %s", self._device_id)
            return True, f"[VisionCamera] Connect OK ({self._device_id})"

        except Exception as e:
            self._cleanup()
            return False, f"[VisionCamera] Connect fail: {e}"

    def md_VisionDisconnect(self) -> tuple[bool, str]:
        """카메라 연결 해제."""
        if not self._isConnected:
            return True, "[VisionCamera] Already disconnected"
        try:
            self._cleanup()
            return True, "[VisionCamera] Disconnect OK"
        except Exception as e:
            return False, f"[VisionCamera] Disconnect fail: {e}"

    def md_IsConnect(self) -> tuple[bool, str]:
        """연결 상태 확인."""
        if self._isConnected and self._ia:
            return True, "[VisionCamera] Connected"
        return False, "[VisionCamera] Not connected"

    def md_VisionCapture(self, szPath: str, left=-1, top=-1, right=-1, bottom=-1) -> tuple[bool, str]:
        """이미지 캡처 → szPath에 저장."""
        if not self._isConnected or not self._ia:
            return False, "[VisionCamera] Not connected"

        try:
            with self._ia.fetch(timeout=10) as buffer:
                comp = buffer.payload.components[0]
                data = comp.data
                w, h = comp.width, comp.height

                # numpy array 변환
                if data.ndim == 1:
                    if w * h == len(data):
                        img_arr = data.reshape(h, w)
                    else:
                        channels = len(data) // (w * h)
                        img_arr = data.reshape(h, w, channels)
                else:
                    img_arr = data

                # PIL Image 변환
                if img_arr.ndim == 2:
                    img = Image.fromarray(img_arr, 'L').convert('RGB')
                elif img_arr.shape[2] == 1:
                    img = Image.fromarray(img_arr[:, :, 0], 'L').convert('RGB')
                elif img_arr.shape[2] == 3:
                    img = Image.fromarray(img_arr, 'RGB')
                else:
                    img = Image.fromarray(img_arr[:, :, :3], 'RGB')

                # 크롭
                if left >= 0 and top >= 0 and right >= 0 and bottom >= 0:
                    img = img.crop((left, top, right, bottom))

                # 디렉토리 생성 + 저장
                Path(szPath).parent.mkdir(parents=True, exist_ok=True)
                img.save(szPath)

            return True, "[VisionCamera] Capture OK"

        except Exception as e:
            logger.error("VisionCamera capture failed: %s", e)
            return False, f"[VisionCamera] Capture fail: {e}"

    @property
    def is_connected(self) -> bool:
        return self._isConnected

    def _cleanup(self):
        """리소스 정리."""
        self._isConnected = False
        if self._ia:
            try:
                self._ia.stop()
            except Exception:
                pass
            try:
                self._ia.destroy()
            except Exception:
                pass
            self._ia = None
        if self._harvester:
            try:
                self._harvester.reset()
            except Exception:
                pass
            self._harvester = None

    def dispose(self):
        self._cleanup()

"""Installer-provisioned shared credentials protected for the current Windows user.

DPAPI protects the installed copy at rest. The client-held shared key remains
recoverable by its user, as explicitly chosen by the product owner.
"""

import ctypes
from ctypes import wintypes
from pathlib import Path

from doctranslator_server.settings import ServerSettings


class _Blob(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]


def _crypt(data: bytes, *, decrypt: bool) -> bytes:
    buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    source = _Blob(len(data), buffer)
    target = _Blob()
    function = (
        ctypes.windll.crypt32.CryptUnprotectData
        if decrypt
        else ctypes.windll.crypt32.CryptProtectData
    )
    if not function(ctypes.byref(source), None, None, None, None, 0x1, ctypes.byref(target)):
        raise OSError("Windows credential protection failed")
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        ctypes.windll.kernel32.LocalFree(target.data)


def protect_secret(data: bytes) -> bytes:
    return _crypt(data, decrypt=False)


def unprotect_secret(data: bytes) -> bytes:
    return _crypt(data, decrypt=True)


def load_provisioned(settings: ServerSettings, application: Path, metadata: Path) -> ServerSettings:
    packaged = application / "provisioning.json"
    protected = metadata / "davy.dpapi"
    if packaged.is_file():
        # A signed app/config update replaces this resource. Reprotect on startup
        # so rotation is independent of the website and never requires key entry.
        payload = packaged.read_bytes()
        try:
            configured = ServerSettings.model_validate_json(payload)
        except ValueError:
            raise ValueError("Installer translation configuration is invalid") from None
        metadata.mkdir(parents=True, exist_ok=True)
        temporary = protected.with_suffix(".tmp")
        temporary.write_bytes(_crypt(payload, decrypt=False))
        temporary.replace(protected)
    elif protected.is_file():
        try:
            configured = ServerSettings.model_validate_json(
                _crypt(protected.read_bytes(), decrypt=True)
            )
        except ValueError:
            raise ValueError("Installed translation configuration requires repair") from None
    else:
        return settings
    return settings.model_copy(
        update={
            "davy_base_url": configured.davy_base_url,
            "davy_api_key": configured.davy_api_key,
            "davy_models": configured.davy_models,
        }
    )

"""Guarda o login do Google protegido.

No Windows usa a DPAPI (a mesma proteção que o Windows usa para senhas salvas): o arquivo só pode
ser lido pelo mesmo usuário do Windows, no mesmo computador. Em Linux/macOS o arquivo fica só com
permissão de leitura para o dono.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

HEADER = b"FFDPAPI1\n"


def is_protected(data: bytes) -> bool:
    return data.startswith(HEADER)


if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    class _Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    _crypt32 = ctypes.windll.crypt32
    _kernel32 = ctypes.windll.kernel32
    _kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    _kernel32.LocalFree.restype = ctypes.c_void_p
    _UI_FORBIDDEN = 0x01

    def _call(fn, data: bytes) -> bytes:
        buf = ctypes.create_string_buffer(data, len(data))
        blob_in = _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
        blob_out = _Blob()
        if not fn(ctypes.byref(blob_in), None, None, None, None, _UI_FORBIDDEN, ctypes.byref(blob_out)):
            raise ctypes.WinError()
        try:
            return ctypes.string_at(blob_out.pbData, blob_out.cbData)
        finally:
            _kernel32.LocalFree(ctypes.cast(blob_out.pbData, ctypes.c_void_p))

    def _protect(data: bytes) -> bytes:
        return _call(_crypt32.CryptProtectData, data)

    def _unprotect(data: bytes) -> bytes:
        return _call(_crypt32.CryptUnprotectData, data)
else:
    def _protect(data: bytes) -> bytes:
        return data

    def _unprotect(data: bytes) -> bytes:
        return data


def needs_upgrade(data: bytes) -> bool:
    """Token antigo em texto puro num Windows: deve ser regravado protegido."""
    return sys.platform == "win32" and not is_protected(data)


def protect(data: bytes) -> bytes:
    if sys.platform != "win32":
        return data  # protegido pela permissão do arquivo (write_private)
    return HEADER + _protect(data)


def unprotect(data: bytes) -> bytes:
    if is_protected(data):
        return _unprotect(data[len(HEADER):])
    return data  # texto puro (versões antigas ou Linux/macOS)


def write_private(path: Path, data: bytes) -> None:
    tmp = Path(str(path) + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)
    os.replace(tmp, path)

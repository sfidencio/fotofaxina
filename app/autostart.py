"""Iniciar junto com o Windows (chave Run do usuário)."""
from __future__ import annotations

import sys
from pathlib import Path

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE = "FotoFaxina"


def supported() -> bool:
    return sys.platform == "win32"


def command() -> str:
    """Comando que o Windows roda ao iniciar: o Python que veio no pacote (sem janela preta) + main.py."""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --minimizado'
    exe = Path(sys.executable)
    quiet = exe.with_name("pythonw.exe")
    main = Path(__file__).resolve().parent.parent / "main.py"
    return f'"{quiet if quiet.exists() else exe}" "{main}" --minimizado'


def is_enabled() -> bool:
    if not supported():
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, VALUE)
            return True
    except OSError:
        return False


def set_enabled(enabled: bool) -> None:
    if not supported():
        return
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if enabled:
            winreg.SetValueEx(k, VALUE, 0, winreg.REG_SZ, command())
        else:
            try:
                winreg.DeleteValue(k, VALUE)
            except OSError:
                pass

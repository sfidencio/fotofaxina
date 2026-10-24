"""Organizador de Fotos → Google Fotos.

Uso:
    python main.py                 # abre a janela
    python main.py --minimizado    # inicia só na bandeja (para iniciar com o sistema)
    python main.py --cli PASTA     # analisa uma pasta sem interface (útil para testar)
"""
import sys


def run_cli(folder: str) -> None:
    from app import pipeline
    from app.config import Config

    cfg = Config.load()

    def progress(stage, done, total, msg=""):
        if total:
            print(f"\r{stage}: {done}/{total} {msg[:40]:<40}", end="", flush=True)

    res = pipeline.processar(folder, cfg, progress=progress, log=lambda t: print(f"\n{t}"))
    print("\nResumo:", res)
    if "--enviar" in sys.argv:
        print(pipeline.enviar(cfg, progress=progress, log=lambda t: print(f"\n{t}")))


def main() -> None:
    if "--cli" in sys.argv:
        run_cli(sys.argv[sys.argv.index("--cli") + 1])
        return

    from PySide6.QtWidgets import QApplication

    from app.config import Config
    from app.gui.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("Organizador de Fotos")
    app.setQuitOnLastWindowClosed(False)
    win = MainWindow(Config.load())
    if "--minimizado" not in sys.argv:
        win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

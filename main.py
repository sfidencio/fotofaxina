"""FotoFaxina — fotos do HD organizadas no Google Fotos.

Uso:
    python main.py                 # abre a janela
    python main.py --minimizado    # inicia só na bandeja (para iniciar com o sistema)
    python main.py --cli PASTA     # analisa uma pasta sem interface (útil para testar)
"""
import sys


def run_cli(folder: str) -> None:
    if sys.stdout is None:  # executável sem console (Windows): grava a saída num arquivo
        from app.config import APP_DIR

        APP_DIR.mkdir(parents=True, exist_ok=True)
        sys.stdout = sys.stderr = open(APP_DIR / "cli.log", "w", encoding="utf-8")
    from app import pipeline
    from app.config import Config
    from app.i18n import set_language

    cfg = Config.load()
    set_language(cfg.language)

    def progress(stage, done, total, msg=""):
        if total:
            print(f"\r{stage}: {done}/{total} {msg[:40]:<40}", end="", flush=True)

    res = pipeline.processar(folder, cfg, progress=progress, log=lambda t: print(f"\n{t}"))
    print("\nResumo:", res)
    if "--enviar" in sys.argv:
        print(pipeline.enviar(cfg, progress=progress, log=lambda t: print(f"\n{t}")))


def install_excepthook() -> None:
    """Erros não tratados (num botão, numa thread) vão para o fotofaxina.log em vez de sumir —
    o executável do Windows não tem console."""
    import logging
    import threading
    import traceback

    def hook(exc_type, exc, tb):
        logging.error("Erro não tratado:\n%s", "".join(traceback.format_exception(exc_type, exc, tb)))
        if sys.__stderr__ is not None:
            sys.__excepthook__(exc_type, exc, tb)

    sys.excepthook = hook
    threading.excepthook = lambda a: hook(a.exc_type, a.exc_value, a.exc_traceback)


def main() -> None:
    if "--baixar-ia" in sys.argv:
        from app import model_download

        model_download.download_model(log=print)
        return
    if "--cli" in sys.argv:
        i = sys.argv.index("--cli") + 1
        if i >= len(sys.argv):
            print("Uso: python main.py --cli PASTA [--enviar]")
            return
        run_cli(sys.argv[i])
        return

    from PySide6.QtCore import QLockFile
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication, QMessageBox

    from PySide6.QtCore import QLibraryInfo, QLocale, QTranslator

    from app.config import APP_DIR, APP_NAME, Config, resource
    from app.i18n import _, set_language

    cfg = Config.load()
    lang = set_language(cfg.language)
    from app.gui.main_window import MainWindow  # também configura o fotofaxina.log

    install_excepthook()

    app = QApplication(sys.argv)
    # botões padrão do Qt (Sim/Não, Cancelar...) no idioma escolhido
    qt_tr = QTranslator()
    if qt_tr.load(QLocale("pt_BR" if lang == "pt" else "en_US"), "qtbase", "_",
                  QLibraryInfo.path(QLibraryInfo.TranslationsPath)):
        app.installTranslator(qt_tr)
    app.setApplicationName(APP_NAME)
    app.setQuitOnLastWindowClosed(False)
    app.setWindowIcon(QIcon(str(resource("assets/icon-256.png"))))

    # só uma cópia aberta (o Windows pode iniciar uma e o usuário abrir outra)
    APP_DIR.mkdir(parents=True, exist_ok=True)
    lock = QLockFile(str(APP_DIR / "fotofaxina.lock"))
    if not lock.tryLock(200):
        if "--minimizado" not in sys.argv:
            QMessageBox.information(None, APP_NAME, _("O FotoFaxina já está aberto.\n"
                                                      "Procure o ícone perto do relógio do Windows."))
        return

    win = MainWindow(cfg)
    if "--minimizado" not in sys.argv:
        win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

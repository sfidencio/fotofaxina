"""Aba/módulo da lixeira: lê .Trash-UID (info/files), restaura ao lugar original sem sobrescrever e
nunca apaga nada da lixeira.

    python tests/test_lixeira.py
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = Path(tempfile.mkdtemp(prefix="fotofaxina-lixeira-"))
os.environ["FOTOFAXINA_DIR"] = str(TMP / "dados")
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PIL import Image  # noqa: E402


def novo_hd():
    hd = TMP / "HD"
    t = hd / ".Trash-1000"
    (t / "files").mkdir(parents=True)
    (t / "info").mkdir()
    return hd, t


def jogar(t, nome, rel, data="2026-11-18T14:08:56", conteudo=b"x"):
    (t / "files" / nome).write_bytes(conteudo)
    (t / "info" / (nome + ".trashinfo")).write_text(
        f"[Trash Info]\nPath={quote(rel)}\nDeletionDate={data}\n", encoding="utf-8")


def main():
    from app import trash

    hd, t = novo_hd()
    Image.new("RGB", (40, 30), "red").save(t / "files" / "a.jpg")
    (t / "info" / "a.jpg.trashinfo").write_text(
        f"[Trash Info]\nPath={quote('Fotos 2020/Viagem/a.jpg')}\nDeletionDate=2026-11-18T14:08:56\n", encoding="utf-8")
    jogar(t, "b.png", "Fotos 2020/b.png", data="2026-11-17T10:00:00")
    jogar(t, "existe.jpg", "Fotos 2020/existe.jpg")
    (hd / "Fotos 2020").mkdir(parents=True, exist_ok=True)
    (hd / "Fotos 2020" / "existe.jpg").write_bytes(b"ja estava aqui")
    jogar(t, "fuga.jpg", "../fora.jpg")  # tentativa de sair da raiz do HD
    (t / "files" / "pasta").mkdir()
    (t / "files" / "pasta" / "x.txt").write_text("x")
    (t / "info" / "pasta.trashinfo").write_text("[Trash Info]\nPath=Docs/pasta\nDeletionDate=2026-11-18T09:00:00\n")
    (t / "info" / "sem_arquivo.jpg.trashinfo").write_text("[Trash Info]\nPath=z.jpg\nDeletionDate=2026-11-18T09:00:00\n")

    tr = {"dir": t, "topdir": hd, "label": "HD"}
    itens = trash.list_items(tr)
    nomes = {i["name"]: i for i in itens}
    assert set(nomes) == {"a.jpg", "b.png", "existe.jpg", "fuga.jpg", "pasta"}, set(nomes)  # sem o item sem arquivo
    assert nomes["a.jpg"]["orig"] == str(hd / "Fotos 2020" / "Viagem" / "a.jpg")
    assert nomes["a.jpg"]["media"] and not nomes["pasta"]["media"] and nomes["pasta"]["is_dir"]

    antes = sorted(os.listdir(t / "files"))
    res = trash.restore(tr, itens)
    assert {i["name"] for i in res["restaurados"]} == {"a.jpg", "b.png", "pasta"}, res
    assert len(res["existentes"]) == 1 and len(res["falhas"]) == 1, res
    assert (hd / "Fotos 2020" / "Viagem" / "a.jpg").exists() and (hd / "Docs" / "pasta" / "x.txt").exists()
    assert (hd / "Fotos 2020" / "existe.jpg").read_bytes() == b"ja estava aqui", "não pode sobrescrever"
    assert not (TMP / "fora.jpg").exists(), "não pode sair da raiz do HD"
    # só o que foi restaurado saiu da lixeira; o resto continua lá
    assert sorted(os.listdir(t / "files")) == sorted(set(antes) - {"a.jpg", "b.png", "pasta"})
    assert not (t / "info" / "a.jpg.trashinfo").exists() and (t / "info" / "existe.jpg.trashinfo").exists()

    # a aba (sem tela): carrega, filtra e restaura
    from PySide6.QtWidgets import QApplication, QMessageBox
    app = QApplication([])
    from app.gui import trash_tab

    hd2, t2 = novo_hd() if False else (TMP / "HD2", TMP / "HD2" / ".Trash-1000")
    (t2 / "files").mkdir(parents=True)
    (t2 / "info").mkdir()
    Image.new("RGB", (40, 30), "blue").save(t2 / "files" / "c.jpg")
    (t2 / "info" / "c.jpg.trashinfo").write_text("[Trash Info]\nPath=Antigas/c.jpg\nDeletionDate=2026-11-16T08:00:00\n")
    jogar(t2, "d.txt", "Antigas/d.txt", data="2026-11-16T08:00:00")
    trash.find_trashes = lambda: [{"dir": t2, "topdir": hd2, "label": "HD2"}]
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
    QMessageBox.information = staticmethod(lambda *a, **k: None)

    tab = trash_tab.LixeiraTab()
    tab.reload()
    import time

    for _ in range(250):  # a leitura roda em outra thread
        app.processEvents()
        if tab.model.items:
            break
        time.sleep(0.02)
    assert len(tab.model.items) == 2
    assert tab.proxy.rowCount() == 1, "o filtro 'só fotos e vídeos' esconde o .txt"
    tab.only_media.setChecked(False)
    assert tab.proxy.rowCount() == 2
    tab.search.setText("c.jpg")
    assert tab.proxy.rowCount() == 1
    tab.table.selectRow(0)
    app.processEvents()
    assert tab.preview.pixmap() is not None and not tab.preview.pixmap().isNull(), "prévia da imagem"
    tab._restore_selected()
    assert (hd2 / "Antigas" / "c.jpg").exists() and not (t2 / "files" / "c.jpg").exists()
    assert (t2 / "files" / "d.txt").exists()
    print("OK: lixeira lida, restauração sem sobrescrever e sem sair da raiz; nada é apagado da lixeira.")


if __name__ == "__main__":
    try:
        main()
    finally:
        shutil.rmtree(TMP, ignore_errors=True)

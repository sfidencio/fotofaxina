"""Configuração e caminhos do aplicativo."""
from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

APP_NAME = "FotoFaxina"
APP_DIR = Path(
    os.environ.get("FOTOFAXINA_DIR") or os.environ.get("ORGANIZADOR_FOTOS_DIR") or Path.home() / ".fotofaxina"
)
# pasta dos arquivos do programa (dentro do .exe gerado pelo PyInstaller ou na raiz do projeto)
BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))


def resource(rel: str) -> Path:
    return BUNDLE_DIR / rel


DB_PATH = APP_DIR / "biblioteca.sqlite"
TOKEN_PATH = APP_DIR / "token.json"
CLIENT_SECRET_PATH = APP_DIR / "client_secret.json"
THUMBS_DIR = APP_DIR / "miniaturas"
CONFIG_PATH = APP_DIR / "config.json"
LOG_PATH = APP_DIR / "fotofaxina.log"

# chave -> rótulo exibido
CATEGORIES: dict[str, str] = {
    "foto": "Foto pessoal",
    "paisagem": "Paisagem / lugares",
    "video": "Vídeo",
    "meme": "Meme / figurinha",
    "print": "Print de tela",
    "documento": "Documento / comprovante",
    "outro": "Outro",
}

SOURCES: dict[str, str] = {
    "camera": "Câmera",
    "whatsapp": "WhatsApp",
    "print": "Print",
    "desconhecida": "Desconhecida",
}


@dataclass
class Config:
    upload_categories: list = field(default_factory=lambda: ["foto", "paisagem", "video"])
    include_whatsapp: bool = True          # envia fotos pessoais recebidas no WhatsApp
    use_ai: bool = True                    # IA leve (CLIP em ONNX) para WhatsApp/origem desconhecida
    ai_on_camera: bool = False             # também passa fotos de câmera pela IA (mais lento)
    language: str = "auto"                 # auto | pt | en
    ai_min_confidence: float = 0.45        # abaixo disso o item aparece como "baixa confiança"
    album_mode: str = "evento"             # evento | mes | ano
    year_album_title: str = ""             # nome do álbum no modo "ano" ("" = padrão do idioma)
    event_gap_hours: float = 24.0          # intervalo sem fotos que separa dois eventos
    min_event_size: int = 8                # eventos menores vão para o álbum do mês
    reuse_same_name: bool = True           # usa álbum do Google (criado pelo app) com o mesmo nome
    auto_scan_on_drive: bool = True        # analisa sozinho quando um HD é plugado
    auto_upload: bool = False              # envia sozinho após a análise (sem revisão)
    welcome_done: bool = False             # já mostrou a tela de boas-vindas
    min_image_side: int = 200              # imagens menores que isso viram "outro"
    ignore_dirs: list = field(default_factory=lambda: [
        "$RECYCLE.BIN", "System Volume Information", "RECYCLER", ".Trash", ".Trashes",
        "node_modules", ".git", "AppData", "Windows", "Program Files", "Program Files (x86)",
        ".thumbnails", "Thumbs", "cache", "Cache",
    ])

    @classmethod
    def load(cls) -> "Config":
        APP_DIR.mkdir(parents=True, exist_ok=True)
        if CONFIG_PATH.exists():
            try:
                data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
                known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
                return cls(**known)
            except (json.JSONDecodeError, TypeError):
                pass
        cfg = cls()
        cfg.save()
        return cfg

    def save(self) -> None:
        APP_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding="utf-8")


def wants_upload(row, cfg: Config) -> bool:
    """Decide se uma foto (linha do banco) deve ir para o Google Fotos."""
    if row["duplicate_of"] is not None:
        return False
    decision = row["decision"]
    if decision == "upload":
        return True
    if decision == "skip":
        return False
    if row["source"] == "whatsapp" and not cfg.include_whatsapp:
        return False
    return row["category"] in cfg.upload_categories

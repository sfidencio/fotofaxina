#!/usr/bin/env bash
# Abre o FotoFaxina no Linux/macOS. Cria o ambiente (.venv) e instala/atualiza as dependências
# a cada vez que requirements.txt muda, então um módulo novo nunca fica faltando.
set -e
cd "$(dirname "$0")"
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv 2>/dev/null || { command -v uv >/dev/null && uv venv .venv; }
fi
PY=.venv/bin/python
STAMP=.venv/.requirements.sha
NOW=$(sha256sum requirements.txt 2>/dev/null | cut -d' ' -f1 || shasum -a 256 requirements.txt | cut -d' ' -f1)
if [ "$(cat "$STAMP" 2>/dev/null)" != "$NOW" ]; then
  if "$PY" -m pip --version >/dev/null 2>&1; then
    "$PY" -m pip install -q -r requirements.txt
  else
    uv pip install -q --python "$PY" -r requirements.txt
  fi
  echo "$NOW" > "$STAMP"
fi
exec "$PY" main.py "$@"

# FotoFaxina

Plugue o HD e deixe trabalhar.

App desktop (Python + PySide6) que lê fotos de um HD, separa o que é foto de verdade do que é
meme, print, figurinha e documento, remove duplicatas, monta álbuns por evento/mês e envia
para o Google Fotos. Funciona em Windows, Linux e macOS.

## Como funciona

1. **Plugou o HD** → o app (rodando na bandeja) detecta e começa a análise sozinho.
2. **Varredura**: lê cada arquivo, calcula hash (duplicata exata) e hash perceptual
   (a mesma foto reenviada/recomprimida pelo WhatsApp), lê data e câmera do EXIF.
3. **Classificação**:
   - Regras rápidas: nome `IMG-20240101-WA0001.jpg` = WhatsApp, `Screenshot_…` = print,
     `.webp` do WhatsApp = figurinha, imagens minúsculas = ícone/lixo.
   - IA local (CLIP, opcional, offline e gratuita) para o restante: foto pessoal, paisagem,
     meme, print, documento.
4. **Álbuns** — escolha em Configurações → “Organizar álbuns”:
   - **Por evento** (padrão): fotos próximas no tempo (sem intervalo maior que 24h e com 8+
     fotos) viram “Evento 24 a 26/12/2023”; o resto vai para o álbum do mês.
   - **Por mês**: “Dezembro de 2023”.
   - **Por ano**: “Fotos 2023” (nome configurável). Ideal para HDs já organizados em pastas
     `2020/`, `2021/`… A data real da foto (EXIF ou nome do arquivo) manda; se a foto não
     tiver data, vale o ano da pasta (`2021/Celular da esposa/foto.jpg` → 2021). Sem nenhum
     dos dois, vai para “Fotos sem data”.
   Renomeie à vontade na aba **Álbuns** antes de enviar.
5. **Revisão** (opcional): grade de miniaturas com filtros. Selecione e marque
   “Enviar” / “Não enviar” / “Mudar categoria”.
6. **Envio**: cria os álbuns e sobe as fotos em lotes de 50. Tudo fica registrado em um banco
   SQLite local; dá para parar, desligar o PC, plugar o HD em outra letra e continuar
   de onde parou, sem enviar nada duas vezes.

## Instalação

Requer Python 3.10+.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate   |   Linux/Mac: source .venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-ia.txt     # opcional: IA local (~2 GB com PyTorch)
python main.py
```

No primeiro uso da IA o modelo (~600 MB) é baixado automaticamente e fica em cache.
Com placa NVIDIA, instale o PyTorch com CUDA (https://pytorch.org/get-started/locally/)
antes do `requirements-ia.txt` — fica muitas vezes mais rápido.

## Credencial do Google (uma vez só, ~5 minutos)

O Google exige que cada app tenha uma credencial própria:

1. Acesse https://console.cloud.google.com/ e crie um projeto (ex.: “Organizador Fotos”).
2. **APIs e serviços → Biblioteca** → procure **Photos Library API** → **Ativar**.
3. **APIs e serviços → Tela de permissão OAuth** (Google Auth Platform):
   tipo **Externo**, preencha nome e e-mail, e em **Público-alvo / Usuários de teste**
   adicione o seu próprio Gmail.
4. **Clientes / Credenciais → Criar credenciais → ID do cliente OAuth** → tipo
   **App para computador** → baixe o JSON.
5. No app: **Configurações → Selecionar client_secret.json** → **Conectar conta Google**.
   O navegador abre, você autoriza e pronto.

> Enquanto o app estiver em modo “Teste” no Google Cloud, o login expira a cada 7 dias.
> Quando expirar, é só clicar em **Conectar conta Google** de novo.

## Limitações da API do Google Fotos (importantes)

- Desde 31/03/2025 a API **só enxerga o que o próprio app enviou**. O app não consegue ver
  sua biblioteca atual, então a checagem de duplicatas vale para tudo que passou por ele,
  não para fotos que você subiu antes manualmente.
- Fotos só podem ser colocadas em **álbuns criados pelo app**. Seus álbuns antigos não mudam.
- Uploads pela API ficam em **qualidade original e contam no armazenamento** da sua conta
  Google. Confira o espaço livre antes de subir um HD inteiro.
- Existe um **limite diário de requisições**. Se for atingido, o app avisa e para;
  no dia seguinte, clique em Enviar e ele continua de onde parou.

## Uso no dia a dia

- **Iniciar com o sistema, minimizado na bandeja**: `python main.py --minimizado`
  - Windows: crie um atalho para `iniciar.bat` em `shell:startup` (Win+R).
  - Linux: adicione aos “Aplicativos de inicialização”.
  - macOS: Ajustes → Geral → Itens de Início.
- Fechar a janela só esconde o app na bandeja. Para sair: ícone da bandeja → **Sair**.
- **Primeira vez**: deixe “Enviar automaticamente” desligado, rode uma análise, confira a aba
  Revisão (filtro “Baixa confiança”) e ajuste. Quando confiar no resultado, ligue o envio
  automático e o fluxo vira só “plugar o HD”.

## Linha de comando (sem janela)

```bash
python main.py --cli /caminho/do/hd            # só analisa
python main.py --cli /caminho/do/hd --enviar   # analisa e envia
```

## Onde ficam os dados

`~/.organizador_fotos/` (no Windows `C:\Users\<você>\.organizador_fotos\`):
`biblioteca.sqlite` (estado de cada arquivo), `config.json`, `token.json` (login Google),
`miniaturas/` e `organizador.log`. Apagar essa pasta reinicia tudo do zero
(mas o app não saberá mais o que já foi enviado).

## Estrutura do código

```
main.py                  ponto de entrada (janela, --minimizado, --cli)
app/config.py            configurações, categorias e regra "vai ou não para o Google"
app/db.py                banco SQLite
app/scanner.py           varredura, hashes, EXIF, datas, duplicatas
app/classifier.py        regras + IA CLIP
app/grouper.py           eventos e álbuns por mês
app/google_photos.py     OAuth + upload + álbuns (Photos Library API)
app/pipeline.py          orquestra as etapas (retomável)
app/drive_watcher.py     detecta HD plugado
app/gui/                 janela, abas, tarefas em segundo plano
```

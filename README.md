# FotoFaxina

Plugue o HD e deixe trabalhar.

App desktop (Python + PySide6) que lê fotos de um HD, separa o que é foto de verdade do que é
meme, print, figurinha e documento, remove duplicatas, monta álbuns por evento/mês e envia
para o Google Fotos. Funciona em Windows, Linux e macOS.

## Instalar (usuário final)

1. Vá em **[Releases](https://github.com/sfidencio/fotofaxina/releases/latest)** e baixe
   `FotoFaxina-Setup-x.y.z.exe`.
2. Abra o arquivo. Se aparecer “O Windows protegeu o computador”, clique em
   **Mais informações → Executar assim mesmo** (o instalador não tem assinatura digital paga).
3. Avance até o fim. Não precisa de senha de administrador nem de Python.
4. No primeiro uso o FotoFaxina oferece conectar sua conta Google. Depois é só plugar o HD.

O programa fica perto do relógio do Windows e começa a analisar sozinho quando um HD é plugado.
Para desinstalar: Configurações do Windows → Aplicativos → FotoFaxina.

> O instalador vem sem a IA local (PyTorch tem ~2 GB). A separação usa as regras e as
> duplicatas; imagens do WhatsApp sem classificação ficam para você decidir na aba Revisão.

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

## Credencial do Google (uma vez só, ~10 minutos)

O Google exige que cada programa tenha uma credencial própria. Resumo:

1. Abra o Google Cloud já em português: https://console.cloud.google.com/?hl=pt-BR
2. Crie um projeto chamado `FotoFaxina`.
3. Ative a **Photos Library API**.
4. Em **Google Auth Platform** → **Primeiros passos**: nome do app, seu e-mail, público
   **Externo**.
5. Em **Público-alvo** → **Usuários de teste**: adicione o seu Gmail (e de quem mais for usar).
6. Em **Clientes** → **Criar cliente** → tipo **App para computador** → baixe o JSON.
7. No FotoFaxina: **Configurações** → **Selecionar client_secret.json** →
   **Conectar conta Google**. Na tela “O Google não verificou este app”, clique em **Continuar**.

👉 **Passo a passo completo, com os nomes dos botões em português e em inglês e solução dos
erros mais comuns: [docs/CONFIGURAR-GOOGLE.md](docs/CONFIGURAR-GOOGLE.md)**

> Enquanto o app estiver em modo de teste no Google Cloud, o login expira a cada 7 dias.
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

## Compartilhar álbuns e garantir acesso da família

Desde 31/03/2025 a API do Google não permite mais compartilhar álbuns por programa. Por isso o
FotoFaxina faz o caminho mais curto: na aba **Álbuns**, selecione um álbum já enviado e clique em
**Abrir no Google Fotos para compartilhar** → no navegador, **Compartilhar** → digite os e-mails.
Com álbuns por ano, são poucos cliques por ano; fotos enviadas depois para o mesmo álbum
aparecem automaticamente para quem já foi adicionado.

Para que ninguém fique dependente da sua conta, configure também no Google (uma vez só):
- **Gerenciador de contas inativas** (myaccount.google.com → Dados e privacidade): até 10 pessoas
  recebem o link para baixar suas fotos se a conta ficar inativa pelo prazo que você escolher.
- **Compartilhamento com parceiro** no app Google Fotos: a outra pessoa recebe tudo
  automaticamente e pode salvar uma cópia na conta dela.

## Uso no dia a dia

- **Iniciar com o sistema, minimizado na bandeja**: `python main.py --minimizado`
  - Windows: crie um atalho para `iniciar.bat` em `shell:startup` (Win+R).
  - Linux: adicione aos “Aplicativos de inicialização”.
  - macOS: Ajustes → Geral → Itens de Início.
- Fechar a janela só esconde o app na bandeja. Para sair: ícone da bandeja → **Sair**.
- **Primeira vez**: deixe “Enviar automaticamente” desligado, rode uma análise, confira a aba
  Revisão (filtro “Baixa confiança”) e ajuste. Quando confiar no resultado, ligue o envio
  automático e o fluxo vira só “plugar o HD”.

## Gerar uma nova versão do instalador (desenvolvedor)

O GitHub Actions (`.github/workflows/release.yml`) monta tudo sozinho num Windows na nuvem:
PyInstaller → instalador Inno Setup → página de Releases.

```bash
git tag v1.0.1
git push origin v1.0.1
```

Em ~10 minutos o `FotoFaxina-Setup-1.0.1.exe` aparece em Releases. Também dá para rodar à mão
em **Actions → Instalador Windows → Run workflow** (o arquivo fica em “Artifacts”).

**Credencial embutida (recomendado):** para o usuário final não precisar do Google Cloud,
cadastre o conteúdo do seu `client_secret.json` em **Settings → Secrets and variables →
Actions → New repository secret** com o nome `GOOGLE_CLIENT_SECRET_JSON`
(detalhes no final de [docs/CONFIGURAR-GOOGLE.md](docs/CONFIGURAR-GOOGLE.md)). O build coloca a
credencial dentro do instalador; ela nunca vai para o código. Lembre de adicionar o Gmail de
quem vai usar como “usuário de teste” na tela de permissão OAuth do Google Cloud.

Build local no Windows: `pip install pyinstaller` → `pyinstaller packaging/fotofaxina.spec`
→ `iscc /DAppVersion=1.0.0 packaging\installer.iss`.

## Linha de comando (sem janela)

```bash
python main.py --cli /caminho/do/hd            # só analisa
python main.py --cli /caminho/do/hd --enviar   # analisa e envia
```

## Onde ficam os dados

`~/.fotofaxina/` (no Windows `C:\Users\<você>\.fotofaxina\`):
`biblioteca.sqlite` (estado de cada arquivo), `config.json`, `token.json` (login Google),
`miniaturas/` e `fotofaxina.log`. Apagar essa pasta reinicia tudo do zero
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
app/autostart.py         iniciar com o Windows
app/phash.py             hash perceptual (duplicatas parecidas)
packaging/               PyInstaller (.spec) e instalador (Inno Setup)
.github/workflows/       build automático do instalador
app/gui/                 janela, abas, tarefas em segundo plano
```

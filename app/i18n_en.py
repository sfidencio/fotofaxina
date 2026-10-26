"""English translations. Key = Portuguese source text. Check with: python packaging/check_i18n.py"""

EN: dict[str, str] = {
    # categorias / origens / idioma
    "Foto pessoal": "Personal photo",
    "Paisagem / lugares": "Landscape / places",
    "Vídeo": "Video",
    "Meme / figurinha": "Meme / sticker",
    "Print de tela": "Screenshot",
    "Documento / comprovante": "Document / receipt",
    "Outro": "Other",
    "Câmera": "Camera",
    "WhatsApp": "WhatsApp",
    "Print": "Screenshot",
    "Desconhecida": "Unknown",
    "Automático (idioma do sistema)": "Automatic (system language)",

    # varredura / classificação / álbuns
    "Listando arquivos": "Listing files",
    "{n} fotos/vídeos encontrados em {pasta}": "{n} photos/videos found in {pasta}",
    "Lendo arquivos": "Reading files",
    "{novos} arquivos novos; {dup} duplicatas no total (somando todas as pastas já analisadas)":
        "{novos} new files; {dup} duplicates in total (across all folders analyzed so far)",
    "Nesta pasta: {total} arquivos — {novas} para enviar, {google} já estão no Google Fotos, {rep} repetidos de fotos que ainda vão ser enviadas, {fora} fora dos critérios (memes, prints…).":
        "In this folder: {total} files — {novas} to upload, {google} already in Google Photos, {rep} repeats of "
        "photos still to be uploaded, {fora} outside the criteria (memes, screenshots…).",
    "Não consegui ler {arquivo}: {erro}": "Could not read {arquivo}: {erro}",
    "Classificando": "Classifying",
    "Classificando {n} arquivos...": "Classifying {n} files...",
    "regras": "rules",
    "IA": "AI",
    "Modelo de IA não encontrado. Usando só as regras.": "AI model not found. Using rules only.",
    "IA leve carregada.": "Lightweight AI loaded.",
    "IA indisponível ({erro}). Usando só as regras.": "AI unavailable ({erro}). Using rules only.",
    "Falha na IA: {erro}": "AI failure: {erro}",
    "Fotos {ano}": "Photos {ano}",
    "sem data": "without date",
    "{n} itens organizados em {albuns} álbuns": "{n} items organized into {albuns} albums",

    # envio / Google
    "Conta Google conectada.": "Google account connected.",
    "{n} itens para enviar": "{n} items to upload",
    "Enviando": "Uploading",
    "Envio concluído: {ok} enviados, {err} com erro": "Upload finished: {ok} uploaded, {err} failed",
    "Álbuns novos: {lista}. Para compartilhar, use a aba Álbuns → “Abrir no Google Fotos para compartilhar”.":
        "New albums: {lista}. To share them, go to the Albums tab → “Open in Google Photos to share”.",
    "Álbum renomeado: {titulo}": "Album renamed: {titulo}",
    "Não consegui renomear “{titulo}”: {erro}": "Could not rename “{titulo}”: {erro}",
    "sem resposta do Google": "no response from Google",
    "Álbum criado: {titulo}": "Album created: {titulo}",
    "Conta Google não conectada.": "Google account not connected.",
    "Conecte sua conta Google na aba Configurações.": "Connect your Google account in the Settings tab.",
    "Selecione o arquivo client_secret.json na aba Configurações.":
        "Select the client_secret.json file in the Settings tab.",
    "Abrindo o navegador para login no Google…": "Opening the browser to sign in to Google…",
    "Pronto! Pode fechar esta aba e voltar ao FotoFaxina.": "Done! You can close this tab and go back to FotoFaxina.",
    "Falha após várias tentativas ({codigo}): {texto}": "Failed after several attempts ({codigo}): {texto}",
    "Limite diário da API do Google Fotos atingido. Continue amanhã — o que já foi enviado fica registrado.":
        "Google Photos API daily limit reached. Continue tomorrow — everything already uploaded is recorded.",

    # janela principal
    "fotos do HD para o Google Fotos": "photos from your drive to Google Photos",
    "Início": "Home",
    "Revisão": "Review",
    "Álbuns": "Albums",
    "Configurações": "Settings",
    "Abrir": "Open",
    "Parar tarefa": "Stop task",
    "Sair": "Quit",
    "Pronto. Plugue um HD ou escolha uma pasta.": "Ready. Plug in a drive or choose a folder.",
    "<h3>Bem-vindo ao FotoFaxina!</h3><p>1. Conecte sua conta do Google Fotos.<br>2. Plugue o HD (ou escolha uma pasta) — a análise começa sozinha.<br>3. Confira o resultado e clique em <b>Enviar para o Google Fotos</b>.</p><p>O programa fica perto do relógio do Windows, esperando o HD.</p>":
        "<h3>Welcome to FotoFaxina!</h3><p>1. Connect your Google Photos account.<br>2. Plug in the drive "
        "(or choose a folder) — the analysis starts on its own.<br>3. Check the result and click "
        "<b>Upload to Google Photos</b>.</p><p>The app waits next to the Windows clock for your drive.</p>",
    "<p><b>Conectar a conta Google agora?</b></p>": "<p><b>Connect your Google account now?</b></p>",
    "✔ Conta Google conectada": "✔ Google account connected",
    "✖ Conta Google não conectada (veja Configurações)": "✖ Google account not connected (see Settings)",
    "Origem: <b>{nome}</b> — {caminho}": "Source: <b>{nome}</b> — {caminho}",
    "Aguarde": "Please wait",
    "Já existe uma tarefa em andamento.": "A task is already running.",
    "{n} itens prontos para enviar ({dup} duplicados ignorados).": "{n} items ready to upload ({dup} duplicates skipped).",
    "Análise concluída.": "Analysis finished.",
    "Análise concluída": "Analysis finished",
    "Revise na aba Revisão/Álbuns e clique em “Enviar para o Google Fotos”.":
        "Check the Review/Albums tabs and click “Upload to Google Photos”.",
    "Análise interrompida. Clique em Analisar para continuar de onde parou.":
        "Analysis stopped. Click Analyze to continue where it left off.",
    "{ok} enviados, {err} com erro.": "{ok} uploaded, {err} failed.",
    "Envio concluído": "Upload finished",
    "Google Fotos": "Google Photos",
    "Conta conectada com sucesso!": "Account connected successfully!",
    "Erro em {tarefa}: {erro}": "Error in {tarefa}: {erro}",
    "Erro": "Error",
    "Conecte sua conta Google na aba Configurações primeiro.": "Connect your Google account in the Settings tab first.",
    "Parando após o item atual…": "Stopping after the current item…",
    "{n} itens com erro voltaram para a fila.": "{n} failed items were put back in the queue.",
    "Escolha a pasta ou o HD com as fotos": "Choose the folder or drive with your photos",
    "HD detectado: {nome}": "Drive detected: {nome}",
    "HD detectado": "Drive detected",
    "{nome} — será analisado quando a tarefa atual terminar.": "{nome} — will be analyzed when the current task ends.",
    "Analisando {nome}…": "Analyzing {nome}…",
    "Analisar as fotos de {nome}?": "Analyze the photos on {nome}?",
    "Continua rodando aqui, perto do relógio. Plugue um HD quando quiser.":
        "Still running here, next to the clock. Plug in a drive whenever you like.",
    "O FotoFaxina já está aberto.\nProcure o ícone perto do relógio do Windows.":
        "FotoFaxina is already open.\nLook for its icon next to the Windows clock.",

    # aba Início
    "Faxina nas fotos do HD: separa, remove duplicadas e envia para o Google Fotos.":
        "Spring cleaning for your photo drive: sorts, removes duplicates and uploads to Google Photos.",
    "Nenhuma pasta selecionada. Plugue um HD ou escolha uma pasta.": "No folder selected. Plug in a drive or choose a folder.",
    "Escolher pasta / HD…": "Choose folder / drive…",
    "1. Analisar": "1. Analyze",
    "2. Enviar para o Google Fotos": "2. Upload to Google Photos",
    "Parar": "Stop",
    "Tentar erros de novo": "Retry failed items",
    "Parado": "Idle",
    "Registro:": "Log:",
    "Arquivos: <b>{total}</b> · Duplicados: <b>{dup}</b> · A enviar: <b>{todo}</b> · Já enviados: <b>{done}</b> · Erros: <b>{err}</b>":
        "Files: <b>{total}</b> · Duplicates: <b>{dup}</b> · To upload: <b>{todo}</b> · Uploaded: <b>{done}</b> · Errors: <b>{err}</b>",

    # aba Revisão
    "Todas as categorias": "All categories",
    "Duplicados": "Duplicates",
    "Vão para o Google": "Going to Google",
    "Não vão": "Not going",
    "Baixa confiança": "Low confidence",
    "Já enviadas": "Already uploaded",
    "Com erro": "With errors",
    "Tudo": "Everything",
    "Categoria:": "Category:",
    "Situação:": "Status:",
    "Carregar mais": "Load more",
    "Enviar selecionadas": "Upload selected",
    "Não enviar": "Don't upload",
    "Voltar ao automático": "Back to automatic",
    "Mudar categoria": "Change category",
    "Dica: Ctrl/Shift para selecionar várias. Duplo clique abre o arquivo.":
        "Tip: Ctrl/Shift to select several. Double-click opens the file.",
    "Origem: {origem}": "Source: {origem}",
    "Data: {data} ({fonte})": "Date: {data} ({fonte})",
    "Câmera: {camera}": "Camera: {camera}",
    "Erro: {erro}": "Error: {erro}",
    "Duplicata de: {arquivo}": "Duplicate of: {arquivo}",
    "(já está no Google Fotos)": "(already in Google Photos)",
    "{n} de {total}": "{n} of {total}",

    # aba Álbuns
    "Título (clique duplo para renomear)": "Title (double-click to rename)",
    "Período": "Period",
    "Itens": "Items",
    "No Google": "On Google",
    "Sim": "Yes",
    "Ainda não": "Not yet",
    "Abrir no Google Fotos para compartilhar": "Open in Google Photos to share",
    "Reagrupar (após mudar configurações)": "Regroup (after changing settings)",
    "Para compartilhar: selecione um álbum já enviado → “Abrir no Google Fotos para compartilhar” → no navegador, clique em <b>Compartilhar</b> e digite os e-mails. Quem você adicionar recebe as fotos novas que forem para esse álbum depois.":
        "To share: select an album that was already uploaded → “Open in Google Photos to share” → in the "
        "browser, click <b>Share</b> and type the e-mails. People you add also get new photos added to that album later.",
    "Os álbuns são criados no Google Fotos só no envio. Renomeie à vontade antes — ex.: “Evento 24 a 26/12/2023” → “Natal 2023”.":
        "Albums are only created in Google Photos when uploading. Rename them freely before — "
        "e.g. “Event Dec 24 – Dec 26, 2023” → “Christmas 2023”.",
    "Este álbum ainda não foi enviado ao Google Fotos.": "This album has not been uploaded to Google Photos yet.",

    # aba Configurações
    "O que vai para o Google Fotos": "What goes to Google Photos",
    "Incluir fotos pessoais recebidas pelo WhatsApp": "Include personal photos received on WhatsApp",
    "Inteligência artificial (embutida, funciona sem internet)": "Artificial intelligence (built in, works offline)",
    "Usar IA para separar memes, prints e documentos": "Use AI to separate memes, screenshots and documents",
    "Analisar também as fotos da câmera (mais lento)": "Also analyze camera photos (slower)",
    "Confiança mínima da IA:": "AI minimum confidence:",
    "IA pronta: modelo leve embutido, roda no processador, sem placa de vídeo.":
        "AI ready: lightweight built-in model, runs on the CPU, no graphics card needed.",
    "Por evento (fotos próximas no tempo)": "By event (photos close in time)",
    "Por mês": "By month",
    "Por ano": "By year",
    "Use {ano} onde o ano deve aparecer. Ex.: Fotos {ano}": "Use {ano} where the year should go. E.g.: Photos {ano}",
    " horas": " hours",
    " fotos": " photos",
    "Organizar álbuns:": "Organize albums:",
    "Nome do álbum anual:": "Yearly album name:",
    "Novo evento após um intervalo de:": "New event after a gap of:",
    "Tamanho mínimo de um evento:": "Minimum event size:",
    "Automação e idioma": "Automation and language",
    "Analisar automaticamente quando um HD for plugado": "Analyze automatically when a drive is plugged in",
    "Enviar automaticamente após a análise (sem revisar)": "Upload automatically after analysis (no review)",
    "Iniciar junto com o Windows (minimizado, esperando o HD)": "Start with Windows (minimized, waiting for the drive)",
    "Idioma / Language:": "Idioma / Language:",
    "Conta Google": "Google account",
    "Selecionar client_secret.json…": "Select client_secret.json…",
    "Conectar conta Google": "Connect Google account",
    "Desconectar": "Disconnect",
    "Salvar configurações": "Save settings",
    "✔ Conta conectada.": "✔ Account connected.",
    "Falta só clicar em “Conectar conta Google” e autorizar no navegador.":
        "Just click “Connect Google account” and authorize in the browser.",
    "Falta a credencial do Google (uma vez só, ~10 min).": "The Google credential is missing (one time only, ~10 min).",
    "Veja o passo a passo": "See the step-by-step guide",
    "Não consegui alterar a inicialização: {erro}": "Could not change the startup setting: {erro}",
    "Salvo. Use “Reagrupar” na aba Álbuns para aplicar.": "Saved. Use “Regroup” in the Albums tab to apply.",
    "Baixando modelo de IA": "Downloading AI model",
    "Baixando o modelo de IA (~96 MB)…": "Downloading the AI model (~96 MB)…",
    "Download cancelado.": "Download cancelled.",
    "O modelo de IA ainda não está publicado na última versão do FotoFaxina. Tente de novo em alguns minutos.":
        "The AI model is not published in the latest FotoFaxina release yet. Try again in a few minutes.",
    "Arquivo do modelo incompleto: falta {nome}.": "Incomplete model file: {nome} is missing.",
    "Modelo de IA instalado.": "AI model installed.",
    "Baixar modelo de IA (~96 MB)": "Download AI model (~96 MB)",
    "Modelo de IA não encontrado nesta instalação — usando só as regras. Clique abaixo para baixar.":
        "AI model not found in this installation — using rules only. Click below to download it.",
    "Inteligência artificial": "Artificial intelligence",
    "Esquecer esta pasta…": "Forget this folder…",
    "Remove do histórico do FotoFaxina os registros da pasta escolhida (não apaga nenhum arquivo).":
        "Removes the chosen folder's records from FotoFaxina's history (no file is deleted).",
    "Esquecer selecionadas…": "Forget selected…",
    "Remove os itens do histórico do FotoFaxina (não apaga nenhum arquivo).":
        "Removes the items from FotoFaxina's history (no file is deleted).",
    "Esquecer {n} item(ns)?": "Forget {n} item(s)?",
    "Esquecer": "Forget",
    "Histórico do FotoFaxina": "FotoFaxina history",
    "O FotoFaxina guarda o que já analisou e enviou para não repetir. Limpar faz ele começar do zero (os arquivos não são apagados).":
        "FotoFaxina remembers what it already analyzed and uploaded so nothing is repeated. Clearing makes it "
        "start from scratch (files are not deleted).",
    "Limpar todo o histórico…": "Clear all history…",
    "Limpar histórico": "Clear history",
    "{n} registros removidos. Seus arquivos continuam onde estavam.": "{n} records removed. Your files are still where they were.",
    "Não há registros desta pasta no histórico.": "There are no records of this folder in the history.",
    "Esquecer os {n} registros da pasta\n{pasta}?": "Forget the {n} records of the folder\n{pasta}?",
    "{n} registros desta pasta foram esquecidos. Clique em Analisar para começar do zero.":
        "{n} records of this folder were forgotten. Click Analyze to start from scratch.",
    "O álbum “{titulo}” não existe mais no Google Fotos; criando de novo.":
        "The album “{titulo}” no longer exists in Google Photos; creating it again.",
    "Falta o componente que executa a IA. No terminal, rode <b>pip install -r requirements.txt</b> e abra o FotoFaxina de novo.":
        "The component that runs the AI is missing. In a terminal, run <b>pip install -r requirements.txt</b> "
        "and open FotoFaxina again.",
    "Modelo de IA instalado. Na próxima análise ele já será usado.":
        "AI model installed. It will be used in the next analysis.",
    "O novo idioma vale a partir da próxima vez que o FotoFaxina for aberto.":
        "The new language takes effect the next time FotoFaxina is opened.",
    "Não é duplicata": "Not a duplicate",
    "Para fotos parecidas, mas diferentes (sequência, rajada): passam a ser enviadas e não são mais tratadas como cópia.":
        "For photos that look alike but are different (sequence, burst): they will be uploaded and "
        "no longer treated as copies.",
    "{n} item(ns) não serão mais tratados como cópia. Eles são classificados na próxima análise ou no próximo envio.":
        "{n} item(s) will no longer be treated as copies. They are classified in the next analysis "
        "or upload.",
    "Não encontrei a soma de verificação do modelo; conferindo só o conteúdo do arquivo.":
        "Couldn't find the model checksum; checking only the file contents.",
    "O arquivo do modelo chegou corrompido (a soma de verificação não confere). Tente baixar de novo.":
        "The model file arrived corrupted (the checksum doesn't match). Try downloading again.",
    "Soma de verificação do modelo conferida.": "Model checksum verified.",
    "O login no Google expirou (enquanto o app está em modo de teste no Google Cloud, isso acontece a cada 7 dias). Clique em “Conectar conta Google” na aba Configurações.":
        "Your Google sign-in expired (while the app is in testing mode in Google Cloud, this happens "
        "every 7 days). Click “Connect Google account” in the Settings tab.",
    "Sem conexão com o Google Fotos: {erro}": "No connection to Google Photos: {erro}",
    "{n} arquivos já conhecidos em outro caminho (ex.: HD com outra letra); não foi preciso ler de novo.":
        "{n} files already known under another path (e.g. drive with another letter); no need to read them again.",
    "{n} itens são de um HD ou pasta que não está conectado agora; serão enviados quando estiver.":
        "{n} items are on a drive or folder that is not connected now; they will be uploaded when it is.",
    "Falha ao criar {n} itens no Google Fotos: {erro}": "Failed to create {n} items in Google Photos: {erro}",
    "A IA está disponível: reclassificando {n} itens que antes foram decididos sem ela.":
        "The AI is available: reclassifying {n} items that were previously decided without it.",
    "{n} aguardam o HD de origem ser plugado.": "{n} are waiting for their source drive to be plugged in.",
    "Aguarde a tarefa atual terminar.": "Wait for the current task to finish.",
    "{n} arquivos já estavam no Google Fotos e não serão enviados de novo.":
        "{n} files were already in Google Photos and won't be uploaded again.",
    "Os arquivos no seu computador NÃO serão apagados, nem nada no Google Fotos. O FotoFaxina esquece a análise desses arquivos, mas lembra o que já está no Google Fotos: nada é enviado de novo e as fotos novas vão para os mesmos álbuns.":
        "Files on your computer will NOT be deleted, nor anything in Google Photos. FotoFaxina forgets the "
        "analysis of these files but remembers what is already in Google Photos: nothing is uploaded again "
        "and new photos go to the same albums.",
    "Limpar TODO o histórico de análise (todas as pastas)?": "Clear ALL analysis history (all folders)?",
    "Os arquivos no seu computador NÃO serão apagados, nem nada no Google Fotos. O FotoFaxina continua lembrando o que já está no Google Fotos: nada é enviado de novo e as fotos novas vão para os álbuns que já existem (ex.: “Fotos 2023”).":
        "Files on your computer will NOT be deleted, nor anything in Google Photos. FotoFaxina keeps "
        "remembering what is already in Google Photos: nothing is uploaded again and new photos go to the "
        "albums that already exist (e.g. “Photos 2023”).",
    "Esquecer também o que já está no Google Fotos (os próximos envios criam álbuns novos e podem repetir fotos). Use só se trocou de conta Google.":
        "Also forget what is already in Google Photos (next uploads create new albums and may repeat "
        "photos). Only use this if you switched Google accounts.",
}

# Como criar a credencial do Google (passo a passo em português)

🇧🇷 Português · [🇺🇸 English](GOOGLE-SETUP.md)

Leva uns 10 minutos e é feito **uma vez só**. No fim você terá um arquivo `client_secret.json`,
que o FotoFaxina usa para pedir sua permissão de enviar fotos ao Google Fotos.

Os nomes dos botões aparecem assim: **Português** (*English*), porque o Google Cloud às vezes
continua em inglês mesmo depois de trocar o idioma.

---

## 0. Deixar o Google Cloud em português

Abra este link já em português:
**https://console.cloud.google.com/?hl=pt-BR**

Se continuar em inglês: clique no seu avatar (canto superior direito) → **Preferências**
(*Preferences*) → **Idioma** (*Language*) → **Português (Brasil)** → **Salvar** (*Save*).

Na primeira vez o Google pede para aceitar os termos de uso: marque o país **Brasil**, aceite e
continue. **Não precisa cadastrar cartão de crédito** — nada aqui é cobrado.

---

## 1. Criar um projeto

1. No topo da tela, ao lado do logo “Google Cloud”, clique no seletor de projetos
   (pode estar escrito **Selecionar um projeto** / *Select a project*).
2. Clique em **Novo projeto** (*New project*).
3. Nome: `FotoFaxina` → **Criar** (*Create*).
4. Espere uns segundos e confirme que o projeto **FotoFaxina** aparece selecionado no topo.

## 2. Ativar a API do Google Fotos

1. Abra: **https://console.cloud.google.com/apis/library/photoslibrary.googleapis.com?hl=pt-BR**
   (ou menu ☰ → **APIs e serviços** / *APIs & Services* → **Biblioteca** / *Library* →
   pesquise `Photos Library API`).
2. Clique em **Ativar** (*Enable*).

## 3. Configurar a tela de permissão (Google Auth Platform)

1. Abra: **https://console.cloud.google.com/auth/overview?hl=pt-BR**
   (ou menu ☰ → **APIs e serviços** → **Tela de permissão OAuth** / *OAuth consent screen*).
2. Clique em **Primeiros passos** (*Get started*) e preencha:
   - **Informações do app** (*App information*): nome `FotoFaxina` e o seu Gmail em
     **E-mail para suporte do usuário** (*User support email*) → **Próxima** (*Next*).
   - **Público-alvo** (*Audience*): escolha **Externo** (*External*) → **Próxima**.
   - **Dados de contato** (*Contact information*): seu Gmail → **Próxima**.
   - Marque que concorda com a política → **Continuar** (*Continue*) → **Criar** (*Create*).

## 4. Autorizar quem vai usar (usuários de teste)

Enquanto o app estiver em modo de teste, só os e-mails desta lista conseguem entrar.

1. Menu da esquerda: **Público-alvo** (*Audience*).
2. Em **Usuários de teste** (*Test users*) → **Adicionar usuários** (*Add users*).
3. Digite o seu Gmail (e o da sua esposa, se ela também for usar) → **Salvar** (*Save*).

> **Não** clique em “Publicar app” (*Publish app*). Para uso da família, o modo de teste basta.

## 5. Criar a credencial e baixar o arquivo

1. Menu da esquerda: **Clientes** (*Clients*) → **Criar cliente** (*Create client*).
2. **Tipo de aplicativo** (*Application type*): **App para computador** (*Desktop app*).
3. Nome: `FotoFaxina` → **Criar** (*Create*).
4. Na janela que abre, clique em **Fazer o download do JSON** (*Download JSON*).
   Se a janela fechou: na lista de **Clientes**, clique no ícone de download (⬇) da linha FotoFaxina.

O arquivo baixado tem um nome comprido, tipo `client_secret_1234…apps.googleusercontent.com.json`.
Não precisa renomear.

## 6. Conectar no FotoFaxina

1. Abra o FotoFaxina → aba **Configurações**.
2. **Selecionar client_secret.json…** → escolha o arquivo baixado.
3. **Conectar conta Google** → o navegador abre.
4. Escolha sua conta. Vai aparecer **“O Google não verificou este app”**
   (*Google hasn't verified this app*). Isso é normal para apps pessoais:
   clique em **Continuar** (*Continue*).
5. Marque as caixinhas de permissão do Google Fotos → **Continuar**.
6. Aparece “Pronto! Pode fechar esta aba…”. Volte ao FotoFaxina: a conta aparece como conectada.

---

## Problemas comuns

| Mensagem | O que fazer |
|---|---|
| **Erro 403: access_denied** / “O app está em fase de testes” | Seu e-mail não está em **Usuários de teste** (passo 4). |
| **Photos Library API has not been used in project…** | A API não foi ativada no projeto certo (passo 2). Confira o projeto selecionado no topo. |
| **redirect_uri_mismatch** | A credencial foi criada como “Aplicativo da Web”. Crie outra como **App para computador** (passo 5). |
| Funcionava e parou depois de uma semana | No modo de teste o login vale 7 dias. Clique em **Conectar conta Google** de novo. |
| Não acho o arquivo baixado | Veja a pasta **Downloads**; o nome começa com `client_secret_`. |

## Opcional: embutir a credencial no instalador

Assim quem instala o FotoFaxina não precisa fazer nada disso — só clica em **Conectar conta
Google** (o e-mail da pessoa ainda precisa estar em **Usuários de teste**).

1. Abra o `client_secret_….json` no Bloco de Notas e copie todo o conteúdo.
2. No GitHub, no repositório: **Settings** → **Secrets and variables** → **Actions** →
   **New repository secret**.
3. Name: `GOOGLE_CLIENT_SECRET_JSON` · Secret: cole o conteúdo → **Add secret**.
4. Gere uma nova versão (Releases). O instalador novo já vem com a credencial.

A credencial nunca fica no código do repositório, só dentro do instalador.

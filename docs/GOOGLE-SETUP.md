# How to create the Google credential (step by step)

[🇧🇷 Português](CONFIGURAR-GOOGLE.md) · 🇺🇸 English

It takes about 10 minutes and is done **only once**. At the end you will have a
`client_secret.json` file, which FotoFaxina uses to ask your permission to upload photos to
Google Photos. **No credit card is needed** — nothing here is billed.

---

## 1. Create a project

1. Open **https://console.cloud.google.com/** and accept the terms if asked.
2. At the top, next to the “Google Cloud” logo, click the project picker
   (it may say **Select a project**).
3. Click **New project**, name it `FotoFaxina` → **Create**.
4. Wait a few seconds and make sure **FotoFaxina** is selected at the top.

## 2. Enable the Google Photos API

1. Open **https://console.cloud.google.com/apis/library/photoslibrary.googleapis.com**
   (or menu ☰ → **APIs & Services** → **Library** → search `Photos Library API`).
2. Click **Enable**.

## 3. Set up the consent screen (Google Auth Platform)

1. Open **https://console.cloud.google.com/auth/overview**
   (or menu ☰ → **APIs & Services** → **OAuth consent screen**).
2. Click **Get started** and fill in:
   - **App information**: name `FotoFaxina` and your Gmail as **User support email** → **Next**.
   - **Audience**: choose **External** → **Next**.
   - **Contact information**: your Gmail → **Next**.
   - Agree to the policy → **Continue** → **Create**.

## 4. Allow who will use it (test users)

While the app is in testing mode, only the e-mails on this list can sign in.

1. Left menu: **Audience**.
2. Under **Test users** → **Add users**.
3. Type your Gmail (and your family's, if they will use it too) → **Save**.

> **Don't** click “Publish app”. For family use, testing mode is enough.

## 5. Create the credential and download the file

1. Left menu: **Clients** → **Create client**.
2. **Application type**: **Desktop app**.
3. Name: `FotoFaxina` → **Create**.
4. In the window that opens, click **Download JSON**.
   If it closed: in the **Clients** list, click the download icon (⬇) on the FotoFaxina row.

The file has a long name like `client_secret_1234…apps.googleusercontent.com.json`.
No need to rename it.

## 6. Connect in FotoFaxina

1. Open FotoFaxina → **Settings** tab.
2. **Select client_secret.json…** → pick the downloaded file.
3. **Connect Google account** → the browser opens.
4. Choose your account. You will see **“Google hasn't verified this app”**. That is normal for
   personal apps: click **Continue**.
5. Tick the Google Photos permission boxes → **Continue**.
6. “Done! You can close this tab…” appears. Back in FotoFaxina, the account shows as connected.

---

## Common problems

| Message | What to do |
|---|---|
| **Error 403: access_denied** / “The app is being tested” | Your e-mail is not in **Test users** (step 4). |
| **Photos Library API has not been used in project…** | The API was not enabled in the right project (step 2). Check the project selected at the top. |
| **redirect_uri_mismatch** | The credential was created as “Web application”. Create another one as **Desktop app** (step 5). |
| It worked and stopped after a week | In testing mode the sign-in lasts 7 days. Click **Connect Google account** again. |
| Can't find the downloaded file | Look in **Downloads**; the name starts with `client_secret_`. |

## Optional: bundle the credential in the installer

That way whoever installs FotoFaxina doesn't need any of this — they just click
**Connect Google account** (their e-mail still has to be in **Test users**).

1. Open `client_secret_….json` in Notepad and copy all of it.
2. On GitHub, in the repository: **Settings** → **Secrets and variables** → **Actions** →
   **New repository secret**.
3. Name: `GOOGLE_CLIENT_SECRET_JSON` · Secret: paste the content → **Add secret**.
4. Release a new version. The new installer comes with the credential.

The credential never goes into the repository code, only into the installer.

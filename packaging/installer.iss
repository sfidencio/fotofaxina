; Instalador do FotoFaxina (Inno Setup 6)
; Compilar: iscc /DAppVersion=1.0.0 packaging\installer.iss   (depois do PyInstaller)

#define AppName "FotoFaxina"
#define AppExe "FotoFaxina.exe"
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{8F2B6C1E-5D7A-4C2B-9E1F-6A0D3C7B1F42}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Fidencio
AppPublisherURL=https://github.com/sfidencio/fotofaxina
; instala só para o usuário atual: não pede senha de administrador
PrivilegesRequired=lowest
DefaultDirName={localappdata}\Programs\{#AppName}
DisableProgramGroupPage=yes
DisableDirPage=yes
OutputDir=..\dist
OutputBaseFilename=FotoFaxina-Setup-{#AppVersion}
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; escolhe o idioma do instalador pelo idioma do Windows, sem perguntar
ShowLanguageDialog=no
LanguageDetectionMethod=uilanguage
CloseApplications=force
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
; o primeiro é o padrão quando o Windows não está em nenhum dos dois idiomas
Name: "en"; MessagesFile: "compiler:Default.isl"
Name: "ptbr"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[CustomMessages]
ptbr.Opcoes=Opções:
en.Opcoes=Options:
ptbr.Autostart=Iniciar com o Windows (fica perto do relógio esperando o HD)
en.Autostart=Start with Windows (waits next to the clock for your drive)
ptbr.Atalho=Criar atalho na área de trabalho
en.Atalho=Create a desktop shortcut
ptbr.AbrirAgora=Abrir o FotoFaxina agora
en.AbrirAgora=Open FotoFaxina now

[Tasks]
Name: "autostart"; Description: "{cm:Autostart}"; GroupDescription: "{cm:Opcoes}"
Name: "desktopicon"; Description: "{cm:Atalho}"; GroupDescription: "{cm:Opcoes}"

[Files]
Source: "..\dist\FotoFaxina\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[InstallDelete]
; remove arquivos de versões anteriores antes de copiar a nova
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "{#AppName}"; ValueData: """{app}\{#AppExe}"" --minimizado"; Flags: uninsdeletevalue; Tasks: autostart

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:AbrirAgora}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{cmd}"; Parameters: "/C taskkill /IM {#AppExe} /F"; Flags: runhidden; RunOnceId: "FecharFotoFaxina"

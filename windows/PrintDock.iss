; PrintDock – Windows-Setup (Inno Setup). Gebaut vom Release-Workflow:
;   iscc /DAppVersion=1.2.3 windows\PrintDock.iss
; Installiert ohne Adminrechte fuer den angemeldeten Benutzer. Die Sprache wird vom System erkannt und einmal zur
; Auswahl angeboten; sie gilt fuer Setup und App. Bei der Neuinstallation fragt es: USB, LAN/WLAN oder Server.
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#define AppId "8F3C2B71-4D5E-4A9B-9C21-7E6D5A4B3C2D"

[Setup]
AppId={{{#AppId}}
AppName=PrintDock
AppVersion={#AppVersion}
AppVerName=PrintDock {#AppVersion}
AppPublisherURL=https://github.com/LucyWolf/printdock
DefaultDirName={localappdata}\Programs\PrintDock
DefaultGroupName=PrintDock
DisableProgramGroupPage=yes
DisableDirPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=PrintDock-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\PrintDock.exe
CloseApplications=yes
ShowLanguageDialog=yes
LanguageDetectionMethod=uilanguage

[Languages]
Name: "german"; MessagesFile: "compiler:Languages\German.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "french"; MessagesFile: "compiler:Languages\French.isl"
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"
Name: "italian"; MessagesFile: "compiler:Languages\Italian.isl"
Name: "portuguese"; MessagesFile: "compiler:Languages\Portuguese.isl"
Name: "dutch"; MessagesFile: "compiler:Languages\Dutch.isl"
Name: "polish"; MessagesFile: "compiler:Languages\Polish.isl"
Name: "turkish"; MessagesFile: "compiler:Languages\Turkish.isl"
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "ukrainian"; MessagesFile: "compiler:Languages\Ukrainian.isl"
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
Name: "japanese"; MessagesFile: "compiler:Languages\Japanese.isl"

[CustomMessages]
german.ConnCaption=Drucker
german.ConnQuestion=Wie ist dein Drucker angeschlossen?
german.ConnLAN=LAN / WLAN
german.ConnServer=Server (Firma / Amt)
german.SrvPrompt=Adresse des PrintDock-Servers (z. B. https://drucker.example.org):
german.SrvNote=Beim ersten Start fragt PrintDock nach Benutzername und Passwort für den Server.
english.ConnCaption=Printer
english.ConnQuestion=How is your printer connected?
english.ConnLAN=LAN / Wi-Fi
english.ConnServer=Server (company / authority)
english.SrvPrompt=Address of the PrintDock Server (e.g. https://printers.example.org):
english.SrvNote=On first start PrintDock asks for the user name and password for the server.
french.ConnCaption=Imprimante
french.ConnQuestion=Comment votre imprimante est-elle connectée ?
french.ConnLAN=LAN / Wi-Fi
french.ConnServer=Serveur (entreprise / administration)
french.SrvPrompt=Adresse du serveur PrintDock (p. ex. https://imprimantes.example.org) :
french.SrvNote=Au premier démarrage, PrintDock demande le nom d'utilisateur et le mot de passe du serveur.
spanish.ConnCaption=Impresora
spanish.ConnQuestion=¿Cómo está conectada tu impresora?
spanish.ConnLAN=LAN / Wi-Fi
spanish.ConnServer=Servidor (empresa / administración)
spanish.SrvPrompt=Dirección del servidor PrintDock (p. ej. https://impresoras.example.org):
spanish.SrvNote=En el primer inicio, PrintDock pide el nombre de usuario y la contraseña del servidor.
italian.ConnCaption=Stampante
italian.ConnQuestion=Come è collegata la tua stampante?
italian.ConnLAN=LAN / Wi-Fi
italian.ConnServer=Server (azienda / ente)
italian.SrvPrompt=Indirizzo del server PrintDock (p. es. https://stampanti.example.org):
italian.SrvNote=Al primo avvio PrintDock chiede nome utente e password del server.
portuguese.ConnCaption=Impressora
portuguese.ConnQuestion=Como está ligada a sua impressora?
portuguese.ConnLAN=LAN / Wi-Fi
portuguese.ConnServer=Servidor (empresa / serviço público)
portuguese.SrvPrompt=Endereço do servidor PrintDock (p. ex. https://impressoras.example.org):
portuguese.SrvNote=No primeiro arranque, o PrintDock pede o nome de utilizador e a palavra-passe do servidor.
dutch.ConnCaption=Printer
dutch.ConnQuestion=Hoe is je printer aangesloten?
dutch.ConnLAN=LAN / wifi
dutch.ConnServer=Server (bedrijf / overheid)
dutch.SrvPrompt=Adres van de PrintDock-server (bijv. https://printers.example.org):
dutch.SrvNote=Bij de eerste start vraagt PrintDock om gebruikersnaam en wachtwoord voor de server.
polish.ConnCaption=Drukarka
polish.ConnQuestion=Jak podłączona jest twoja drukarka?
polish.ConnLAN=LAN / Wi-Fi
polish.ConnServer=Serwer (firma / urząd)
polish.SrvPrompt=Adres serwera PrintDock (np. https://drukarki.example.org):
polish.SrvNote=Przy pierwszym uruchomieniu PrintDock zapyta o nazwę użytkownika i hasło do serwera.
turkish.ConnCaption=Yazıcı
turkish.ConnQuestion=Yazıcınız nasıl bağlı?
turkish.ConnLAN=LAN / Wi-Fi
turkish.ConnServer=Sunucu (şirket / kurum)
turkish.SrvPrompt=PrintDock sunucusunun adresi (ör. https://yazicilar.example.org):
turkish.SrvNote=İlk başlatmada PrintDock sunucu için kullanıcı adını ve parolayı sorar.
russian.ConnCaption=Принтер
russian.ConnQuestion=Как подключён ваш принтер?
russian.ConnLAN=LAN / Wi-Fi
russian.ConnServer=Сервер (компания / учреждение)
russian.SrvPrompt=Адрес сервера PrintDock (например, https://printers.example.org):
russian.SrvNote=При первом запуске PrintDock запросит имя пользователя и пароль для сервера.
ukrainian.ConnCaption=Принтер
ukrainian.ConnQuestion=Як під'єднано ваш принтер?
ukrainian.ConnLAN=LAN / Wi-Fi
ukrainian.ConnServer=Сервер (компанія / установа)
ukrainian.SrvPrompt=Адреса сервера PrintDock (наприклад, https://printers.example.org):
ukrainian.SrvNote=Під час першого запуску PrintDock запитає ім'я користувача та пароль для сервера.
chinesesimplified.ConnCaption=打印机
chinesesimplified.ConnQuestion=你的打印机如何连接？
chinesesimplified.ConnLAN=LAN / Wi-Fi
chinesesimplified.ConnServer=服务器（企业 / 机构）
chinesesimplified.SrvPrompt=PrintDock 服务器地址（例如 https://printers.example.org）：
chinesesimplified.SrvNote=首次启动时，PrintDock 会询问服务器的用户名和密码。
japanese.ConnCaption=プリンター
japanese.ConnQuestion=プリンターの接続方法は？
japanese.ConnLAN=LAN / Wi-Fi
japanese.ConnServer=サーバー（企業 / 官公庁）
japanese.SrvPrompt=PrintDock サーバーのアドレス（例：https://printers.example.org）：
japanese.SrvNote=初回起動時に、PrintDock がサーバーのユーザー名とパスワードを尋ねます。

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\PrintDock\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; Sprachdateien gleich mitliefern: die App holt sie sonst beim ersten Start aus dem Netz
Source: "..\sprachen\*.json"; DestDir: "{userappdata}\PrintDock\sprachen"; Flags: ignoreversion

[Icons]
Name: "{group}\PrintDock"; Filename: "{app}\PrintDock.exe"
Name: "{group}\{cm:UninstallProgram,PrintDock}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\PrintDock"; Filename: "{app}\PrintDock.exe"; Tasks: desktopicon

[Run]
; auch nach einem stillen Update (aus der App heraus) wieder starten; /NOLAUNCH nur fuer den Test im Workflow
Filename: "{app}\PrintDock.exe"; Description: "{cm:LaunchProgram,PrintDock}"; Flags: nowait postinstall; Check: not NoLaunch

[Code]
var
  ConnPage: TInputOptionWizardPage;
  SrvPage: TInputQueryWizardPage;
  WasInstalled: Boolean;

function NoLaunch: Boolean;
var
  I: Integer;
begin
  Result := False;
  for I := 1 to ParamCount do
    if CompareText(ParamStr(I), '/NOLAUNCH') = 0 then Result := True;
end;

function InitializeSetup: Boolean;
begin
  WasInstalled := RegValueExists(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{{#AppId}}_is1', 'UninstallString');
  Result := True;
end;

procedure InitializeWizard;
begin
  ConnPage := CreateInputOptionPage(wpSelectTasks, CustomMessage('ConnCaption'), CustomMessage('ConnQuestion'), '', True, False);
  ConnPage.Add('USB');
  ConnPage.Add(CustomMessage('ConnLAN'));
  ConnPage.Add(CustomMessage('ConnServer'));
  ConnPage.SelectedValueIndex := 0;
  SrvPage := CreateInputQueryPage(ConnPage.ID, CustomMessage('ConnServer'), CustomMessage('SrvNote'), '');
  SrvPage.Add(CustomMessage('SrvPrompt'), False);
  SrvPage.Values[0] := 'https://';
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := False;
  if (PageID = ConnPage.ID) and WasInstalled then Result := True;
  if (PageID = SrvPage.ID) and (WasInstalled or (ConnPage.SelectedValueIndex <> 2)) then Result := True;
end;

function LangCode: String;
begin
  case ActiveLanguage of
    'german': Result := 'de';
    'french': Result := 'fr';
    'spanish': Result := 'es';
    'italian': Result := 'it';
    'portuguese': Result := 'pt';
    'dutch': Result := 'nl';
    'polish': Result := 'pl';
    'turkish': Result := 'tr';
    'russian': Result := 'ru';
    'ukrainian': Result := 'uk';
    'chinesesimplified': Result := 'zh';
    'japanese': Result := 'ja';
  else
    Result := 'en';
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Dir, Url: String;
begin
  if CurStep <> ssPostInstall then Exit;
  Dir := ExpandConstant('{userappdata}\PrintDock');
  ForceDirectories(Dir);
  { Ein stilles Update aus der App laesst die in der App gewaehlte Sprache stehen }
  if (not WizardSilent) or (not FileExists(Dir + '\sprache')) then
    SaveStringToFile(Dir + '\sprache', LangCode + #13#10, False);
  if (not WasInstalled) and (ConnPage.SelectedValueIndex = 2) then
  begin
    Url := Trim(SrvPage.Values[0]);
    if (Url <> '') and (Url <> 'https://') then
    begin
      if (Pos('http://', Url) <> 1) and (Pos('https://', Url) <> 1) then Url := 'https://' + Url;
      SaveStringToFile(Dir + '\server', Url + #13#10, False);
    end;
  end;
end;

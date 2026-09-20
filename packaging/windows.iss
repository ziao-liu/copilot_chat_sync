#ifndef AppVersion
  #error AppVersion is required
#endif
#ifndef BundleDir
  #error BundleDir is required
#endif
#ifndef OutputDir
  #error OutputDir is required
#endif
#ifndef WebViewSetup
  #error WebViewSetup is required
#endif

[Setup]
AppId=ziao-liu.CopilotChatSync
AppName=Copilot Chat Sync
AppVersion={#AppVersion}
AppPublisher=ziao-liu
AppPublisherURL=https://github.com/ziao-liu/copilot_chat_sync
DefaultDirName={localappdata}\Programs\CopilotChatSync
DefaultGroupName=Copilot Chat Sync
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
LicenseFile=..\LICENSE
OutputDir={#OutputDir}
OutputBaseFilename=CopilotChatSync-{#AppVersion}-windows-x64-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=no
RestartApplications=no
UninstallDisplayIcon={app}\CopilotChatSync.exe

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Files]
Source: "{#BundleDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#WebViewSetup}"; Flags: dontcopy

[Icons]
Name: "{autoprograms}\Copilot Chat Sync"; Filename: "{app}\CopilotChatSync.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\Copilot Chat Sync"; Filename: "{app}\CopilotChatSync.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\CopilotChatSync.exe"; Description: "Open Copilot Chat Sync"; Flags: nowait postinstall skipifsilent

[Code]
function WebViewAvailable: Boolean;
var
  Version: String;
  Key: String;
begin
  Key := 'Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';
  Result := ((RegQueryStringValue(HKCU, Key, 'pv', Version) or
              RegQueryStringValue(HKLM32, Key, 'pv', Version)) and
             (Version <> '') and (Version <> '0.0.0.0'));
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ExitCode: Integer;
begin
  Result := '';
  if not WebViewAvailable then
  begin
    if not WizardSilent then
      if MsgBox('Microsoft WebView2 Runtime is required. Setup will install it from Microsoft; an internet connection is needed. Continue?', mbConfirmation, MB_YESNO) <> IDYES then
      begin
        Result := 'Install Microsoft WebView2 Runtime before continuing.';
        Exit;
      end;
    ExtractTemporaryFile('MicrosoftEdgeWebview2Setup.exe');
    if not Exec(ExpandConstant('{tmp}\MicrosoftEdgeWebview2Setup.exe'), '/silent /install', '', SW_HIDE, ewWaitUntilTerminated, ExitCode) then
      Result := 'Could not start the Microsoft WebView2 installer.'
    else if not WebViewAvailable then
      Result := 'Microsoft WebView2 could not be installed. Install the Evergreen Runtime from https://developer.microsoft.com/microsoft-edge/webview2/consumer/ and retry.';
  end;
end;
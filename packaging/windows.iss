#ifndef AppVersion
  #error AppVersion is required
#endif
#ifndef BundleDir
  #error BundleDir is required
#endif
#ifndef OutputDir
  #error OutputDir is required
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

[Icons]
Name: "{autoprograms}\Copilot Chat Sync"; Filename: "{app}\CopilotChatSync.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\Copilot Chat Sync"; Filename: "{app}\CopilotChatSync.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\CopilotChatSync.exe"; Description: "Open Copilot Chat Sync"; Flags: nowait postinstall skipifsilent
#define MyAppName "PromptMeld"
#ifndef MyAppVersion
  #define MyAppVersion "0.1.0"
#endif
#ifndef MyAppMutex
  #define MyAppMutex "Local\PromptMeld-v1"
#endif
#ifndef MyOutputBaseFilename
  #define MyOutputBaseFilename "PromptMeld-Setup-v" + MyAppVersion
#endif
#define MyAppPublisher "PromptMeld contributors"
#define MyAppExeName "PromptMeld.exe"

[Setup]
AppId={{B65C3027-5196-4D6A-A411-7985105A32B0}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL=https://github.com/an1uk/promptmeld-windows
AppSupportURL=https://github.com/an1uk/promptmeld-windows/issues
AppUpdatesURL=https://github.com/an1uk/promptmeld-windows/releases
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=..\dist\installer
OutputBaseFilename={#MyOutputBaseFilename}
SetupIconFile=..\src\promptmeld\resources\branding\promptmeld.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
LicenseFile=..\LICENSE
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
CloseApplications=force
RestartApplications=no
AppMutex={#MyAppMutex}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
Source: "..\dist\PromptMeld\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\PromptMeld"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall PromptMeld"; Filename: "{uninstallexe}"
Name: "{autodesktop}\PromptMeld"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch PromptMeld"; Flags: nowait postinstall skipifsilent

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
    RegDeleteValue(
      HKCU,
      'Software\Microsoft\Windows\CurrentVersion\Run',
      'PromptMeld'
    );
end;

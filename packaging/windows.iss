#ifndef AppVersion
  #define AppVersion "0.3.4"
#endif
[Setup]
AppId={{92384361-D151-4594-B57B-11D3548B07C1}
AppName=Mac Controller
AppVersion={#AppVersion}
AppPublisher=StellarStar255
AppPublisherURL=https://github.com/StellarStar255/stellar_mac_controller
DefaultDirName={localappdata}\Programs\MacController
DefaultGroupName=Mac Controller
PrivilegesRequired=lowest
DisableProgramGroupPage=yes
DisableDirPage=yes
DisableWelcomePage=yes
OutputDir=..\release
OutputBaseFilename=MacController-{#AppVersion}-windows-x64-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\MacController.exe
CloseApplications=yes
RestartApplications=no
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
[Files]
Source: "..\dist\MacController\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
[Icons]
Name: "{group}\Mac Controller"; Filename: "{app}\MacController.exe"
Name: "{autodesktop}\Mac Controller"; Filename: "{app}\MacController.exe"
[InstallDelete]
Type: filesandordirs; Name: "{app}\_internal"
[Run]
Filename: "{app}\MacController.exe"; Description: "启动 Mac Controller"; Flags: nowait postinstall skipifsilent

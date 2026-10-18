; Inno Setup script for the FRCA Election installer.
; Built by packaging/build.ps1, which passes /DAppVersion=<version.py>.
; Never change AppId: it is how upgrades find the existing install.

#ifndef AppVersion
  #error AppVersion not defined. Build with packaging/build.ps1.
#endif

#define AppName "FRCA Election"
#define AppExe "FRCA-Election.exe"
#define RuleName "FRCA Election"

[Setup]
AppId={{338F559E-AE20-4728-AB9A-0EF21064530A}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisherURL=https://github.com/jdemooijau/frca_election_app
DefaultDirName={autopf}\{#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64ModeOnly=x64compatible
OutputDir=dist
OutputBaseFilename=FRCA-Election-Setup-{#AppVersion}
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Dirs]
; Users-modify so the app can write its data without running as admin.
; Never removed on uninstall: it holds the election database.
Name: "{commonappdata}\{#AppName}\data"; Permissions: users-modify; Flags: uninsneveruninstall

[Files]
Source: "dist\FRCA-Election\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autoprograms}\{#AppName} data folder"; Filename: "{commonappdata}\{#AppName}\data"

[Run]
Filename: "{app}\{#AppExe}"; Description: "Start {#AppName} now"; Flags: postinstall nowait skipifsilent runasoriginaluser unchecked

[UninstallRun]
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""{#RuleName}"""; Flags: runhidden; RunOnceId: "DeleteFirewallRule"

[Code]
var
  RemovedPortProxy: Boolean;

function Netsh(Params: String): Boolean;
var
  ResultCode: Integer;
begin
  Result := Exec(ExpandConstant('{sys}\netsh.exe'), Params, '', SW_HIDE,
                 ewWaitUntilTerminated, ResultCode) and (ResultCode = 0);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    { The old captive-portal-on.bat proxy holds port 80 and would block the app. }
    RemovedPortProxy := Netsh('interface portproxy delete v4tov4 listenport=80 listenaddress=0.0.0.0');
    if Netsh('interface portproxy delete v4tov4 listenport=443 listenaddress=0.0.0.0') then
      RemovedPortProxy := True;

    { Replace, never duplicate, our own rule. The delete fails harmlessly on a first install. }
    Netsh('advfirewall firewall delete rule name="{#RuleName}"');
    if not Netsh('advfirewall firewall add rule name="{#RuleName}" dir=in action=allow ' +
                 'program="' + ExpandConstant('{app}\{#AppExe}') + '" protocol=TCP ' +
                 'localport=80,5000 remoteip=10.0.0.0/24 profile=any') then
      MsgBox('The firewall rule could not be added. Phones may not reach the app. ' +
             'See SETUP.md, "Firewall".', mbError, MB_OK);
  end;
end;

procedure CurPageChanged(CurPageID: Integer);
var
  Extra: String;
begin
  if CurPageID = wpFinished then
  begin
    Extra := #13#10#13#10 + 'Election data is kept in:' + #13#10 +
             ExpandConstant('{commonappdata}\{#AppName}\data') + #13#10 +
             'Uninstalling the app does not delete it.';
    if RemovedPortProxy then
      Extra := Extra + #13#10#13#10 + 'Old port forwarding from captive-portal-on.bat ' +
               'was removed. The app now listens on port 80 itself.';
    WizardForm.FinishedLabel.Caption := WizardForm.FinishedLabel.Caption + Extra;
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if (CurUninstallStep = usPostUninstall) and not UninstallSilent then
    MsgBox('The election data was kept in ' +
           ExpandConstant('{commonappdata}\{#AppName}\data') +
           '. Delete that folder yourself if you no longer need it.',
           mbInformation, MB_OK);
end;

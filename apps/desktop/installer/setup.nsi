Unicode true
!include "MUI2.nsh"
!include "LogicLib.nsh"
!include "FileFunc.nsh"
!ifndef AppPayload
!error "Define AppPayload as the built matched shell/runtime directory"
!endif
!ifndef OutputPath
!define OutputPath "Lenny-Translator-Setup.exe"
!endif
Name "Lenny Translator"
OutFile "${OutputPath}"
InstallDir "$LOCALAPPDATA\Programs\Lenny Translator"
RequestExecutionLevel user
InstType "Online and offline (recommended)"
InstType "Online only"
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_COMPONENTS
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"

Function .onInit
  SetShellVarContext current
  ${GetParameters} $0
  ${GetOptions} $0 "/ONLINE" $1
  ${IfNot} ${Errors}
    SetCurInstType 1
  ${EndIf}
  IfFileExists "$INSTDIR\lenny-desktop.exe" 0 done
  ExecWait '$\"$INSTDIR\lenny-desktop.exe$\" --shutdown'
  Sleep 16000
  nsExec::ExecToStack '$\"$SYSDIR\WindowsPowerShell\v1.0\powershell.exe$\" -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $\"$INSTDIR\register-explorer.ps1$\" -InstallDir $\"$INSTDIR$\" -CheckPaths'
  Pop $0
  Pop $1
  ${If} $0 != 0
    MessageBox MB_ICONSTOP "The application is still in use or its paths require review. Update stopped to preserve files." /SD IDOK
    Abort
  ${EndIf}
  done:
FunctionEnd

Section "Lenny Translator" App
  SectionIn 1 2 RO
  SetOutPath "$INSTDIR"
  File /r "${AppPayload}\*"
  ; Signed sparse identity registration supplies the Windows 11 modern submenu.
  nsExec::ExecToStack '$\"$SYSDIR\WindowsPowerShell\v1.0\powershell.exe$\" -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $\"$INSTDIR\register-explorer.ps1$\" -InstallDir $\"$INSTDIR$\"'
  Pop $0
  Pop $1
  ${If} $0 != 0
    MessageBox MB_ICONEXCLAMATION "Explorer registration could not finish. The application is installed. A trusted signed identity package is required for the modern menu." /SD IDOK
  ${EndIf}
  CreateShortcut "$SMPROGRAMS\Lenny Translator.lnk" "$INSTDIR\lenny-desktop.exe"
  WriteUninstaller "$INSTDIR\Uninstall.exe"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\LennyTranslator" "DisplayName" "Lenny Translator"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\LennyTranslator" "UninstallString" '$\"$INSTDIR\Uninstall.exe$\"'
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\LennyTranslator" "InstallLocation" "$INSTDIR"
SectionEnd

Section "Offline support" Offline
  SectionIn 1
  !ifdef OfflinePayload
    SetOutPath "$INSTDIR\runtime\offline-media"
    File /r "${OfflinePayload}\*"
  !endif
  Exec '$\"$INSTDIR\lenny-desktop.exe$\" --install-offline'
SectionEnd

Section "Uninstall"
  SetShellVarContext current
  StrCmp $INSTDIR "$LOCALAPPDATA\Programs\Lenny Translator" +3
    MessageBox MB_ICONSTOP "Unexpected installation directory. Uninstall stopped to preserve files."
    Abort
  ExecWait '$\"$INSTDIR\lenny-desktop.exe$\" --shutdown'
  Sleep 16000
  nsExec::ExecToLog '$\"$SYSDIR\WindowsPowerShell\v1.0\powershell.exe$\" -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $\"$INSTDIR\register-explorer.ps1$\" -InstallDir $\"$INSTDIR$\" -Remove'
  nsExec::ExecToStack '$\"$SYSDIR\WindowsPowerShell\v1.0\powershell.exe$\" -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $\"$INSTDIR\register-explorer.ps1$\" -InstallDir $\"$INSTDIR$\" -CheckPaths'
  Pop $0
  Pop $1
  ${If} $0 != 0
    MessageBox MB_ICONSTOP "Installation paths require manual review. Files were preserved."
    Abort
  ${EndIf}
  Delete "$SMPROGRAMS\Lenny Translator.lnk"
  ; User originals, exports, and model/work data remain outside this verified install tree.
  RMDir /r "$INSTDIR\runtime"
  Delete "$INSTDIR\lenny-desktop.exe"
  Delete "$INSTDIR\lenny-explorer.dll"
  Delete "$INSTDIR\Lenny.Identity.msix"
  Delete "$INSTDIR\icon.png"
  Delete "$INSTDIR\register-explorer.ps1"
  IfFileExists "$INSTDIR\lenny-desktop.exe" removal_failed
  IfFileExists "$INSTDIR\lenny-explorer.dll" removal_failed
  IfFileExists "$INSTDIR\runtime\*.*" removal_failed
  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\LennyTranslator"
  Goto removal_complete
  removal_failed:
  MessageBox MB_ICONSTOP "Some application files are still in use. Uninstall registration was retained; close Lenny and retry." /SD IDOK
  Abort
  removal_complete:
  Delete "$INSTDIR\Uninstall.exe"
  RMDir "$INSTDIR"
SectionEnd

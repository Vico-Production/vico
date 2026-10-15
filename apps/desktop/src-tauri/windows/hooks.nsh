; Vico's additions to its NSIS installer (bundle.windows.nsis.installerHooks).
; Variables used here ($UpdateMode) are declared by the installer template.

!macro NSIS_HOOK_POSTINSTALL
  ; Earlier test builds put an icon on the desktop; Vico lives in the tray, so remove it.
  !insertmacro IsShortcutTarget "$DESKTOP\${PRODUCTNAME}.lnk" "$INSTDIR\${MAINBINARYNAME}.exe"
  Pop $0
  ${If} $0 = 1
    Delete "$DESKTOP\${PRODUCTNAME}.lnk"
  ${EndIf}
!macroend

!macro NSIS_HOOK_POSTUNINSTALL
  ; Uninstalling forgets everything, so a fresh install starts with picking a look and
  ; entering access codes again. Automatic updates (/UPDATE) keep them.
  ${If} $UpdateMode <> 1
    ; The codes live in Windows Credential Manager. Python's keyring names the first one
    ; "vico-desktop" and the others "<name>@vico-desktop".
    nsExec::Exec 'cmdkey /delete:vico-desktop'
    Pop $0
    nsExec::Exec 'cmdkey /delete:gemini@vico-desktop'
    Pop $0
    nsExec::Exec 'cmdkey /delete:groq@vico-desktop'
    Pop $0
    nsExec::Exec 'cmdkey /delete:speech_server@vico-desktop'
    Pop $0
    ; Settings, history, the chosen look, the wake-word model and the sign-in marker.
    SetShellVarContext current
    RMDir /r "$APPDATA\Vico"
    RMDir /r "$APPDATA\${BUNDLEID}"
  ${EndIf}
!macroend

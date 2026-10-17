; Vico's additions to its NSIS installer (bundle.windows.nsis.installerHooks).
; Variables used here ($UpdateMode) are declared by the installer template.

!macro NSIS_HOOK_POSTINSTALL
  ; Earlier test builds put an icon on the desktop; Vico lives in the tray, so remove it.
  !insertmacro IsShortcutTarget "$DESKTOP\${PRODUCTNAME}.lnk" "$INSTDIR\${MAINBINARYNAME}.exe"
  Pop $0
  ${If} $0 = 1
    Delete "$DESKTOP\${PRODUCTNAME}.lnk"
  ${EndIf}
  ; Vico opens by itself when installation finishes, on its setup screen, and starts with
  ; Windows from then on (the same entry its "Start when I sign in" switch manages). Calling
  ; it by name works once setup is done.
  ${If} $UpdateMode <> 1
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "${PRODUCTNAME}" '"$INSTDIR\${MAINBINARYNAME}.exe" --autostart'
    nsis_tauri_utils::RunAsUser "$INSTDIR\${MAINBINARYNAME}.exe" ""
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
    nsExec::Exec 'cmdkey /delete:mistral@vico-desktop'
    Pop $0
    nsExec::Exec 'cmdkey /delete:openrouter@vico-desktop'
    Pop $0
    nsExec::Exec 'cmdkey /delete:tinyfish@vico-desktop'
    Pop $0
    DeleteRegValue HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "${PRODUCTNAME}"
    ; Settings, history, the chosen look, the wake-word model and the sign-in marker.
    SetShellVarContext current
    RMDir /r "$APPDATA\Vico"
    RMDir /r "$APPDATA\${BUNDLEID}"
  ${EndIf}
!macroend

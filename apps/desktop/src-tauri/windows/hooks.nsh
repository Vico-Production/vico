; Vico's additions to Tauri's NSIS installer (bundle.windows.nsis.installerHooks).
; Variables used here ($UpdateMode, $DeleteAppDataCheckboxState) are declared by Tauri's template.

!macro NSIS_HOOK_POSTUNINSTALL
  ; "Delete the application data" also forgets the saved access codes and Vico's settings,
  ; so a reinstall starts fresh. Updates and plain upgrades keep them.
  ${If} $DeleteAppDataCheckboxState = 1
  ${AndIf} $UpdateMode <> 1
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
    SetShellVarContext current
    RMDir /r "$APPDATA\Vico"
  ${EndIf}
!macroend

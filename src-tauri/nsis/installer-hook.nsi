; src-tauri/nsis/installer-hook.nsi
; ─────────────────────────────────────────────────────────────────────────────
; Tauri 2 NSIS hook — injected into the generated installer by setting
;   bundle.windows.nsis.installerHooks = ["nsis/installer-hook.nsi"]
; in tauri.conf.json (add that key if customisation is needed).
;
; This file adds:
;   1. Custom welcome/finish page header image
;   2. Licence agreement page (required for App Store / enterprise deployment)
;   3. Silent installation of VB-Audio Virtual Cable and OBS Virtual Camera
;   4. Start Menu shortcut with correct icon
;   5. Clean uninstall that also removes the virtual drivers (optional)
; ─────────────────────────────────────────────────────────────────────────────

; ── Branding ─────────────────────────────────────────────────────────────────
Name           "PrankCam"
OutFile        "PrankCam-Setup.exe"
InstallDir     "$PROGRAMFILES64\PrankCam"
RequestExecutionLevel admin

!include "MUI2.nsh"
!include "LogicLib.nsh"

; Header / sidebar images (Tauri places bundled resources in $PLUGINSDIR)
!define MUI_HEADERIMAGE
!define MUI_HEADERIMAGE_BITMAP    "$PLUGINSDIR\banner.bmp"
!define MUI_WELCOMEFINISHPAGE_BITMAP "$PLUGINSDIR\sidebar.bmp"
!define MUI_ICON                  "$PLUGINSDIR\icon.ico"
!define MUI_UNICON                "$PLUGINSDIR\icon.ico"
!define MUI_ABORTWARNING

; ── Pages ─────────────────────────────────────────────────────────────────────
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE   "$PLUGINSDIR\LICENSE.txt"
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "English"

; ── Installer sections ────────────────────────────────────────────────────────

Section "PrankCam" SecMain
    SectionIn RO   ; required, cannot be deselected

    SetOutPath "$INSTDIR"

    ; The main Tauri-generated files are placed here by tauri-action.
    ; We only add the extras.

    ; Start Menu shortcut
    CreateDirectory "$SMPROGRAMS\PrankCam"
    CreateShortCut  "$SMPROGRAMS\PrankCam\PrankCam.lnk" \
                    "$INSTDIR\PrankCam.exe"              \
                    ""                                   \
                    "$INSTDIR\PrankCam.exe" 0

    CreateShortCut  "$SMPROGRAMS\PrankCam\Uninstall PrankCam.lnk" \
                    "$INSTDIR\Uninstall.exe"

    ; Desktop shortcut
    CreateShortCut  "$DESKTOP\PrankCam.lnk" \
                    "$INSTDIR\PrankCam.exe"  \
                    ""                       \
                    "$INSTDIR\PrankCam.exe" 0

    WriteUninstaller "$INSTDIR\Uninstall.exe"

SectionEnd

Section "Virtual Camera Driver (OBS)" SecOBSVCam
    ; OBS Virtual Camera — required for face/video output
    ; The installer is bundled in resources/drivers/windows/
    SetOutPath "$TEMP\prankcam_drivers"
    File /oname=obs-setup.exe "$PLUGINSDIR\drivers\obs-virtualcam-setup.exe"

    DetailPrint "Installing OBS Virtual Camera driver..."
    ExecWait '"$TEMP\prankcam_drivers\obs-setup.exe" /S' $0
    ${If} $0 != 0
        MessageBox MB_OK|MB_ICONINFORMATION \
            "OBS Virtual Camera could not be installed silently.$\n\
             You may install it manually from obsproject.com.$\n\
             PrankCam will still work without it for preview."
    ${EndIf}
    Delete "$TEMP\prankcam_drivers\obs-setup.exe"
SectionEnd

Section "Virtual Audio Driver (VB-Cable)" SecVBCable
    ; VB-Audio Virtual Cable — required for voice output
    SetOutPath "$TEMP\prankcam_drivers"
    File /oname=vbcable-setup.exe "$PLUGINSDIR\drivers\VBCABLE_Setup_x64.exe"

    DetailPrint "Installing VB-Audio Virtual Cable driver..."
    ExecWait '"$TEMP\prankcam_drivers\vbcable-setup.exe" /S' $0
    ${If} $0 != 0
        MessageBox MB_OK|MB_ICONINFORMATION \
            "VB-Audio Virtual Cable could not be installed silently.$\n\
             You may install it manually from vb-audio.com/Cable/$\n\
             PrankCam will still work without it for direct mic output."
    ${EndIf}
    Delete "$TEMP\prankcam_drivers\vbcable-setup.exe"
    RMDir  "$TEMP\prankcam_drivers"
SectionEnd

; ── Uninstaller ───────────────────────────────────────────────────────────────

Section "Uninstall"
    ; Remove Start Menu / Desktop shortcuts
    Delete "$SMPROGRAMS\PrankCam\PrankCam.lnk"
    Delete "$SMPROGRAMS\PrankCam\Uninstall PrankCam.lnk"
    RMDir  "$SMPROGRAMS\PrankCam"
    Delete "$DESKTOP\PrankCam.lnk"

    ; Remove installation directory (Tauri handles main files; we remove extras)
    Delete "$INSTDIR\Uninstall.exe"
    RMDir  "$INSTDIR"

    ; NOTE: Virtual drivers (OBS / VB-Cable) are intentionally NOT removed here
    ; because other apps on the system may use them.
SectionEnd

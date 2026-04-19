# GitHub Actions — Required Secrets

Add these secrets at:  
**GitHub repo → Settings → Secrets and variables → Actions → New repository secret**

---

## Required for all platforms

| Secret | Value | Notes |
|---|---|---|
| *(none required for unsigned builds)* | — | Unsigned builds work but show OS security warnings |

---

## macOS Code Signing (removes "Unidentified Developer" warning)

| Secret | How to get it |
|---|---|
| `APPLE_CERTIFICATE` | Base64-encoded `.p12` export of your Developer ID certificate from Keychain Access |
| `APPLE_CERTIFICATE_PASSWORD` | The password you set when exporting the `.p12` |
| `APPLE_SIGNING_IDENTITY` | The full name, e.g. `Developer ID Application: Your Name (TEAMID)` |
| `APPLE_ID` | Your Apple ID email used for notarization |
| `APPLE_PASSWORD` | App-specific password from appleid.apple.com → Security |
| `APPLE_TEAM_ID` | Your 10-character Team ID from developer.apple.com/account |

**How to create `APPLE_CERTIFICATE`:**
```bash
# In Keychain Access, export your Developer ID cert as .p12
# Then base64-encode it:
base64 -i certificate.p12 | pbcopy   # copies to clipboard
# Paste as the APPLE_CERTIFICATE secret value
```

---

## Windows Code Signing (removes SmartScreen warning)

| Secret | How to get it |
|---|---|
| `TAURI_SIGNING_PRIVATE_KEY` | Generated with `tauri signer generate` (see below) |
| `TAURI_SIGNING_PRIVATE_KEY_PASSWORD` | Password set during key generation |

**Generate a Tauri signing keypair:**
```bash
npm run tauri signer generate -- -w ~/.tauri/prankcam.key
# Prints a public key — add to tauri.conf.json "pubkey" field
# Private key file → base64 encode → TAURI_SIGNING_PRIVATE_KEY secret
base64 -i ~/.tauri/prankcam.key | pbcopy
```

For a proper EV code signing certificate (no SmartScreen at all):
- Purchase from DigiCert, Sectigo, or GlobalSign (~$300/year)
- Use `TAURI_SIGNING_PRIVATE_KEY` with the cert's private key

---

## Driver download URLs (optional — drivers are bundled if URLs are provided)

| Secret | Value |
|---|---|
| `OBS_VCAM_WINDOWS_URL` | Direct download URL for `OBS-Studio-X.Y.Z-Windows-Installer.exe` |
| `VBCABLE_URL` | Direct download URL for `VBCABLE_Driver_Pack43.zip` |
| `BLACKHOLE_PKG_URL` | Direct download URL for `BlackHole2ch-X.Y.Z.pkg` |

**Easier alternative:** Run `bash scripts/download-drivers.sh` locally once,  
commit the downloaded files to a **private** release asset, then set the secrets  
to point to those asset download URLs.

---

## Triggering a release build

```bash
# Tag the commit you want to release
git tag v3.0.0
git push origin v3.0.0

# GitHub Actions automatically:
# 1. Builds on macOS-14 (Apple Silicon), macOS-13 (Intel), Windows, Ubuntu
# 2. Uploads all installers as a DRAFT release
# 3. Publishes the release once all jobs succeed
```

The resulting GitHub Release will contain:
- `PrankCam_3.0.0_aarch64.dmg` — macOS Apple Silicon
- `PrankCam_3.0.0_x64.dmg` — macOS Intel  
- `PrankCam_3.0.0_x64-setup.exe` — Windows NSIS installer
- `PrankCam_3.0.0_x64_en-US.msi` — Windows MSI
- `prankcam_3.0.0_amd64.deb` — Ubuntu/Debian
- `PrankCam_3.0.0_amd64.AppImage` — Linux universal

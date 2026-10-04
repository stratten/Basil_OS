#!/usr/bin/env bash
set -euo pipefail

# Imports the Developer ID signing identity and the App Store Connect notary key into a temporary keychain for one GitHub Actions job. Every input comes from the protected release-build environment; nothing is written outside RUNNER_TEMP.

for name in BASIL_DEVELOPER_ID_P12_BASE64 BASIL_DEVELOPER_ID_P12_PASSWORD BASIL_DEVELOPER_ID_CERT BASIL_NOTARY_API_KEY_P8_BASE64 BASIL_NOTARY_API_KEY_ID BASIL_NOTARY_API_ISSUER_ID BASIL_NOTARY_KEYCHAIN_PROFILE RUNNER_TEMP GITHUB_ENV; do
    if [[ -z "${!name:-}" ]]; then
        echo "Required environment variable is unset: $name" >&2
        exit 1
    fi
done

readonly KEYCHAIN_PATH="$RUNNER_TEMP/basil-signing.keychain-db"
readonly P12_PATH="$RUNNER_TEMP/developer-id.p12"
readonly NOTARY_KEY_PATH="$RUNNER_TEMP/notary-api-key.p8"
readonly INTERMEDIATE_DIR="$RUNNER_TEMP/developer-id-intermediates"
readonly INTERMEDIATE_URLS=(
    "https://www.apple.com/certificateauthority/DeveloperIDCA.cer"
    "https://www.apple.com/certificateauthority/DeveloperIDG2CA.cer"
)

remove_secret_files() {
    rm -f "$P12_PATH" "$NOTARY_KEY_PATH"
    rm -rf "$INTERMEDIATE_DIR"
}
trap remove_secret_files EXIT

keychain_password="$(openssl rand -hex 32)"
echo "::add-mask::$keychain_password"

security create-keychain -p "$keychain_password" "$KEYCHAIN_PATH"
security set-keychain-settings -lut 21600 "$KEYCHAIN_PATH"
security unlock-keychain -p "$keychain_password" "$KEYCHAIN_PATH"

mkdir -p "$INTERMEDIATE_DIR"
for url in "${INTERMEDIATE_URLS[@]}"; do
    certificate_path="$INTERMEDIATE_DIR/$(basename "$url")"
    curl --fail --location --proto '=https' --tlsv1.2 "$url" --output "$certificate_path"
    security import "$certificate_path" -k "$KEYCHAIN_PATH"
done

printf '%s' "$BASIL_DEVELOPER_ID_P12_BASE64" | base64 --decode > "$P12_PATH"
security import "$P12_PATH" -k "$KEYCHAIN_PATH" -P "$BASIL_DEVELOPER_ID_P12_PASSWORD" -f pkcs12 -T /usr/bin/codesign -T /usr/bin/security
security set-key-partition-list -S apple-tool:,apple:,codesign: -s -k "$keychain_password" "$KEYCHAIN_PATH" > /dev/null

search_list=("$KEYCHAIN_PATH")
while IFS= read -r keychain; do
    keychain="${keychain#"${keychain%%[![:space:]]*}"}"
    keychain="${keychain#\"}"
    keychain="${keychain%\"}"
    if [[ -n "$keychain" && "$keychain" != "$KEYCHAIN_PATH" ]]; then
        search_list+=("$keychain")
    fi
done < <(security list-keychains -d user)
security list-keychains -d user -s "${search_list[@]}"

if ! security find-identity -v -p codesigning "$KEYCHAIN_PATH" | grep -F -- "$BASIL_DEVELOPER_ID_CERT" > /dev/null; then
    echo "The imported keychain has no valid code-signing identity matching BASIL_DEVELOPER_ID_CERT." >&2
    exit 1
fi

printf '%s' "$BASIL_NOTARY_API_KEY_P8_BASE64" | base64 --decode > "$NOTARY_KEY_PATH"
xcrun notarytool store-credentials "$BASIL_NOTARY_KEYCHAIN_PROFILE" \
    --key "$NOTARY_KEY_PATH" \
    --key-id "$BASIL_NOTARY_API_KEY_ID" \
    --issuer "$BASIL_NOTARY_API_ISSUER_ID" \
    --keychain "$KEYCHAIN_PATH"

echo "BASIL_NOTARY_KEYCHAIN=$KEYCHAIN_PATH" >> "$GITHUB_ENV"
echo "Signing identity and notary credentials are ready in $KEYCHAIN_PATH."

#!/bin/bash
# cyberduck-sso.bash — Login to AWS SSO via acp and write temp credentials for Cyberduck
# Cyberduck must use the "S3 (Credentials from AWS Command Line Interface)" profile
# pointing to the profile name "cyberduck-sso" in Windows %USERPROFILE%\.aws\credentials

set -e

ENV_FILE="$(dirname "$0")/.env"
if [ ! -f "$ENV_FILE" ]; then
    echo "ERROR: Missing .env file at ${ENV_FILE}. Please create it with WIN_AWS_DIR defined."
    exit 1
fi
source "$ENV_FILE"

if [ -z "$WIN_AWS_DIR" ]; then
    echo "ERROR: WIN_AWS_DIR is not set in ${ENV_FILE}."
    exit 1
fi

if [ -z "$COMMON_FUNCTIONS" ] || [ ! -f "$COMMON_FUNCTIONS" ]; then
    echo "ERROR: COMMON_FUNCTIONS not set or file not found: ${COMMON_FUNCTIONS}"
    exit 1
fi
source "$COMMON_FUNCTIONS"

PROFILE="${1:-csna-operations-sso}"
CYBERDUCK_PROFILE="cyberduck-sso"
WIN_CREDENTIALS="${WIN_AWS_DIR}/credentials"

echo "=== Cyberduck SSO Connector ==="
echo ""

# Check if cyberduck-sso credentials are still valid
if aws sts get-caller-identity --profile "$CYBERDUCK_PROFILE" &>/dev/null; then
    echo "[✓] Credentials '${CYBERDUCK_PROFILE}' are still valid — nothing to do."
    exit 0
fi

echo "[!] Credentials expired or missing — renewing..."
echo ""

# Step 1: Switch to profile via acp
echo "[1/3] Switching to AWS profile via acp..."
acp "$PROFILE"

# If session expired, login
if ! aws sts get-caller-identity --profile "$PROFILE" &>/dev/null; then
    echo "Logging into SSO..."
    aws sso login --profile "$PROFILE"
fi

# Step 2: Extract temporary credentials
echo "[2/3] Extracting temporary credentials..."
CREDS=$(aws configure export-credentials --profile "$PROFILE" --format env-no-export)

ACCESS_KEY=$(echo "$CREDS" | grep AWS_ACCESS_KEY_ID | cut -d= -f2)
SECRET_KEY=$(echo "$CREDS" | grep AWS_SECRET_ACCESS_KEY | cut -d= -f2)
SESSION_TOKEN=$(echo "$CREDS" | grep AWS_SESSION_TOKEN | cut -d= -f2)

if [ -z "$ACCESS_KEY" ]; then
    echo "ERROR: Failed to extract credentials."
    exit 1
fi

echo "  Access Key: ${ACCESS_KEY:0:8}..."

# Step 3: Write credentials to Windows-side ~/.aws/credentials for Cyberduck
echo "[3/3] Writing credentials to Windows AWS credentials file..."
mkdir -p "$WIN_AWS_DIR"

write_credentials() {
    local creds_file="$1"
    if [ -f "$creds_file" ]; then
        sed -i "/^\[${CYBERDUCK_PROFILE}\]/,/^\[/{ /^\[${CYBERDUCK_PROFILE}\]/d; /^\[/!d; }" "$creds_file"
    fi
    cat >> "$creds_file" <<EOF
[${CYBERDUCK_PROFILE}]
aws_access_key_id=${ACCESS_KEY}
aws_secret_access_key=${SECRET_KEY}
aws_session_token=${SESSION_TOKEN}
region=${AWS_DEFAULT_REGION:-ca-central-1}
EOF
}

write_credentials "$WIN_CREDENTIALS"
write_credentials "$HOME/.aws/credentials"

echo ""
echo "=== Done! ==="
echo "Credentials written to: ${WIN_CREDENTIALS} [${CYBERDUCK_PROFILE}]"
echo ""
echo "In Cyberduck:"
echo "  1. Go to Preferences → Profiles → enable 'S3 (Credentials from AWS Command Line Interface)'"
echo "  2. Create a bookmark using that profile"
echo "  3. Set the profile name to: ${CYBERDUCK_PROFILE}"
echo ""
echo "Credentials are temporary — re-run this script when they expire."

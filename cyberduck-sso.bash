#!/bin/bash
# cyberduck-sso.bash — Login to AWS SSO via acp and write temp credentials for Cyberduck
# Cyberduck must use the "S3 (Credentials from AWS Command Line Interface)" profile
# pointing to the profile name "cyberduck-sso" in Windows %USERPROFILE%\.aws\credentials

set -e

source /home/nizar/workspace/PROC/xxxxuseful-scripts/common-functions.bash

PROFILE="${1:-csna-operations-sso}"
CYBERDUCK_PROFILE="cyberduck-sso"
WIN_AWS_DIR="/mnt/c/Users/nizar/.aws"
WIN_CREDENTIALS="${WIN_AWS_DIR}/credentials"

echo "=== Cyberduck SSO Connector ==="
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

# Remove existing cyberduck-sso profile block if present, then append new one
if [ -f "$WIN_CREDENTIALS" ]; then
    sed -i "/^\[${CYBERDUCK_PROFILE}\]/,/^\[/{ /^\[${CYBERDUCK_PROFILE}\]/d; /^\[/!d; }" "$WIN_CREDENTIALS"
fi

cat >> "$WIN_CREDENTIALS" <<EOF
[${CYBERDUCK_PROFILE}]
aws_access_key_id=${ACCESS_KEY}
aws_secret_access_key=${SECRET_KEY}
aws_session_token=${SESSION_TOKEN}
region=${AWS_DEFAULT_REGION:-ca-central-1}
EOF

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

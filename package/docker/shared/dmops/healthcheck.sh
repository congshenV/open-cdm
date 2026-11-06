#!/bin/sh
# dmops healthcheck.
# Every /v1/** request requires X-DmOps-User + X-DmOps-Signature, so the check
# signs a synthetic uid with the same secret the console proxy uses.
set -eu

PORT="${DMOPS_PORT:-8080}"

exec python - "$PORT" <<'PY'
import base64
import hashlib
import hmac
import os
import sys
import urllib.request

port = sys.argv[1]
uid = 'healthcheck'
headers = {}

secret = os.environ.get('DMOPS_IDENTITY_SECRET', '')
verify = os.environ.get('DMOPS_IDENTITY_VERIFY_ENABLED', 'true').lower() != 'false'
if verify and secret:
    digest = hmac.new(secret.encode('utf-8'), uid.encode('utf-8'), hashlib.sha1).digest()
    headers = {
        'X-DmOps-User': uid,
        'X-DmOps-Signature': base64.b64encode(digest).decode('utf-8'),
    }

request = urllib.request.Request(f'http://127.0.0.1:{port}/v1/ping', headers=headers)
with urllib.request.urlopen(request, timeout=3) as resp:
    if resp.status != 200:
        raise SystemExit(f'unhealthy: http {resp.status}')
PY

#!/usr/bin/env sh
# Upload CI security reports to DefectDojo via Python (multipart is unreliable with curl here).
set -eu

if [ -z "${DEFECTDOJO_URL:-}" ] || [ -z "${DEFECTDOJO_API_TOKEN:-}" ]; then
  echo "DEFECTDOJO_URL / DEFECTDOJO_API_TOKEN not set — skip"
  exit 0
fi

# Prefer python image helpers; fall back to downloading get-pip if needed — job uses python image.
python3 - <<'PY'
import json
import os
import sys
from pathlib import Path

try:
    import requests
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "--quiet", "requests"])
    import requests

base = os.environ["DEFECTDOJO_URL"].rstrip("/")
token = os.environ["DEFECTDOJO_API_TOKEN"].strip()
product = (os.environ.get("DEFECTDOJO_PRODUCT_NAME") or "backend-jarvis").strip().strip('"')
engagement = (os.environ.get("DEFECTDOJO_ENGAGEMENT_NAME") or f"ci-{os.environ.get('CI_COMMIT_REF_SLUG', 'pipeline')}").strip().strip('"')
product_type = (os.environ.get("DEFECTDOJO_PRODUCT_TYPE_NAME") or "Research and Development").strip().strip('"')
min_sev = os.environ.get("DEFECTDOJO_MINIMUM_SEVERITY") or "Info"

headers = {"Authorization": f"Token {token}"}
endpoint = f"{base}/api/v2/reimport-scan/"

print(f"DefectDojo target: {base}")
print(f"product_name=[{product}]")
print(f"engagement_name=[{engagement}]")
print(f"product_type_name=[{product_type}]")

uploads = [
    ("Gitleaks Scan", "gitleaks-report.json"),
    ("Semgrep JSON Report", "semgrep-report.json"),
    ("GitLab Secret Detection Report", "gl-secret-detection-report.json"),
    ("GitLab SAST Report", "gl-sast-report.json"),
    ("Checkov Scan", "checkov-report.json"),
]

fail = 0
for scan_type, filename in uploads:
    path = Path(filename)
    if not path.is_file():
        print(f"skip missing: {filename} ({scan_type})")
        continue
    print(f"==> Import {scan_type} ← {filename} ({path.stat().st_size} bytes)")
    data = {
        "scan_type": scan_type,
        "product_name": product,
        "product_type_name": product_type,
        "engagement_name": engagement,
        "test_title": scan_type,
        "auto_create_context": "true",
        "verified": "true",
        "active": "true",
        "close_old_findings": "true",
        # Keep manually/previously mitigated findings closed across reimports
        "do_not_reactivate": "true",
        "push_to_jira": "false",
        "minimum_severity": min_sev,
    }
    with path.open("rb") as fh:
        files = {"file": (filename, fh, "application/json")}
        resp = requests.post(endpoint, headers=headers, data=data, files=files, timeout=120)
    print(f"HTTP {resp.status_code}")
    print(resp.text[:800])
    # Debug: prove server saw product_name if still 400
    if resp.status_code == 400 and "product_name" in resp.text:
        print("DEBUG data keys sent:", sorted(data.keys()))
        print("DEBUG product_name value repr:", repr(data["product_name"]))
    if resp.status_code not in (200, 201):
        print(f"WARN: DefectDojo import failed for {scan_type} (HTTP {resp.status_code})", file=sys.stderr)
        fail = 1

if fail:
    print("One or more imports failed")
    sys.exit(1)
print(f"DefectDojo import complete → {base} (product={product}, engagement={engagement})")
PY

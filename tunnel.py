#!/usr/bin/env python3
"""
EnjoyAnime — Free HTTPS Tunnel Helper for Sandboxed Environments.
Creates an instant, free public HTTPS tunnel to port 8080 and saves it to .env (WEB_APP_URL).

Supported providers (100% free, no credit card):
1. Pinggy (default): connects via SSH on port 443, no registration required.
2. Ngrok: if ngrok is installed or NGROK_AUTHTOKEN is set.
"""

import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ENV_PATH = Path(__file__).parent / ".env"
PORT = int(os.getenv("WEB_PORT", "8080"))


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)


def update_env_file(key: str, value: str) -> None:
    """Updates or appends a KEY=VALUE pair in .env file."""
    if not ENV_PATH.exists():
        ENV_PATH.write_text(f"{key}={value}\n", encoding="utf-8")
        return

    content = ENV_PATH.read_text(encoding="utf-8")
    pattern = rf"^{key}=.*$"
    if re.search(pattern, content, flags=re.MULTILINE):
        new_content = re.sub(pattern, f"{key}={value}", content, flags=re.MULTILINE)
    else:
        new_content = content.rstrip() + f"\n{key}={value}\n"
    ENV_PATH.write_text(new_content, encoding="utf-8")
    print(f"✅ Updated .env: {key}={value}")


def start_pinggy_tunnel():
    """Starts a free Pinggy SSH tunnel on port 443."""
    ssh_bin = shutil.which("ssh")
    if not ssh_bin:
        print("❌ 'ssh' binary not found. Please install openssh-client.")
        return False

    cmd = [
        ssh_bin,
        "-p", "443",
        "-o", "StrictHostKeyChecking=no",
        "-o", "ServerAliveInterval=30",
        "-R0:localhost:8080",
        "qr@a.pinggy.io"
    ]
    print(f"🚀 Starting Pinggy tunnel to localhost:{PORT} via SSH port 443…")
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

    https_url = None
    for line in iter(proc.stdout.readline, ""):
        print(line, end="")
        match = re.search(r"https://[a-zA-Z0-9.-]+\.(?:run\.pinggy-free\.link|run\.pinggy\.link|a\.pinggy\.link|free\.pinggy\.net|pinggy\.link|pinggy\.net)", line)
        if match:
            https_url = match.group(0)
            print("\n" + "=" * 50)
            print(f"🎉 PUBLIC HTTPS URL: {https_url}")
            print("=" * 50 + "\n")
            update_env_file("WEB_APP_URL", https_url)
            update_env_file("MINI_APP_URL", https_url)
            break

    if https_url:
        proc.wait()
        return True
    return False


def start_ngrok_tunnel():
    """Starts Ngrok tunnel and saves public HTTPS URL to .env."""
    ngrok_bin = shutil.which("ngrok")
    if not ngrok_bin:
        print("❌ 'ngrok' binary not found.")
        return False

    authtoken = os.getenv("NGROK_AUTHTOKEN")
    if authtoken:
        subprocess.run([ngrok_bin, "config", "add-authtoken", authtoken], check=False)

    cmd = [ngrok_bin, "http", str(PORT), "--log=stdout"]
    print(f"🚀 Starting Ngrok tunnel to localhost:{PORT}…")
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

    https_url = None
    import json
    import urllib.request

    # Wait for Ngrok API on port 4040
    for _ in range(25):
        time.sleep(1)
        try:
            req = urllib.request.Request("http://127.0.0.1:4040/api/tunnels")
            with urllib.request.urlopen(req, timeout=2) as resp:
                data = json.loads(resp.read().decode())
                for t in data.get("tunnels", []):
                    url = t.get("public_url")
                    if url and url.startswith("https://"):
                        https_url = url
                        break
                if https_url:
                    break
        except Exception:
            pass

    if https_url:
        print("\n" + "=" * 50)
        print(f"🎉 NGROK PUBLIC HTTPS URL: {https_url}")
        print("=" * 50 + "\n")
        update_env_file("WEB_APP_URL", https_url)
        update_env_file("MINI_APP_URL", https_url)
        proc.wait()
        return True

    return False


if __name__ == "__main__":
    provider = sys.argv[1] if len(sys.argv) > 1 else "pinggy"
    if provider == "ngrok":
        if not start_ngrok_tunnel():
            start_pinggy_tunnel()
    else:
        if not start_pinggy_tunnel():
            start_ngrok_tunnel()

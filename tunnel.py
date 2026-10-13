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


def start_cloudflared_tunnel() -> bool:
    """Starts Cloudflare Quick Tunnel (no warning page, stable) if binary exists."""
    cf_bin = shutil.which("cloudflared")
    if not cf_bin:
        for candidate in ["./cloudflared", "/usr/local/bin/cloudflared", "/tmp/cloudflared", "cloudflared.exe"]:
            if Path(candidate).is_file():
                cf_bin = candidate
                break
    if not cf_bin:
        return False

    cmd = [cf_bin, "tunnel", "--url", f"http://localhost:{PORT}"]
    print(f"🚀 Starting Cloudflare Quick Tunnel to localhost:{PORT}…")
    env = os.environ.copy()
    env["TUNNEL_TRANSPORT_PROTOCOL"] = "http2"
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env)
    except Exception as e:
        print(f"❌ Failed to spawn cloudflared: {e}")
        return False

    https_url = None
    try:
        for line in iter(proc.stdout.readline, ""):
            print(line, end="")
            if not https_url:
                match = re.search(r"https://[a-zA-Z0-9.-]+\.trycloudflare\.com", line)
                if match:
                    https_url = match.group(0)
                    print("\n" + "=" * 50)
                    print(f"🎉 CLOUDFLARE PUBLIC HTTPS URL: {https_url}")
                    print("=" * 50 + "\n")
                    update_env_file("WEB_APP_URL", https_url)
                    update_env_file("MINI_APP_URL", https_url)
    finally:
        if proc.poll() is None:
            proc.kill()

    return bool(https_url)


def start_pinggy_tunnel() -> bool:
    """Starts a free Pinggy SSH tunnel on port 443 with continuous stdout reading."""
    ssh_bin = shutil.which("ssh")
    if not ssh_bin:
        print("❌ 'ssh' binary not found. Please install openssh-client.")
        return False

    cmd = [
        ssh_bin,
        "-p", "443",
        "-o", "StrictHostKeyChecking=no",
        "-o", "ServerAliveInterval=30",
        "-o", "TCPKeepAlive=yes",
        f"-R0:localhost:{PORT}",
        "qr@a.pinggy.io",
    ]
    print(f"🚀 Starting Pinggy tunnel to localhost:{PORT} via SSH port 443…")
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    except Exception as e:
        print(f"❌ Failed to spawn ssh: {e}")
        return False

    https_url = None
    try:
        for line in iter(proc.stdout.readline, ""):
            print(line, end="")
            if not https_url:
                match = re.search(
                    r"https://[a-zA-Z0-9.-]+\.(?:run\.pinggy-free\.link|run\.pinggy\.link|a\.pinggy\.link|free\.pinggy\.net|pinggy\.link|pinggy\.net)",
                    line,
                )
                if match:
                    https_url = match.group(0)
                    print("\n" + "=" * 50)
                    print(f"🎉 PUBLIC HTTPS URL: {https_url}")
                    print("=" * 50 + "\n")
                    update_env_file("WEB_APP_URL", https_url)
                    update_env_file("MINI_APP_URL", https_url)
    finally:
        if proc.poll() is None:
            proc.kill()

    return bool(https_url)


def start_ngrok_tunnel() -> bool:
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
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    except Exception as e:
        print(f"❌ Failed to spawn ngrok: {e}")
        return False

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
        try:
            for line in iter(proc.stdout.readline, ""):
                print(line, end="")
        finally:
            if proc.poll() is None:
                proc.kill()
        return True

    if proc.poll() is None:
        proc.kill()
    return False


def run_tunnel_supervisor():
    """Runs tunnel in an automatic supervision loop. Reconnects on disconnection."""
    requested = sys.argv[1] if len(sys.argv) > 1 else None

    while True:
        try:
            if requested == "cloudflared" or (not requested and shutil.which("cloudflared")):
                if start_cloudflared_tunnel():
                    pass
            elif requested == "ngrok":
                if not start_ngrok_tunnel():
                    start_pinggy_tunnel()
            else:
                # Default: try cloudflared first if installed, else pinggy
                if not start_cloudflared_tunnel():
                    start_pinggy_tunnel()
        except KeyboardInterrupt:
            print("\n🛑 Tunnel stopped by user.")
            break
        except Exception as e:
            print(f"⚠️ Tunnel error: {e}")

        print("🔄 Tunnel disconnected. Reconnecting in 3 seconds…")
        time.sleep(3)


if __name__ == "__main__":
    run_tunnel_supervisor()

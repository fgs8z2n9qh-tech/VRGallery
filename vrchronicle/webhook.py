"""Discord webhook sharing (stdlib only, mirrors the AjazzDock urllib approach)."""
import json
import os
import urllib.request
import uuid

from . import imaging


def send_photo(url, path, caption):
    """Blocking; run on a worker thread. Returns (ok, message)."""
    if not url or not url.startswith("https://"):
        return False, "No webhook URL configured (see Settings)."
    if not os.path.exists(path):
        return False, "File not found."
    up_path, temp = imaging.shrink_for_upload(path)
    try:
        boundary = "----vrchronicle" + uuid.uuid4().hex
        payload = {"content": caption or ""}
        with open(up_path, "rb") as f:
            file_bytes = f.read()
        fname = os.path.basename(up_path if temp else path)
        ctype = "image/jpeg" if fname.lower().endswith((".jpg", ".jpeg")) else "image/png"
        parts = []
        parts.append(f"--{boundary}\r\n"
                     f'Content-Disposition: form-data; name="payload_json"\r\n'
                     f"Content-Type: application/json\r\n\r\n"
                     f"{json.dumps(payload, ensure_ascii=False)}\r\n".encode("utf-8"))
        parts.append(f"--{boundary}\r\n"
                     f'Content-Disposition: form-data; name="files[0]"; filename="{fname}"\r\n'
                     f"Content-Type: {ctype}\r\n\r\n".encode("utf-8"))
        parts.append(file_bytes)
        parts.append(f"\r\n--{boundary}--\r\n".encode("utf-8"))
        body = b"".join(parts)
        req = urllib.request.Request(url, data=body, method="POST", headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "User-Agent": "VRChronicle/1.1",
        })
        with urllib.request.urlopen(req, timeout=20) as resp:
            if 200 <= resp.status < 300:
                return True, "Sent to Discord."
            return False, f"Webhook error: HTTP {resp.status}"
    except Exception as e:
        return False, f"Webhook error: {e.__class__.__name__}"
    finally:
        if temp:
            try:
                os.remove(up_path)
            except OSError:
                pass

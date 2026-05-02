import os
import json
import urllib.request
import urllib.error

# Parse .env to populate os.environ without external libraries
_env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
if os.path.exists(_env_path):
    with open(_env_path) as _f:
        for _line in _f:
            if _line.strip() and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.strip().split("=", 1)
                os.environ[_k] = _v

_URL = "http://20.207.122.201/evaluation-service/logs"



def Log(stack, level, pkg, message):
    tok = os.environ.get("AUTH_TOKEN", "")
    body = json.dumps({
        "stack": stack,
        "level": level,
        "package": pkg,
        "message": message
    }).encode()
    req = urllib.request.Request(
        _URL,
        data=body,
        headers={
            "Authorization": f"Bearer {tok}",
            "Content-Type": "application/json"
        },
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read())
    except Exception:
        pass

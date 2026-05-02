import os
import json
import urllib.request
import urllib.error

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

"""Authenticated local container liveness check; never print the token."""

import json
import os
import sys
from urllib.request import Request, urlopen


def main():
    token = os.environ.get("DEMO_BEARER_TOKEN", "")
    request = Request(
        f"http://127.0.0.1:{int(os.environ.get('PORT', '8080'))}/health",
        headers={"Authorization": f"Bearer {token}"} if token else {},
    )
    try:
        with urlopen(request, timeout=4) as response:
            return 0 if response.status == 200 and json.load(response) == {"status": "ok"} else 1
    except Exception:
        return 1


if __name__ == "__main__":
    sys.exit(main())

"""Copy your planner (data/sem5.json and data/progress.json) to your private link on the
HeadStart site, so it can be shown online. Your laptop copy stays the real one; run this
again whenever you want the online copy updated.

    python publish.py

The first run asks for the site's address and its publish token (the PUBLISH_TOKEN
environment variable on Render) and saves them, with a new private planner id, in .publish.json (kept out
of git).
"""

from __future__ import annotations

import json
import secrets
import sys
import urllib.error
import urllib.request
from pathlib import Path

from plan import DEFAULT_INPUT, DEFAULT_PROGRESS

CONFIG = Path(".publish.json")


def main() -> None:
    if CONFIG.exists():
        cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    else:
        cfg = {"site": input("Site address (e.g. https://you-headstart.hf.space): ").strip().rstrip("/"),
               "token": input("Publish token: ").strip(),
               "id": "".join(secrets.choice("abcdefghjkmnpqrstuvwxyz23456789") for _ in range(12))}
        CONFIG.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    body = {"id": cfg["id"],
            "setup": json.loads(Path(DEFAULT_INPUT).read_text(encoding="utf-8")),
            "progress": json.loads(Path(DEFAULT_PROGRESS).read_text(encoding="utf-8"))}
    req = urllib.request.Request(f"{cfg['site']}/api/publish", data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "X-Publish-Token": cfg["token"]})
    try:
        with urllib.request.urlopen(req, timeout=120) as res:
            url = json.load(res)["url"]
    except urllib.error.HTTPError as e:
        sys.exit(f"Publishing failed: {e.code} {e.read().decode(errors='replace')}")
    print(f"Published. Your planner online: {cfg['site']}{url}")


if __name__ == "__main__":
    main()

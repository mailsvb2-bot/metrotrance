from __future__ import annotations

import threading
import webbrowser
from pathlib import Path

import uvicorn

from metrotrance.api import create_app
from metrotrance.config import get_settings


def main() -> None:
    settings = get_settings(Path.cwd())
    app = create_app(settings)
    url = f"http://{settings.host}:{settings.port}"
    if settings.open_browser:
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host=settings.host, port=settings.port, log_level="info")


if __name__ == "__main__":
    main()

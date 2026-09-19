"""Start the local fake-only operator console: python -m web --port 8787."""
import argparse

import uvicorn

from .app import create_app


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("Choose a port between 1024 and 65535")
    print(f"Guitarra console: http://127.0.0.1:{args.port} — FAKE ARMS ONLY", flush=True)
    uvicorn.run(create_app(port=args.port), host="127.0.0.1", port=args.port,
                access_log=False, log_level="info")


if __name__ == "__main__":
    main()

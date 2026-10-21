from __future__ import annotations

import argparse
import json
import sys

from pydantic import ValidationError

from .config import Config, load_config, resolve_paths
from .engine import Busy, Engine


def main(argv=None):
    parser = argparse.ArgumentParser(description="Rundown: personal Slack digests")
    subcommands = parser.add_subparsers(dest="command", required=True)
    for command in ("check", "run", "serve"):
        sub = subcommands.add_parser(command)
        sub.add_argument("--config", default="config.toml", help="Path to TOML configuration")
        if command == "serve":
            sub.add_argument("--host", choices=["127.0.0.1", "localhost", "::1"], default="127.0.0.1")
            sub.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
    except FileNotFoundError:
        if args.command == "serve":
            config = resolve_paths(Config(), args.config)
        else:
            print("Configuration not found. Run 'python -m rundown serve' to complete setup in your browser.", file=sys.stderr)
            return 2
    except ValidationError as exc:
        # Pydantic's default rendering can expose input values, including secrets.
        print("Invalid configuration:", file=sys.stderr)
        for error in exc.errors(include_input=False, include_url=False, include_context=False):
            print(f"  {'.'.join(map(str, error['loc']))}: {error['msg']}", file=sys.stderr)
        return 2
    except (ValueError, OSError):
        print("Could not read configuration. Check TOML syntax and file permissions.", file=sys.stderr)
        return 2
    try:
        engine = Engine(config)
        if args.command == "check":
            result = engine.check()
            print(json.dumps(result, indent=2))
            return 0 if result["ready"] else 1
        if args.command == "run":
            result = engine.run()
            print(json.dumps(result, indent=2))
            return 0 if result["status"] == "completed" else 1
        import uvicorn
        from .web import create_app
        uvicorn.run(create_app(engine=engine, config_path=args.config), host=args.host, port=args.port, log_level="warning")
        return 0
    except Busy as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except OSError:
        print("Local file or server access failed. Check paths, permissions, and port availability.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

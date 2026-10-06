import argparse
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Local circuit research workbench")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--index-only", action="store_true")
    args = parser.parse_args()
    import os
    os.environ["CIRCUIT_ROOT"] = str(args.root.resolve())
    from .settings import Settings
    from .app import create_app
    app = create_app(Settings.local(), background=not args.index_only)
    if args.index_only:
        app.state.retrieval.build()
        app.state.neo4j.sync()
        print(app.state.retrieval.status)
        print(app.state.neo4j.health())
        return
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()

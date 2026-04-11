"""
tibet-mux CLI — run a standalone mux server or interact as a client.

Usage:
    # Start server
    tibet-mux serve --port 8443 --agent my_node

    # Client commands
    tibet-mux open --target gemini --intent chat
    tibet-mux send --channel ch-xxx --payload '{"text":"hi"}'
    tibet-mux channels
    tibet-mux status
    tibet-mux intents
"""

import argparse
import json
import sys


def main():
    parser = argparse.ArgumentParser(
        prog="tibet-mux",
        description="Single-port channel multiplexer with intent-based routing",
    )
    sub = parser.add_subparsers(dest="command")

    # serve
    serve_p = sub.add_parser("serve", help="Start mux server")
    serve_p.add_argument("--port", type=int, default=8443)
    serve_p.add_argument("--host", default="0.0.0.0")
    serve_p.add_argument("--agent", default="node")

    # status
    status_p = sub.add_parser("status", help="Check server status")
    status_p.add_argument("--url", default="http://localhost:8000")

    # intents
    intents_p = sub.add_parser("intents", help="List known intents")
    intents_p.add_argument("--url", default="http://localhost:8000")

    # open
    open_p = sub.add_parser("open", help="Open a channel")
    open_p.add_argument("--url", default="http://localhost:8000")
    open_p.add_argument("--agent", required=True)
    open_p.add_argument("--target", required=True)
    open_p.add_argument("--intent", required=True)

    # send
    send_p = sub.add_parser("send", help="Send on a channel")
    send_p.add_argument("--url", default="http://localhost:8000")
    send_p.add_argument("--channel", required=True)
    send_p.add_argument("--payload", required=True, help="JSON payload")

    # channels
    ch_p = sub.add_parser("channels", help="List open channels")
    ch_p.add_argument("--url", default="http://localhost:8000")
    ch_p.add_argument("--agent", required=True)

    # close
    close_p = sub.add_parser("close", help="Close a channel")
    close_p.add_argument("--url", default="http://localhost:8000")
    close_p.add_argument("--channel", required=True)
    close_p.add_argument("--reason", default="client_close")

    args = parser.parse_args()

    if args.command == "serve":
        try:
            import uvicorn
            from tibet_mux.server import create_app
        except ImportError:
            print("Error: tibet-mux[server] required. Install with:")
            print("  pip install tibet-mux[server]")
            sys.exit(1)

        app = create_app(agent=args.agent)
        print(f"Tibet-Mux server starting on {args.host}:{args.port}")
        print(f"Agent: {args.agent}")
        print(f"Endpoints: /api/mux/open, /api/mux/send, /api/mux/ws, ...")
        uvicorn.run(app, host=args.host, port=args.port)

    elif args.command == "status":
        from tibet_mux.client import MuxClient
        client = MuxClient(args.url, agent="cli")
        _print_json(client.status())

    elif args.command == "intents":
        from tibet_mux.client import MuxClient
        client = MuxClient(args.url, agent="cli")
        data = client.intents()
        for name, info in data.get("intents", {}).items():
            print(f"  {name:20s} → {info['backend']:10s}  {info['description']}")

    elif args.command == "open":
        from tibet_mux.client import MuxClient
        client = MuxClient(args.url, agent=args.agent)
        result = client.open(target=args.target, intent=args.intent)
        _print_json(result)

    elif args.command == "send":
        from tibet_mux.client import MuxClient
        client = MuxClient(args.url, agent="cli")
        payload = json.loads(args.payload)
        result = client.send(args.channel, payload)
        _print_json(result)

    elif args.command == "channels":
        from tibet_mux.client import MuxClient
        client = MuxClient(args.url, agent=args.agent)
        _print_json(client.channels())

    elif args.command == "close":
        from tibet_mux.client import MuxClient
        client = MuxClient(args.url, agent="cli")
        result = client.close(args.channel, args.reason)
        _print_json(result)

    else:
        parser.print_help()


def _print_json(data):
    print(json.dumps(data, indent=2))


if __name__ == "__main__":
    main()

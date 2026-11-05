"""Single-client-at-a-time TCP server using one JSON object per line."""

import argparse
import json
from pathlib import Path
import socketserver

from pv_model import RingModel


def dispatch(model, request):
    operation = request["op"]
    if operation == "list":
        return model.list_pvs()
    if operation == "get":
        return model.get(request["pv"])
    if operation == "set":
        return model.set(request["pv"], request["value"])
    raise ValueError(f"Unknown operation: {operation}")


class PVHandler(socketserver.StreamRequestHandler):
    def handle(self):
        for line in self.rfile:
            try:
                result = dispatch(self.server.model, json.loads(line))
                response = {"ok": True, "result": result}
            except Exception as error:
                response = {"ok": False, "error": str(error)}
            self.wfile.write((json.dumps(response, allow_nan=False) + "\n").encode())
            self.wfile.flush()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--lattice", type=Path,
                        default=Path(__file__).with_name("toy_ring.bmad"))
    args = parser.parse_args()
    model = RingModel(args.lattice)
    with socketserver.TCPServer((args.host, args.port), PVHandler) as server:
        server.model = model
        print(f"PV server listening on {args.host}:{args.port}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()

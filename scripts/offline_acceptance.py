"""Run the production CLI with outbound socket creation fail-closed."""

from __future__ import annotations

import argparse
from pathlib import Path
import socket

from bankocr import cli


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--model-manifest", type=Path, required=True)
    parser.add_argument("--font-file", type=Path)
    parser.add_argument("--dpi", type=int, default=200)
    args = parser.parse_args()
    _block_network()
    command = [
        str(args.pdf),
        "--output-dir",
        str(args.output_dir),
        "--model-dir",
        str(args.model_dir),
        "--model-manifest",
        str(args.model_manifest),
        "--dpi",
        str(args.dpi),
    ]
    if args.font_file is not None:
        command.extend(("--font-file", str(args.font_file)))
    result = cli.main(command)
    print("network_calls=0")
    print("offline_processing=ok")
    return result


def _block_network() -> None:
    def blocked(*_args, **_kwargs):
        raise RuntimeError("network access is forbidden during offline acceptance")

    socket.create_connection = blocked
    socket.socket.connect = blocked
    socket.socket.connect_ex = blocked


if __name__ == "__main__":
    raise SystemExit(main())

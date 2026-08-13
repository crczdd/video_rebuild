from __future__ import annotations

import argparse
import logging
import time

from dingtalk.factory import make_client
from dingtalk.settings import DingtalkSettings

from .llm_client import LLMClient
from .service import run_cycle
from .settings import VideoRemakeSettings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="DingTalk AI video-remake prompt worker")
    parser.add_argument("--once", action="store_true", help="run one polling cycle and exit")
    parser.add_argument("--interval", type=int, help="poll interval in seconds")
    parser.add_argument("--dry-run", action="store_true", help="read and evaluate only")
    parser.add_argument("--env", default=".env", help="environment file path")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # Avoid logging request URLs/query parameters such as operatorId.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    settings = VideoRemakeSettings.from_env(args.env)
    interval = args.interval if args.interval is not None else settings.poll_interval_seconds
    if interval <= 0:
        raise ValueError("--interval must be greater than zero")
    llm = None if args.dry_run else LLMClient(settings)
    dingtalk_settings = DingtalkSettings.from_env(args.env)

    while True:
        try:
            with make_client("video_remake", settings=dingtalk_settings) as client:
                run_cycle(client, llm, dry_run=args.dry_run)
        except Exception:
            logging.getLogger(__name__).exception("cycle failed")
            if args.once:
                return 1
        if args.once:
            return 0
        time.sleep(interval)


if __name__ == "__main__":
    raise SystemExit(main())

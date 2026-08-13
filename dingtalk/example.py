from __future__ import annotations

import argparse
from pathlib import Path

from dingtalk.attachments import attachment_value
from dingtalk.factory import make_client


def main() -> int:
    parser = argparse.ArgumentParser(description="DingTalk AI Table integration example")
    parser.add_argument("--workflow", choices=["infringement", "exaggeration"], default="infringement")
    parser.add_argument("--list", action="store_true", help="List fields and recent records")
    parser.add_argument("--image", type=Path, help="Upload an image and create a test record")
    parser.add_argument("--attachment-field", default="侵权截图1")
    parser.add_argument("--url", default="https://www.douyin.com/video/TEST")
    args = parser.parse_args()

    client = make_client(args.workflow)
    with client:
        print("access token: OK" if client.get_access_token() else "access token: missing")
        if args.list:
            print("fields:")
            for field in client.list_fields():
                print(f"- {field.field_name}: {field.ui_type}")
            print("records:", len(client.list_records(page_size=10, max_pages=1)))
        if args.image:
            uploaded = client.upload_file(args.image)
            record = client.create_record(
                {
                    "视频链接": args.url,
                    args.attachment_field: attachment_value(uploaded.file_token),
                }
            )
            print("created record:", record.get("record_id"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

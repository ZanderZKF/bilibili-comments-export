#!/usr/bin/env python3
import asyncio
import csv
import hashlib
import json
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

try:
    from bilibili_api.comment import Comment, CommentResourceType
except ImportError:
    Comment = None
    CommentResourceType = None


BASE_API = "https://api.bilibili.com"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
DEFAULT_URL = (
    "https://www.bilibili.com/video/BV1eiwFz1EQx/"
    "?spm_id_from=333.1007.tianma.1-3-3.click"
    "&vd_source=69660ef3e207db89c48f0721bb683627"
)
DEFAULT_BVID = "BV1eiwFz1EQx"
DEFAULT_OID = 116210842803834
TYPE_VIDEO = 1
PAGE_SIZE = 20
MIXIN_KEY_ENC_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35,
    27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13,
    37, 48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4,
    22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36, 20, 34, 44, 52,
]

ssl._create_default_https_context = ssl._create_unverified_context
WBI_MIXIN_KEY = None


def build_headers():
    return {
        "User-Agent": USER_AGENT,
        "Referer": DEFAULT_URL,
        "Origin": "https://www.bilibili.com",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }


def get_mixin_key(orig):
    return "".join(orig[index] for index in MIXIN_KEY_ENC_TAB)[:32]


def get_wbi_mixin_key():
    global WBI_MIXIN_KEY
    if WBI_MIXIN_KEY:
        return WBI_MIXIN_KEY
    req = urllib.request.Request(
        f"{BASE_API}/x/web-interface/nav",
        headers=build_headers(),
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    data = payload["data"]["wbi_img"]
    img_key = data["img_url"].rsplit("/", 1)[1].split(".")[0]
    sub_key = data["sub_url"].rsplit("/", 1)[1].split(".")[0]
    WBI_MIXIN_KEY = get_mixin_key(img_key + sub_key)
    return WBI_MIXIN_KEY


def sign_wbi_params(params, mixin_key):
    signed = dict(params)
    signed["wts"] = int(time.time())
    signed = {
        key: "".join(ch for ch in str(value) if ch not in "!'()*")
        for key, value in sorted(signed.items())
    }
    query = urllib.parse.urlencode(signed)
    signed["w_rid"] = hashlib.md5((query + mixin_key).encode("utf-8")).hexdigest()
    return signed


def api_get(path, params, use_wbi=False):
    if use_wbi:
        query = urllib.parse.urlencode(sign_wbi_params(params, get_wbi_mixin_key()))
    else:
        query = urllib.parse.urlencode(params)
    url = f"{BASE_API}{path}?{query}"
    headers = build_headers()

    last_error = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=20) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            if payload.get("code") != 0:
                raise RuntimeError(
                    f"API returned code={payload.get('code')} message={payload.get('message')}"
                )
            return payload["data"]
        except (urllib.error.HTTPError, urllib.error.URLError, RuntimeError, json.JSONDecodeError) as exc:
            last_error = exc
            time.sleep(1 + attempt)

    raise RuntimeError(f"Failed to fetch {url}: {last_error}")


def iso_time(timestamp):
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).astimezone().isoformat()


def normalize_comment(item):
    member = item.get("member") or {}
    level_info = member.get("level_info") or {}
    content = item.get("content") or {}
    reply_control = item.get("reply_control") or {}

    return {
        "comment_id": str(item.get("rpid_str") or item.get("rpid") or ""),
        "root_id": str(item.get("root_str") or item.get("root") or ""),
        "parent_id": str(item.get("parent_str") or item.get("parent") or ""),
        "dialog_id": str(item.get("dialog_str") or item.get("dialog") or ""),
        "oid": str(item.get("oid_str") or item.get("oid") or ""),
        "type": item.get("type"),
        "author_mid": str(member.get("mid") or ""),
        "author_name": member.get("uname") or "",
        "author_level": level_info.get("current_level"),
        "author_sign": member.get("sign") or "",
        "author_avatar": member.get("avatar") or "",
        "like_count": item.get("like", 0),
        "reply_count": item.get("rcount", 0),
        "sub_reply_count": item.get("count", 0),
        "created_at": item.get("ctime"),
        "created_at_iso": iso_time(item["ctime"]) if item.get("ctime") else "",
        "message": content.get("message") or "",
        "location": reply_control.get("location") or "",
    }


def fetch_video_meta(bvid):
    data = api_get("/x/web-interface/view", {"bvid": bvid})
    owner = data.get("owner") or {}
    return {
        "bvid": data.get("bvid", bvid),
        "aid": data.get("aid", DEFAULT_OID),
        "cid": data.get("cid"),
        "title": data.get("title", ""),
        "desc": data.get("desc", ""),
        "pubdate": data.get("pubdate"),
        "pubdate_iso": iso_time(data["pubdate"]) if data.get("pubdate") else "",
        "owner_mid": owner.get("mid"),
        "owner_name": owner.get("name", ""),
        "stat": data.get("stat") or {},
    }


def fetch_root_comments(oid):
    roots = []
    seen = set()
    next_cursor = 0
    total_visible = None

    while True:
        data = api_get(
            "/x/v2/reply/wbi/main",
            {"oid": oid, "type": TYPE_VIDEO, "mode": 3, "next": next_cursor, "ps": PAGE_SIZE},
            use_wbi=True,
        )
        cursor = data.get("cursor") or {}
        total_visible = cursor.get("all_count", total_visible)

        for reply in data.get("replies") or []:
            reply_id = str(reply.get("rpid_str") or reply.get("rpid") or "")
            if reply_id and reply_id not in seen:
                roots.append(reply)
                seen.add(reply_id)

        if cursor.get("is_end"):
            break

        next_cursor = cursor.get("next")
        if next_cursor is None:
            break
        time.sleep(0.2)

    return roots, total_visible or len(roots)


def fetch_sub_replies(oid, root_id):
    if Comment is None or CommentResourceType is None:
        raise RuntimeError(
            "缺少 bilibili-api-python 依赖。请先激活 .venv-bili，"
            "或安装 bilibili-api-python 后再运行脚本。"
        )

    async def _fetch():
        replies = []
        page = 1
        comment = Comment(oid, CommentResourceType.VIDEO, int(root_id))

        while True:
            data = await comment.get_sub_comments(page_index=page, page_size=PAGE_SIZE)
            total_count = ((data.get("page") or {}).get("count")) or 0
            chunk = data.get("replies") or []
            if not chunk:
                break

            replies.extend(chunk)
            if len(replies) >= total_count:
                break

            page += 1
            await asyncio.sleep(0.2)

        return replies

    return asyncio.run(_fetch())


def build_outputs(video_url, bvid, oid):
    video_meta = fetch_video_meta(bvid)
    roots, visible_comment_total = fetch_root_comments(oid)

    hierarchical_comments = []
    flat_rows = []
    total_sub_replies = 0

    for index, root in enumerate(roots, start=1):
        normalized_root = normalize_comment(root)
        normalized_root["order"] = index

        root_id = root.get("rpid_str") or root.get("rpid")
        sub_replies_raw = fetch_sub_replies(oid, root_id)
        normalized_sub_replies = []

        flat_rows.append(
            {
                "level": "root",
                "comment_id": normalized_root["comment_id"],
                "root_comment_id": normalized_root["comment_id"],
                "parent_id": normalized_root["parent_id"],
                "author_mid": normalized_root["author_mid"],
                "author_name": normalized_root["author_name"],
                "like_count": normalized_root["like_count"],
                "created_at": normalized_root["created_at"],
                "created_at_iso": normalized_root["created_at_iso"],
                "location": normalized_root["location"],
                "message": normalized_root["message"],
            }
        )

        for sub_index, reply in enumerate(sub_replies_raw, start=1):
            normalized_reply = normalize_comment(reply)
            normalized_reply["order"] = sub_index
            normalized_sub_replies.append(normalized_reply)
            total_sub_replies += 1

            flat_rows.append(
                {
                    "level": "reply",
                    "comment_id": normalized_reply["comment_id"],
                    "root_comment_id": normalized_root["comment_id"],
                    "parent_id": normalized_reply["parent_id"],
                    "author_mid": normalized_reply["author_mid"],
                    "author_name": normalized_reply["author_name"],
                    "like_count": normalized_reply["like_count"],
                    "created_at": normalized_reply["created_at"],
                    "created_at_iso": normalized_reply["created_at_iso"],
                    "location": normalized_reply["location"],
                    "message": normalized_reply["message"],
                }
            )

        normalized_root["replies"] = normalized_sub_replies
        hierarchical_comments.append(normalized_root)

    payload = {
        "video": {
            "url": video_url,
            "oid": oid,
            **video_meta,
        },
        "scraped_at": datetime.now().astimezone().isoformat(),
        "root_comment_count": len(hierarchical_comments),
        "reply_comment_count": total_sub_replies,
        "comment_count_total": len(hierarchical_comments) + total_sub_replies,
        "visible_comment_count_from_root_api": visible_comment_total,
        "comments": hierarchical_comments,
    }
    return payload, flat_rows


def write_json(data, output_path):
    output_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def write_csv(rows, output_path):
    if not rows:
        output_path.write_text("", encoding="utf-8")
        return

    fieldnames = list(rows[0].keys())
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main():
    video_url = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_URL
    bvid = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_BVID
    oid = int(sys.argv[3]) if len(sys.argv) > 3 else DEFAULT_OID

    json_path = Path.cwd() / f"{bvid}_comments.json"
    csv_path = Path.cwd() / f"{bvid}_comments_flat.csv"

    payload, flat_rows = build_outputs(video_url, bvid, oid)
    write_json(payload, json_path)
    write_csv(flat_rows, csv_path)

    print(f"JSON saved to: {json_path}")
    print(f"CSV saved to: {csv_path}")
    print(f"Root comments: {payload['root_comment_count']}")
    print(f"Reply comments: {payload['reply_comment_count']}")
    print(f"Total comments: {payload['comment_count_total']}")


if __name__ == "__main__":
    main()

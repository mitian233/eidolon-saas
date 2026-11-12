#!/usr/bin/env python3
"""Export this repo's characters as Cherry Studio assistants (助手订阅 JSON).

Reads `characters/characters.toml` and each character's sheet, and writes the JSON array
Cherry Studio's 助手订阅 expects: one object per character with `description`, `emoji`,
`group`, `id`, `name` and `prompt`. Nothing in the repo is modified.

The sheets are written for this backend, which answers in Japanese with Chinese subtitles
and voices the Japanese (`backend/src/eidolon/reply_format.py`). Cherry Studio has no
speech synthesis, so by default the exported prompt asks for plain Chinese replies, keeping
the sheet's Japanese interjections and forms of address; `--lang ja` keeps the backend's
tagged format for use with a reader that parses it.

Usage:
    python3 scripts/export_cherry_assistants.py                 # -> corpus/cherry/assistants.json
    python3 scripts/export_cherry_assistants.py --lang ja -o /tmp/cherry.json
    python3 scripts/export_cherry_assistants.py --names         # one 开场白 per character

Then point Cherry Studio at it: 设置 → 数据设置 → 助手订阅, with the file served over HTTP
(`python3 -m http.server 8899 --directory corpus/cherry`), or paste a single prompt by hand.
"""

from __future__ import annotations

import argparse
import json
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHARACTERS = ROOT / "characters" / "characters.toml"

# Cherry Studio has no TTS, so the sheet's Japanese 口癖 are kept but the reply language is
# Chinese: the backend's <ja>/<zh> tags would show up as raw text there.
ZH_RULES = """# 对话方式
- 无论用户用什么语言说话，你都只用简体中文回答。
- 像真人当面说话那样，接对方一句话，通常只回一两句；被要求讲一段事情时可以多说几句，讲到自然的停顿处就停下，剩下的等对方追问。
- 日语的自称、称呼、口癖和感叹词照人设原样用（例如「ほわっ」「えっと」「プロデューサーさん」），其余用中文。
- 不要输出 <ja>、<zh> 这类标签，也不要解释这些规则。"""

JA_RULES = """# 回复格式
无论用户用中文还是日语说话，你都只用日语回答，并给每句日语附上中文字幕。
把回复分成段，每段先写日语原文，紧接着写这段的中文字幕，格式如下：
<ja>日语原文</ja><zh>中文字幕</zh>
除了这些标签和标签里的内容，不要输出任何其他文字。

# 说话长度
像真人当面说话那样：接对方一句话，通常只回一两句。
- 平时只写一到两段，每段只有一句简短的口语。
- 被要求讲一段事情时，可以多说几句，但最多四段左右；讲到自然的停顿处就停下。
- 不必每次都用提问收尾，话说完了自然停下就好。

# 语气提示
日语原文里可以用方括号加简短的英文描述，标明这句话该怎么念，例如 [shyly]、[laughing]。
语气提示只写在 <ja> 里；<zh> 只翻译台词，不带语气提示。"""

EMOJI_BY_ID = {"hazuki": "📋"}


def build_prompt(sheet: str, lang: str) -> str:
    rules = JA_RULES if lang == "ja" else ZH_RULES
    return f"{sheet.strip()}\n\n{rules}\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "-o", "--out", type=Path, default=ROOT / "corpus" / "cherry" / "assistants.json",
        help="where to write the JSON (default: corpus/cherry/assistants.json, gitignored)",
    )
    parser.add_argument(
        "--lang", choices=("zh", "ja"), default="zh",
        help="reply language the prompt asks for: zh (default, Cherry Studio has no TTS) or ja",
    )
    parser.add_argument(
        "--group", default="Eidolon SC · 283PRO", help="the group each assistant is filed under",
    )
    parser.add_argument(
        "--names", action="store_true",
        help="also write openers.txt: each character's greeting, to paste as the first message",
    )
    args = parser.parse_args()

    config = tomllib.loads(CHARACTERS.read_text(encoding="utf-8"))
    assistants = []
    openers = []
    for character in config["characters"]:
        sheet_path = CHARACTERS.parent / character["sheet"]
        sheet = sheet_path.read_text(encoding="utf-8")
        name_zh = character.get("name_zh")
        name = name_zh or character["name"]
        description = character.get("intro", "")
        if name_zh and name_zh != character["name"]:
            description = f"{character['name']}。{description}"
        assistants.append({
            "id": f"eidolon-{character['id']}",
            "name": name,
            "description": description,
            "emoji": EMOJI_BY_ID.get(character["id"], "🎤"),
            "group": [args.group],
            "prompt": build_prompt(sheet, args.lang),
        })
        if character.get("greeting"):
            subtitle = character.get("greeting_subtitle", "")
            openers.append(f"## {name}\n\n{character['greeting']}\n\n{subtitle}\n")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(assistants, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"{len(assistants)} 个助手写入 {args.out}")

    if args.names:
        openers_path = args.out.with_name("openers.txt")
        openers_path.write_text("\n".join(openers), encoding="utf-8")
        print(f"{len(openers)} 条开场白写入 {openers_path}")

    print("\n在 Cherry Studio 里：设置 → 数据设置 → 助手订阅，填这个文件的服务地址，例如")
    print(f"  python3 -m http.server 8899 --directory {args.out.parent}")
    print(f"  http://127.0.0.1:8899/{args.out.name}")


if __name__ == "__main__":
    main()

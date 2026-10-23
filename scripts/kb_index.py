#!/usr/bin/env python3
"""把知识库里的笔记按话题标签聚一遍，生成主题索引草稿。

只做机器能做的部分：分组、计数、列出每条的字数和校对状态。
分组之后怎么评价、哪些值得建页，还是要人看。

用法：
    python kb_index.py                     # 屏幕上看看
    python kb_index.py --out 主题草稿.md    # 写成文件
    python kb_index.py --min 3             # 至少 3 篇才算一个主题（默认 3）
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

TAG = re.compile(r"#([^\s#，。！？、,.!?;:：、（）()]{1,16})")
SKIP_DIRS = {"模板", "系统", "日报", ".obsidian", ".trash"}


def short(title: str, n: int = 34) -> str:
    return title if len(title) <= n else title[: n - 1] + "…"


def default_kb_dir() -> Path | None:
    appdata = os.environ.get("APPDATA") or os.path.expanduser("~/.config")
    cfg = Path(appdata) / "douyin-favorites-to-knowledge" / "config.json"
    if cfg.exists():
        try:
            return Path(json.loads(cfg.read_text(encoding="utf-8"))["knowledge_dir"])
        except Exception:
            return None
    return None


def read_note(path: Path) -> dict:
    text = path.read_text(encoding="utf-8", errors="replace")
    meta: dict[str, str] = {}
    body = text
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end > 0:
            for line in text[3:end].splitlines():
                if ":" in line and not line.startswith(" "):
                    key, value = line.split(":", 1)
                    meta[key.strip()] = value.strip().strip('"').strip("'")
            body = text[end + 4 :]

    title = meta.get("title") or path.stem
    desc = meta.get("description", "")
    tags = {t for t in TAG.findall(title + " " + desc)}

    # 转录段字数，用来在草稿里标量级
    lines = body.splitlines()
    chars = 0
    try:
        start = next(i for i, l in enumerate(lines) if l.strip() == "### 转录") + 1
        end = next((i for i in range(start, len(lines)) if lines[i].startswith("## ")), len(lines))
        chars = len(re.findall(r"[\u4e00-\u9fff]", "\n".join(lines[start:end])))
    except StopIteration:
        pass

    return {
        "file": path,
        "stem": path.stem,
        "title": TAG.sub("", title).strip(" ，。、"),
        "tags": tags,
        "chars": chars,
        "aweme_id": meta.get("aweme_id", ""),
        "proofread": bool(meta.get("proofread")),
        "nospeech": meta.get("transcript_status") == "no_speech",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="按话题标签生成主题索引草稿")
    parser.add_argument("--dir", help="知识库目录，不填就用配置里的")
    parser.add_argument("--out", help="写到指定 md 文件")
    parser.add_argument("--min", type=int, default=3, help="覆盖几篇才算一个主题，默认 3")
    args = parser.parse_args()

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    root = Path(args.dir).expanduser() if args.dir else default_kb_dir()
    if not root or not root.exists():
        print("找不到知识库目录。用 --dir 指定。")
        return 1

    notes = []
    for path in sorted(root.rglob("*.md")):
        if any(part in SKIP_DIRS for part in path.relative_to(root).parts):
            continue
        if path.name.startswith("00_"):
            continue
        note = read_note(path)
        # 日报、主题页、分析页没有 aweme_id，不当成视频笔记
        if not note["aweme_id"]:
            continue
        notes.append(note)

    if not notes:
        print(f"{root} 里没有找到笔记。")
        return 0

    grouped: dict[str, list[dict]] = defaultdict(list)
    for note in notes:
        for tag in note["tags"]:
            grouped[tag].append(note)

    big = {t: v for t, v in grouped.items() if len(v) >= args.min}
    small = {t: v for t, v in grouped.items() if len(v) < args.min}
    covered = {n["stem"] for v in big.values() for n in v}
    loose = [n for n in notes if n["stem"] not in covered]

    out: list[str] = []
    out.append("# 主题索引草稿")
    out.append("")
    out.append(
        f"{len(notes)} 篇笔记，{len(grouped)} 个话题标签，"
        f"其中 {len(big)} 个覆盖 {args.min} 篇以上。"
    )
    out.append("")

    if big:
        for tag, items in sorted(big.items(), key=lambda kv: (-len(kv[1]), kv[0])):
            out.append(f"## {tag} · {len(items)} 篇")
            for n in items:
                flag = "已校对" if n["proofread"] else ("无口播" if n["nospeech"] else "未校对")
                out.append(f"- [[{n['stem']}|{short(n['title'])}]] —— {n['chars']} 字，{flag}")
            out.append("")
    else:
        out.append(f"没有标签覆盖到 {args.min} 篇以上，先只维护 00_总览.md，别急着建主题页。")
        out.append("")

    if loose:
        out.append("## 未归入主题")
        for n in loose:
            tags = "、".join(sorted(n["tags"])) or "无标签"
            out.append(f"- [[{n['stem']}|{short(n['title'])}]] —— {n['chars']} 字，{tags}")
        out.append("")

    if small:
        out.append("## 只有一两篇的标签（不够建页，留着看趋势）")
        out.append("")
        out.append("、".join(f"{t}（{len(v)}）" for t, v in sorted(small.items(), key=lambda kv: -len(kv[1]))))
        out.append("")

    text = "\n".join(out)

    if args.out:
        target = Path(args.out).expanduser()
        target.write_text(text, encoding="utf-8")
        print(f"已写入 {target}")
        print(f"{len(notes)} 篇 / {len(big)} 个主题 / {len(loose)} 篇未归类")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())

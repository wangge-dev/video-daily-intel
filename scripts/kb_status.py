#!/usr/bin/env python3
"""看一眼知识库里每篇笔记的状态。

输出每篇的字数、标点密度、是否校对过、是否无口播，最后给下一步动作建议。

用法：
    python kb_status.py                      # 读安装时配置的知识库路径
    python kb_status.py --dir "D:\\库\\抖音收藏"
    python kb_status.py --todo               # 只列还没处理的
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

CN = re.compile(r"[\u4e00-\u9fff]")
PUNCT = re.compile(r"[，。！？；：、]")
# 只统计笔记，跳过这些目录
SKIP_DIRS = {"模板", "系统", "日报", ".obsidian", ".trash"}

STATE_LABEL = {
    "done": "已校对",
    "todo": "待校对",
    "regen": "待重转",
    "nospeech": "无口播",
    "notext": "无转录",
}


def default_kb_dir() -> Path | None:
    """从引擎配置里取知识库路径。"""
    appdata = os.environ.get("APPDATA") or os.path.expanduser("~/.config")
    cfg = Path(appdata) / "douyin-favorites-to-knowledge" / "config.json"
    if cfg.exists():
        try:
            return Path(json.loads(cfg.read_text(encoding="utf-8"))["knowledge_dir"])
        except Exception:
            return None
    return None


def read_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """拆 frontmatter，够用就行，不做完整 YAML 解析。"""
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end < 0:
        return {}, text
    meta: dict[str, str] = {}
    for line in text[3:end].splitlines():
        if ":" not in line or line.startswith(" "):
            continue
        key, value = line.split(":", 1)
        meta[key.strip()] = value.strip().strip('"').strip("'")
    return meta, text[end + 4 :]


def transcript_lines(body: str) -> list[str] | None:
    """取 ### 转录 到下一个 ## 标题之间的正文。没这一段返回 None。"""
    lines = body.splitlines()
    try:
        start = next(i for i, l in enumerate(lines) if l.strip() == "### 转录") + 1
    except StopIteration:
        return None
    # 从 start 往后找，不能从 0 开始找，否则会命中前面的 ## 原始材料
    end = next((i for i in range(start, len(lines)) if lines[i].startswith("## ")), len(lines))
    return [l.strip() for l in lines[start:end] if l.strip()]


def inspect(path: Path) -> dict:
    text = path.read_text(encoding="utf-8", errors="replace")
    meta, body = read_frontmatter(text)
    lines = transcript_lines(body)

    if lines is None:
        return {"path": path, "meta": meta, "chars": 0, "punct": 0, "lines": 0,
                "density": 0.0, "state": "notext", "doubt": 0}

    joined = "\n".join(lines)
    chars = len(CN.findall(joined))
    punct = len(PUNCT.findall(joined))
    density = punct * 100 / chars if chars else 0.0

    if meta.get("transcript_status") == "no_speech":
        state = "nospeech"
    elif meta.get("proofread"):
        state = "done"
    elif density < 2 and chars >= 200:
        # 整篇几乎没有标点，说明提示词没吃上，得重转，改也改不动
        state = "regen"
    else:
        state = "todo"

    return {
        "path": path,
        "meta": meta,
        "chars": chars,
        "punct": punct,
        "lines": len(lines),
        "density": density,
        "state": state,
        "doubt": joined.count("（？）") + joined.count("(?)"),
    }


def dwidth(s: str) -> int:
    """终端里中文占两格，算显示宽度才能对齐。"""
    return sum(2 if ord(c) > 0x2E80 else 1 for c in s)


def pad(s: str, width: int) -> str:
    return s + " " * max(0, width - dwidth(s))


def collect(root: Path) -> list[dict]:
    rows = []
    for path in sorted(root.rglob("*.md")):
        if any(part in SKIP_DIRS for part in path.relative_to(root).parts):
            continue
        if path.name.startswith("00_"):
            continue
        row = inspect(path)
        # 只有带 aweme_id 的才是视频笔记，日报、总览、主题页都跳过
        if not row["meta"].get("aweme_id"):
            continue
        rows.append(row)
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="知识库状态一览")
    parser.add_argument("--dir", help="知识库目录，不填就用配置里的")
    parser.add_argument("--todo", action="store_true", help="只显示待处理和不正常的")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args()

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    root = Path(args.dir).expanduser() if args.dir else default_kb_dir()
    if not root or not root.exists():
        print("找不到知识库目录。用 --dir 指定，例如：\n  python kb_status.py --dir \"D:\\我的库\\抖音收藏\"")
        return 1

    rows = collect(root)
    if not rows:
        print(f"{root} 里没有找到笔记。")
        return 0

    if args.json:
        print(json.dumps([
            {
                "file": str(r["path"].relative_to(root)).replace("\\", "/"),
                "title": r["meta"].get("title", ""),
                "chars": r["chars"], "lines": r["lines"],
                "density": round(r["density"], 1),
                "state": r["state"],
                "proofread": r["meta"].get("proofread", ""),
                "doubt": r["doubt"],
            }
            for r in rows
        ], ensure_ascii=False, indent=2))
        return 0

    counts = {k: 0 for k in STATE_LABEL}
    total_chars = 0
    for r in rows:
        counts[r["state"]] = counts.get(r["state"], 0) + 1
        total_chars += r["chars"]

    show = [r for r in rows if not args.todo or r["state"] in ("todo", "regen")]
    if show:
        print(pad("笔记", 42) + pad("字数", 8) + pad("密度", 7) + pad("存疑", 6) + "状态")
        print("-" * 76)
        for r in show:
            name = r["path"].stem
            if len(name) > 40:
                name = name[:39] + "…"
            print(
                pad(name, 42)
                + pad(str(r["chars"]), 8)
                + pad(f"{r['density']:.1f}", 7)
                + pad(str(r["doubt"]), 6)
                + STATE_LABEL[r["state"]]
            )
        print()

    print(f"共 {len(rows)} 篇，{total_chars} 汉字")
    parts = [f"{STATE_LABEL[k]} {v}" for k, v in counts.items() if v]
    print("  " + " · ".join(parts))

    need = [r for r in rows if r["state"] in ("todo", "regen")]
    if need:
        print("\n下一步：")
        for r in need:
            title = r["meta"].get("title", r["path"].stem)[:32]
            if r["state"] == "regen":
                print(f"  · {title} —— 标点几乎全丢，重转这条（别手工改）")
            else:
                print(f"  · {title} —— 按题材判档：娱乐叙事只查人名，专业内容整篇校")
    elif counts["done"]:
        print("\n都校对过了，可以按主题整理总览了。")
    return 0


if __name__ == "__main__":
    sys.exit(main())

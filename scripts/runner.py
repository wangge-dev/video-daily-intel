#!/usr/bin/env python3
"""AI 视频情报局核心驱动脚本 (WorkBuddy 专用执行器)
负责底层的抖音官方扫码登录、私密收藏自动同步、本地 Whisper 转写与知识库写入。
严禁使用 AI 模拟浏览器点击，一律走原生通道执行。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
WHEELS_DIR = SKILL_DIR / "wheels"

# 用当前解释器执行 CLI，不依赖 PATH。
# run.cmd 会把 Scripts 目录塞进 PATH，但直接跑 runner.py 时没有，会报 WinError 2。
CLI = [sys.executable, "-m", "douyin_favorites_knowledge"]


def ensure_dependencies() -> None:
    """确保核心运行库已安装；若未安装，用仓库自带的 wheel 补装。

    主引擎是 MIT，随仓库分发；专有的 core 组件不在仓库里，
    缺了就让用户重跑 install.py（它会按上游地址取）。
    """
    try:
        import douyin_favorites_knowledge
        return
    except ImportError:
        pass

    wheel_files = list(WHEELS_DIR.glob("*.whl")) if WHEELS_DIR.exists() else []

    if not wheel_files:
        print(
            json.dumps(
                {"error": "引擎未安装，且仓库里没有 wheel。请先运行 python scripts/install.py"},
                ensure_ascii=False,
            )
        )
        sys.exit(1)

    pip_cmd = [sys.executable, "-m", "pip", "install", "--quiet", "--no-deps"]
    pip_cmd.extend(str(w) for w in wheel_files)

    try:
        subprocess.run(pip_cmd, check=True)
    except Exception as e:
        print(json.dumps({"error": f"依赖自动安装失败，请手动在终端运行: {' '.join(pip_cmd)}", "details": str(e)}, ensure_ascii=False))
        sys.exit(1)


def cmd_status(args: argparse.Namespace) -> None:
    ensure_dependencies()
    from douyin_favorites_knowledge.browser_collector import browser_status
    try:
        res = browser_status()
        print(json.dumps(res, ensure_ascii=False))
    except Exception as e:
        print(json.dumps({"status": "login_required", "message": str(e)}, ensure_ascii=False))


def cmd_login(args: argparse.Namespace) -> None:
    ensure_dependencies()
    from douyin_favorites_knowledge.browser_collector import login_browser
    try:
        print(json.dumps({"info": "正在唤起官方登录窗口，请拿起手机抖音 App 扫码授权..."}, ensure_ascii=False))
        res = login_browser(timeout_seconds=args.timeout)
        print(json.dumps(res, ensure_ascii=False))
    except Exception as e:
        print(json.dumps({"error": "登录超时或被取消", "details": str(e)}, ensure_ascii=False))
        sys.exit(1)


def cmd_setup(args: argparse.Namespace) -> None:
    ensure_dependencies()
    target_dir = Path(args.knowledge_dir).expanduser().resolve()
    target_dir.mkdir(parents=True, exist_ok=True)
    
    # 初始化目录与配置
    cmd = [
        *CLI,
        "setup",
        "--knowledge-dir", str(target_dir),
        "--transcription", "local",
        "--skip-login",
        "--force"
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    
    # 如果指定了 vault，则配置 Obsidian 模板
    obsidian_cmd = [
        *CLI,
        "configure-obsidian",
        "--vault", str(target_dir.parent if target_dir.name in ("抖音收藏", "视频情报") else target_dir),
        "--subdir", target_dir.name
    ]
    subprocess.run(obsidian_cmd, check=False, capture_output=True)
    
    print(json.dumps({
        "status": "ready",
        "knowledge_dir": str(target_dir),
        "message": f"知识库目录已绑定至: {target_dir}"
    }, ensure_ascii=False))


def cmd_sync(args: argparse.Namespace) -> None:
    ensure_dependencies()
    cmd = [
        *CLI,
        "sync",
        "--max-items", str(args.max_items),
        "--no-login-prompt"
    ]
    if args.dry_run:
        cmd.append("--dry-run")
        
    proc = subprocess.run(cmd, capture_output=True, text=True)
    stdout = proc.stdout.strip()
    try:
        res = json.loads(stdout)
        print(json.dumps(res, ensure_ascii=False))
    except Exception:
        print(stdout if stdout else json.dumps({"status": "no_changes", "raw": proc.stderr}, ensure_ascii=False))


def cmd_extract(args: argparse.Namespace) -> None:
    """提取单条视频链接的口播逐字稿"""
    extract_script = SKILL_DIR / "scripts" / "extract_douyin.py"
    if not extract_script.exists():
        print(json.dumps({"error": "未找到 extract_douyin.py 脚本"}, ensure_ascii=False))
        sys.exit(1)
        
    cmd = [sys.executable, str(extract_script), "--json", args.url]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    stdout = proc.stdout.strip()
    try:
        res = json.loads(stdout)
        print(json.dumps(res, ensure_ascii=False))
    except Exception:
        print(stdout if stdout else proc.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(description="AI 视频情报局核心执行器")
    subparsers = parser.add_subparsers(dest="action", required=True)

    # status
    subparsers.add_parser("status", help="检查抖音授权登录状态")

    # login
    login_parser = subparsers.add_parser("login", help="唤起原生浏览器扫码登录")
    login_parser.add_argument("--timeout", type=int, default=300, help="等待扫码超时时间")

    # setup
    setup_parser = subparsers.add_parser("setup", help="配置知识库目录与模板")
    setup_parser.add_argument("--knowledge-dir", required=True, help="知识库或文件夹路径")

    # sync
    sync_parser = subparsers.add_parser("sync", help="同步最新收藏并写入知识库")
    sync_parser.add_argument("--max-items", type=int, default=5, help="单次最多同步条数")
    sync_parser.add_argument("--dry-run", action="store_true", help="只预览不写入")

    # extract
    extract_parser = subparsers.add_parser("extract", help="单条视频直接转写")
    extract_parser.add_argument("--url", required=True, help="抖音/B站等视频链接")

    args = parser.parse_args()
    
    if args.action == "status":
        cmd_status(args)
    elif args.action == "login":
        cmd_login(args)
    elif args.action == "setup":
        cmd_setup(args)
    elif args.action == "sync":
        cmd_sync(args)
    elif args.action == "extract":
        cmd_extract(args)


if __name__ == "__main__":
    main()

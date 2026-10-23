"""视频情报局一键安装。

在技能目录下执行（WorkBuddy 里直接说“装一下视频情报局”即可）：
    python scripts/install.py

做的事情：建独立 venv → 装依赖 → 装引擎 → 打补丁 → 检查 ffmpeg。
不改动系统 Python，所有依赖都在 ~/.workbuddy/vdi-runtime 里。
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WHEELS = ROOT / "wheels"
DEFAULT_VENV = Path.home() / ".workbuddy" / "vdi-runtime"
MIN_PY = (3, 10)

# 上游引擎（MIT），插件包不在 PyPI，只能从这里取。
# core 是上游作者的专有组件，本仓库不重新分发，安装时按上游发布地址取用。
UPSTREAM = "https://github.com/tars1230/douyin-favorites-to-knowledge"
UPSTREAM_TAG = "v2.3.3"
UPSTREAM_CORE_WHEEL = (
    f"{UPSTREAM}/raw/{UPSTREAM_TAG}/vendor/wheels/douyin_knowledge_core-0.2.1-py3-none-any.whl"
)

# Windows 上没有 ffmpeg 时自动下载的地址（官方推荐的 essentials build）
FFMPEG_WIN_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"

# 由 --venv 覆盖，见 main()
VENV = DEFAULT_VENV


def _venv_python() -> Path:
    if os.name == "nt":
        return VENV / "Scripts" / "python.exe"
    return VENV / "bin" / "python"


def _run(cmd: list, quiet: bool = False) -> None:
    label = " ".join(str(c) for c in cmd[:4])
    print(f"  -> {label}{' ...' if len(cmd) > 4 else ''}", flush=True)
    kwargs = {"check": True}
    if quiet:
        kwargs["stdout"] = subprocess.DEVNULL
        kwargs["stderr"] = subprocess.DEVNULL
    subprocess.run([str(c) for c in cmd], **kwargs)


def _check_python() -> None:
    if sys.version_info < MIN_PY:
        raise SystemExit(
            f"当前 Python {sys.version_info.major}.{sys.version_info.minor} 太旧，"
            f"需要 {MIN_PY[0]}.{MIN_PY[1]} 或更高。请先升级 Python 再运行。"
        )
    print(f"  Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro} 可用")


def _download(url: str, dest: Path) -> bool:
    import urllib.request

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "video-daily-intel-installer"})
        with urllib.request.urlopen(req, timeout=60) as resp, dest.open("wb") as fh:
            total = int(resp.headers.get("Content-Length") or 0)
            done = 0
            last_pct = -1
            while True:
                chunk = resp.read(256 * 1024)
                if not chunk:
                    break
                fh.write(chunk)
                done += len(chunk)
                if total:
                    pct = done * 100 // total
                    if pct != last_pct:
                        last_pct = pct
                        print(
                            f"\r    已下载 {pct}%  ({done // 1048576}/{total // 1048576} MB)",
                            end="",
                            flush=True,
                        )
        print()
        return True
    except Exception as exc:
        print(f"\n    下载失败：{exc}")
        return False


def _ensure_ffmpeg(venv: Path) -> bool:
    """ffmpeg 是硬依赖。PATH 里没有就自动下一份放进虚拟环境，避免新手卡在这一步。"""
    found = shutil.which("ffmpeg")
    if found:
        print(f"  已在 PATH 中找到：{found}")
        return True

    local = venv / ("Scripts/ffmpeg.exe" if os.name == "nt" else "bin/ffmpeg")
    if local.is_file():
        print(f"  使用之前下载的：{local}")
        return True

    if os.name != "nt":
        print("  没找到 ffmpeg。macOS 请执行：brew install ffmpeg")
        return False

    print("  系统里没有 ffmpeg，自动下载一份（约 110 MB，只需一次）")
    tmp = venv / "_ffmpeg_tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    archive = tmp / "ffmpeg.zip"

    if not _download(FFMPEG_WIN_URL, archive):
        shutil.rmtree(tmp, ignore_errors=True)
        print("  自动下载失败，可以手动装：winget install Gyan.FFmpeg")
        print("  装好后重新运行本脚本，会自动跳过下载。")
        return False

    print("    解压中")
    try:
        import zipfile

        with zipfile.ZipFile(archive) as zf:
            member = next(
                (n for n in zf.namelist() if n.replace("\\", "/").endswith("/bin/ffmpeg.exe")),
                None,
            )
            if member is None:
                raise RuntimeError("压缩包里没有找到 ffmpeg.exe")
            local.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member) as src, local.open("wb") as dst:
                shutil.copyfileobj(src, dst)
    except Exception as exc:
        print(f"    解压失败：{exc}")
        return False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    try:
        out = subprocess.run([str(local), "-version"], capture_output=True, text=True, timeout=30)
        ver = out.stdout.splitlines()[0].strip() if out.returncode == 0 and out.stdout else "版本未知"
    except Exception:
        ver = "版本未知"
    print(f"  已就绪：{local}")
    print(f"  {ver}")
    return True


def _nvidia_gpu() -> str | None:
    """有 NVIDIA 显卡就返回型号，没有返回 None。"""
    exe = shutil.which("nvidia-smi")
    if not exe:
        for cand in (
            r"C:\Windows\System32\nvidia-smi.exe",
            r"C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe",
        ):
            if Path(cand).is_file():
                exe = cand
                break
    if not exe:
        return None
    try:
        out = subprocess.run(
            [str(exe), "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=20,
        )
        line = (out.stdout or "").strip().splitlines()
        return line[0].strip() if out.returncode == 0 and line else None
    except Exception:
        return None


_GPU_PROBE = """
import os, site, sys
from pathlib import Path
for root in site.getsitepackages():
    for sub in ("cublas", "cudnn", "cuda_nvrtc"):
        d = Path(root) / "nvidia" / sub / "bin"
        if d.is_dir():
            os.add_dll_directory(str(d))
import ctranslate2
print(ctranslate2.get_cuda_device_count())
"""


def _ensure_gpu(py: Path, skip: bool = False) -> bool:
    """装了 CUDA 运行库才能用显卡转写，速度差三倍左右。没显卡就安静走 CPU。"""
    if skip:
        print("  已跳过 GPU 检测")
        return False
    name = _nvidia_gpu()
    if not name:
        print("  没检测到 NVIDIA 显卡，使用 CPU 转写")
        return False

    print(f"  检测到显卡：{name}")
    print("  安装 CUDA 运行库（约 700MB，只需一次）")
    try:
        _run(
            [py, "-m", "pip", "install", "--quiet", "nvidia-cublas-cu12", "nvidia-cudnn-cu12"],
            quiet=True,
        )
    except subprocess.CalledProcessError:
        print("  安装失败，将使用 CPU 转写")
        return False

    try:
        probe = subprocess.run([str(py), "-c", _GPU_PROBE], capture_output=True, text=True, timeout=120)
        count = int((probe.stdout or "0").strip() or 0)
    except Exception:
        count = 0

    if count > 0:
        print(f"  GPU 加速已启用（{count} 个设备）")
        return True
    print("  显卡不可用，回退 CPU 转写")
    return False


def _install_engine(py: Path) -> None:
    """装引擎的两个包：MIT 主包在本仓库 wheels/ 里，专有的 core 从上游取。

    为什么分两处：douyin_favorites_to_knowledge 是 MIT，可以随仓库分发；
    douyin_knowledge_core 是上游作者的专有组件，本仓库不重新分发，
    只在上游公开的发布地址按需下载，装进本机运行环境自用。
    """
    local = sorted(WHEELS.glob("*.whl"))
    main_pkg = [w for w in local if w.name.startswith("douyin_favorites_to_knowledge")]
    if not main_pkg:
        raise SystemExit(f"仓库里缺主引擎 wheel：{WHEELS}。请重新完整下载本仓库。")

    core_local = [w for w in local if w.name.startswith("douyin_knowledge_core")]
    if core_local:
        print(f"  本地 wheel：{len(local)} 个")
        _run([py, "-m", "pip", "install", "--quiet", "--no-deps", *local])
        return

    targets = list(main_pkg)
    cache = Path(tempfile.mkdtemp(prefix="vdi-engine-"))
    core = cache / "douyin_knowledge_core-0.2.1-py3-none-any.whl"
    print(f"  主引擎用本地 wheel，core 组件从上游取（{UPSTREAM_TAG}）")
    if _download(UPSTREAM_CORE_WHEEL, core):
        targets.append(core)
    else:
        print("  core 组件下载失败。")
        print("  可以手动下载后放进 wheels/ 目录再跑一次：")
        print(f"  {UPSTREAM_CORE_WHEEL}")
        raise SystemExit(1)
    _run([py, "-m", "pip", "install", "--quiet", "--no-deps", *targets])


def main() -> int:
    parser = argparse.ArgumentParser(description="安装视频情报局的运行环境")
    parser.add_argument("--force", action="store_true", help="删掉已有环境重装")
    parser.add_argument("--skip-browser", action="store_true", help="不下载 Playwright 浏览器")
    parser.add_argument("--venv", type=Path, help=f"指定环境目录（默认 {DEFAULT_VENV}）")
    parser.add_argument("--no-ffmpeg", action="store_true", help="不自动下载 ffmpeg")
    parser.add_argument("--no-gpu", action="store_true", help="不装 CUDA 运行库，强制 CPU 转写")
    args = parser.parse_args()

    global VENV
    if args.venv:
        VENV = args.venv.expanduser().resolve()

    if not WHEELS.is_dir() or not list(WHEELS.glob("*.whl")):
        raise SystemExit(f"找不到 wheels 目录：{WHEELS}。请确认整个仓库完整克隆下来了。")

    print("[1/7] 检查 Python")
    _check_python()

    print("[2/7] 准备独立运行环境")
    if args.force and VENV.exists():
        shutil.rmtree(VENV, ignore_errors=True)
        print(f"  已删除旧环境：{VENV}")
    if not _venv_python().exists():
        _run([sys.executable, "-m", "venv", str(VENV)])
        print(f"  已创建：{VENV}")
    else:
        print(f"  复用已有环境：{VENV}")
    py = _venv_python()
    _run([py, "-m", "pip", "install", "--quiet", "--upgrade", "pip"], quiet=True)

    print("[3/7] 安装依赖（约 100MB，首次几分钟）")
    _run([py, "-m", "pip", "install", "--quiet", "-r", str(ROOT / "requirements.txt")])
    # faster-whisper 单独装：跳过它 av<13 的依赖声明
    _run([py, "-m", "pip", "install", "--quiet", "--no-deps", "faster-whisper"])

    print("[4/7] 检查显卡加速")
    has_gpu = _ensure_gpu(py, skip=args.no_gpu)

    print("[5/7] 安装核心引擎")
    _install_engine(py)

    print("[6/7] 打兼容补丁")
    _run([py, str(ROOT / "scripts" / "patch_runtime.py")])

    print("[7/7] 准备 ffmpeg（视频转音频要用）")
    if args.no_ffmpeg:
        has_ffmpeg = bool(shutil.which("ffmpeg"))
        print("  已跳过检查")
    else:
        has_ffmpeg = _ensure_ffmpeg(VENV)

    if not args.skip_browser:
        print("  Playwright 浏览器：优先用本机 Chrome/Edge，缺失时才需要下载。")
        try:
            _run([py, "-m", "playwright", "install", "chromium"], quiet=True)
            print("  已就绪")
        except subprocess.CalledProcessError:
            print("  [提醒] 浏览器下载失败，但本机有 Chrome 或 Edge 就能正常用。")

    print("\n安装完成。")
    if not has_ffmpeg:
        print("\n但 ffmpeg 还没就绪，没有它视频转不了音频，转写会失败。")
        print("  Windows：winget install Gyan.FFmpeg")
        print("  macOS  ：brew install ffmpeg")
        print("装好之后重新运行本脚本，会自动跳过已经装好的部分。")
        return 1
    print("\n下一步：")
    print(f"  {py} {ROOT / 'scripts' / 'runner.py'} setup --knowledge-dir \"<你的知识库路径>\"")
    print(f"  {py} {ROOT / 'scripts' / 'runner.py'} login")
    return 0


if __name__ == "__main__":
    sys.exit(main())

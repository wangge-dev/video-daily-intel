"""把上游 douyin_favorites_knowledge 包的已知缺陷与本机优化，固化成可重复执行的补丁。

为什么要这个脚本：
  上游 2.3.3 版有几个问题，纯 pip 装完直接跑会失败或产出脏数据。以前是手工改
  site-packages，重装即丢，别人拿去也用不了。这里改成脚本，安装后跑一次即可，
  幂等：重复执行不会重复打补丁。

用法：
  python patch_runtime.py            # 打补丁
  python patch_runtime.py --check    # 只检查状态，不写入
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

MARK = "# [vdi-patch]"

# ---------------------------------------------------------------- 补丁定义


def _p0_av_compat(text: str) -> str:
    """av 13+ 移除了 av.open() 的 metadata_errors 参数，faster-whisper 1.2.1 还在传它，
    一调用就 TypeError。改成优先带参数、不支持时回退，兼容新旧两个 av 大版本。"""
    if "_vdi_open_container" in text:
        return text
    old = 'with av.open(input_file, mode="r", metadata_errors="ignore") as container:'
    new = 'with _vdi_open_container(input_file) as container:  # [vdi-patch] 兼容 av 12 / 19'
    if old not in text:
        raise RuntimeError("P0 匹配失败：faster-whisper 的 av.open 调用和预期不一致")
    text = text.replace(old, new, 1)

    anchor = "def decode_audio("
    helper = '''def _vdi_open_container(input_file):  # [vdi-patch]
    """av 13 起去掉了 metadata_errors 参数，这里两个大版本都兼容。"""
    try:
        return av.open(input_file, mode="r", metadata_errors="ignore")
    except TypeError:
        return av.open(input_file, mode="r")


'''
    if anchor not in text:
        raise RuntimeError("P0 匹配失败：找不到 decode_audio 定义")
    return text.replace(anchor, helper + anchor, 1)


def _p5_ffmpeg_locate(text: str) -> str:
    """上游只在 PATH 里找 ffmpeg，找不到就整条转写链失败。
    安装器会把 ffmpeg 下到虚拟环境里，这里补一个兜底查找。"""
    if "_vdi_ffmpeg" in text:
        return text

    anchor = "def check_environment() -> dict[str, Any]:"
    helper = '''def _vdi_ffmpeg() -> str | None:  # [vdi-patch]
    """ffmpeg 优先取 PATH，其次取安装器下载到虚拟环境里的那一份。"""
    found = shutil.which("ffmpeg")
    if found:
        return found
    for sub in ("Scripts", "bin"):
        name = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
        candidate = Path(sys.prefix) / sub / name
        if candidate.is_file():
            return str(candidate)
    return None


'''
    if anchor not in text:
        raise RuntimeError("P5 匹配失败：找不到 check_environment 定义")
    text = text.replace(anchor, helper + anchor, 1)

    old_check = '    if not shutil.which("ffmpeg"):'
    new_check = "    if not _vdi_ffmpeg():  # [vdi-patch]"
    if old_check not in text:
        raise RuntimeError("P5 匹配失败：ffmpeg 环境检查代码和预期不一致")
    text = text.replace(old_check, new_check, 1)

    old_call = '["ffmpeg", "-nostdin", "-y", "-i", str(media_path)'
    new_call = '[_vdi_ffmpeg() or "ffmpeg", "-nostdin", "-y", "-i", str(media_path)'
    if old_call not in text:
        raise RuntimeError("P5 匹配失败：ffmpeg 调用代码和预期不一致")
    text = text.replace(old_call, new_call, 1)

    if "\nimport sys\n" not in text:
        text = text.replace("import subprocess\n", "import subprocess\nimport sys\n", 1)
    return text


def _p1_sec_user_id(text: str) -> str:
    """上游用正则从页面脚本里扒 sec_user_id，抖音新版页面里取不到，喜欢列表直接废掉。
    改成取不到时回退请求官方 profile 接口。"""
    if "profile/self/?device_platform=webapp" in text:
        return text
    old = """                    if (!match) return {ok: false, error: 'sec_user_id_missing'};
                    params.set('sec_user_id', match[1]);"""
    new = """                    let secUserId = match ? match[1] : '';
                    if (!secUserId) {
                        try {
                            const pr = await fetch('https://www.douyin.com/aweme/v1/web/user/profile/self/?device_platform=webapp&aid=6383', { credentials: 'include' });
                            const pd = await pr.json();
                            secUserId = (pd && pd.user && pd.user.sec_uid) || '';
                        } catch (e) {}
                    }
                    if (!secUserId) return {ok: false, error: 'sec_user_id_missing'};
                    params.set('sec_user_id', secUserId);"""
    if old not in text:
        raise RuntimeError("P1 匹配失败：浏览器采集代码结构和预期不一致")
    return text.replace(old, new, 1)


def _p2_note_subdir(text: str) -> str:
    """上游把所有笔记平铺在知识库根目录，收藏/喜欢/那五个子文件夹从没用过。
    改成按来源分目录，Obsidian 里层级才清楚（双链按文件名解析，不受目录影响）。"""
    if "NOTE_SUBDIRS" in text:
        return text
    old = '''def _note_path(config: Config, item: dict[str, Any]) -> Path:
    return config.knowledge_dir / f"{item['source']}-{item['aweme_id']}.md"'''
    new = '''NOTE_SUBDIRS = {"collection": "收藏", "like": "喜欢"}  # [vdi-patch]


def _note_dir(config: Config, item: dict[str, Any]) -> Path:
    """按来源分目录存放，避免全部平铺在知识库根目录。"""
    target = config.knowledge_dir / NOTE_SUBDIRS.get(str(item.get("source", "")), "")
    target.mkdir(parents=True, exist_ok=True)
    return target


def _note_path(config: Config, item: dict[str, Any]) -> Path:
    return _note_dir(config, item) / f"{item['source']}-{item['aweme_id']}.md"'''
    if old not in text:
        raise RuntimeError("P2 匹配失败：_note_path 结构和预期不一致")
    text = text.replace(old, new, 1)

    # 校验阶段的目标路径
    old_plan = '''        final_path = config.knowledge_dir / f"{item['source']}-{aweme_id}.md"'''
    new_plan = '''        final_path = _note_path(config, item)  # [vdi-patch]'''
    if old_plan not in text:
        raise RuntimeError("P2 匹配失败：_promotion_plan 目标路径和预期不一致")
    text = text.replace(old_plan, new_plan, 1)

    # 正式写入的目标路径
    old_move = '''                    config.knowledge_dir / f"{item['source']}-{item['aweme_id']}.md",'''
    new_move = '''                    _note_path(config, item),  # [vdi-patch]'''
    if old_move not in text:
        raise RuntimeError("P2 匹配失败：promote 移动目标和预期不一致")
    return text.replace(old_move, new_move, 1)


def _p3_clean_title(text: str) -> str:
    """抖音接口偶尔会在 desc 末尾塞降级提示，上游原样当标题写进笔记。"""
    if "_clean_title" in text:
        # 已打过补丁：把旧版实现升级成会顺手清掉残留标点的新版
        old_tail = (
            '    cleaned = title\n'
            '    for noise in _TITLE_NOISE:\n'
            '        cleaned = cleaned.replace(noise, "")\n'
            '    return cleaned.strip() or title'
        )
        new_tail = (
            '    cleaned = title\n'
            '    for noise in _TITLE_NOISE:\n'
            '        cleaned = cleaned.replace(noise, "")\n'
            '    cleaned = cleaned.strip().strip("…。，,.;；·—- ")\n'
            '    return cleaned.strip() or title'
        )
        return text.replace(old_tail, new_tail, 1)
    old = '''    title = _text(raw, "title") or _text(raw, "description")'''
    new = '''    title = _clean_title(_text(raw, "title") or _text(raw, "description"))  # [vdi-patch]'''
    if old not in text:
        raise RuntimeError("P3 匹配失败：normalize_item 标题取值和预期不一致")
    text = text.replace(old, new, 1)

    old_fn = "def normalize_item(raw: dict[str, Any]) -> dict[str, Any]:"
    new_fn = '''_TITLE_NOISE = (
    "版本过低，升级后可展示全部信息",
    "版本过低，升级后可展示全部信息。",
    "去抖音搜索",
)


def _clean_title(title: str) -> str:  # [vdi-patch]
    """去掉抖音接口塞进标题里的降级提示，这类文案不是作者写的。"""
    cleaned = title
    for noise in _TITLE_NOISE:
        cleaned = cleaned.replace(noise, "")
    cleaned = cleaned.strip().strip("…。，,.;；·—- ")
    return cleaned.strip() or title


def normalize_item(raw: dict[str, Any]) -> dict[str, Any]:'''
    if old_fn not in text:
        raise RuntimeError("P3 匹配失败：normalize_item 定义和预期不一致")
    return text.replace(old_fn, new_fn, 1)


def _p4_daily_report(text: str) -> str:
    """上游日报把所有入库条目都列出来，但纯音乐/字幕视频转写是空的，
    "今日新增 4 条"里 2 条点进去没内容。改成只列有实质口播的，其余归纳成一行。
    阈值 15 字：低于这个长度基本都是背景音被误识别成一两个词。"""
    if "MIN_TRANSCRIPT_CHARS" in text:
        return text

    anchor = "DEFAULT_MAX_DAILY_ITEMS = 100"
    new_line = (
        '    readable = [i for i in items '
        'if len((i.get("transcript") or "").strip()) >= MIN_TRANSCRIPT_CHARS]  # [vdi-patch]'
    )
    old_line = (
        '    readable = [i for i in items '
        'if (i.get("transcript") or "").strip()]  # [vdi-patch]'
    )

    old_block = '''    if items:
        lines.extend(["## 新增笔记", ""])
        for item in items:
            note_name = f"{item['source']}-{item['aweme_id']}"
            author = f" - {item['author']}" if item["author"] else ""
            lines.append(f"- [[{note_name}|{item['title']}]]{author} ([原链接]({item['source_url']}))")
    else:
        lines.append("今日没有新增条目。")'''
    new_block = (
        new_line + "\n"
        + '''    silent = len(items) - len(readable)
    if readable:
        lines.extend(["## 新增笔记", ""])
        for item in readable:
            note_name = f"{item['source']}-{item['aweme_id']}"
            author = f" - {item['author']}" if item["author"] else ""
            lines.append(f"- [[{note_name}|{item['title']}]]{author} ([原链接]({item['source_url']}))")
            lines.append("")
    else:
        lines.append("今日没有可读的口播内容。")
    if silent:
        lines.extend(["", f"> 另有 {silent} 条无口播（纯音乐/字幕类），已入库但不列出。"])'''
    )

    if old_line in text:
        text = text.replace(old_line, new_line, 1)
    elif old_block in text:
        text = text.replace(old_block, new_block, 1)
    else:
        raise RuntimeError("P4 匹配失败：日报生成逻辑和预期不一致")

    if anchor not in text:
        raise RuntimeError("P4 匹配失败：cli.py 缺少默认配置常量锚点")
    return text.replace(
        anchor,
        anchor + "\nMIN_TRANSCRIPT_CHARS = 15  # [vdi-patch] 逐字稿低于该长度视为无有效口播",
        1,
    )


def _p6_gpu_device(text: str) -> str:
    """上游把 device 写死成 cpu，有 NVIDIA 显卡的机器白白慢好几倍。
    改成先探测 CUDA，能用就用 GPU，起不来静默回退 CPU。"""
    if "_vdi_pick_device" in text:
        return text
    anchor = "_MODEL_CACHE: dict[str, Any] = {}"
    if anchor not in text:
        raise RuntimeError("P6 匹配失败：找不到模型缓存定义")
    helper = '''def _vdi_inject_cuda_dll() -> None:  # [vdi-patch]
    """pip 装的 nvidia-* 把 DLL 放在 site-packages/nvidia/*/bin，Windows 不会自动找。"""
    if os.name != "nt" or getattr(_vdi_inject_cuda_dll, "_done", False):
        return
    _vdi_inject_cuda_dll._done = True
    try:
        import site

        roots = [Path(p) / "nvidia" for p in site.getsitepackages()]
        user_site = site.getusersitepackages()
        if user_site:
            roots.append(Path(user_site) / "nvidia")
        for root in roots:
            if not root.is_dir():
                continue
            for sub in ("cublas", "cudnn", "cuda_nvrtc", "cuda_runtime"):
                bin_dir = root / sub / "bin"
                if bin_dir.is_dir():
                    os.add_dll_directory(str(bin_dir))
                    os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")
    except Exception:
        pass


def _vdi_pick_device() -> tuple[str, str]:  # [vdi-patch]
    """优先用 GPU，不可用就回退 CPU。环境变量 VDI_DEVICE=cpu 可强制走 CPU。"""
    forced = os.environ.get("VDI_DEVICE", "").strip().lower()
    if forced == "cpu":
        return "cpu", "int8"
    try:
        _vdi_inject_cuda_dll()
        import ctranslate2

        if ctranslate2.get_cuda_device_count() > 0:
            types = ctranslate2.get_supported_compute_types("cuda")
            return "cuda", ("int8" if "int8" in types else "float16")
    except Exception:
        pass
    return "cpu", "int8"


'''
    text = text.replace(anchor, helper + anchor, 1)
    old = 'model = WhisperModel(model_name, device="cpu", compute_type="int8")'
    if old not in text:
        raise RuntimeError("P6 匹配失败：找不到 WhisperModel 初始化")
    new = (
        "device, compute_type = _vdi_pick_device()  # [vdi-patch]\n"
        '        model = WhisperModel(model_name, device=device, compute_type=compute_type)'
    )
    return text.replace(old, new, 1)


def _p7_browser_flags(text: str) -> str:
    """Playwright 默认带 --no-sandbox 启动，浏览器顶部会顶一条黄色警告条；
    另外固定 viewport 1280x800 会让打开的窗口只占屏幕一角，截图和演示都难看。
    两个都改成可用环境变量控制，默认开沙箱、默认跟随窗口大小。"""
    if "VDI_BROWSER_SANDBOX" in text:
        return text
    old = """                    "viewport": {"width": 1280, "height": 800},
                    "locale": "zh-CN",
                }"""
    if old not in text:
        raise RuntimeError("P7 匹配失败：浏览器启动参数和预期不一致")
    new = """                    "locale": "zh-CN",
                }
                # [vdi-patch] 去掉 --no-sandbox 警告条；VDI_BROWSER_SANDBOX=0 可恢复
                if os.environ.get("VDI_BROWSER_SANDBOX", "1") != "0":
                    kwargs["chromium_sandbox"] = True
                # [vdi-patch] 窗口自适应屏幕；VDI_FIXED_VIEWPORT=1 可恢复固定 1280x800
                if os.environ.get("VDI_FIXED_VIEWPORT", "0") == "1":
                    kwargs["viewport"] = {"width": 1280, "height": 800}
                else:
                    kwargs["no_viewport"] = True"""
    return text.replace(old, new, 1)


def _p8_hf_offline(text: str) -> str:
    """huggingface 连不上时（国内很常见），模型明明已经下载到本地也会加载失败。
    改成加载前先查本地缓存，有就切离线，避免整批转写全废。"""
    if "_vdi_offline_guard" in text:
        return text
    anchor = '''def _load_model(model_name: str):
    """Load each Whisper model once. A load failure must stop the run, not mark every item retryable."""
'''
    if anchor not in text:
        raise RuntimeError("P8 匹配失败：_load_model 结构和预期不一致")
    helper = '''def _vdi_offline_guard(model_name: str) -> None:  # [vdi-patch]
    """本地已有模型权重时强制离线，避免 huggingface 不可达导致加载失败。"""
    if os.environ.get("HF_HUB_OFFLINE") == "1":
        return
    if "/" in model_name:
        repo = "models--" + model_name.replace("/", "--")
    else:
        repo = "models--Systran--faster-whisper-" + model_name
    roots = []
    if os.environ.get("HF_HOME"):
        roots.append(Path(os.environ["HF_HOME"]) / "hub")
    roots.append(Path.home() / ".cache" / "huggingface" / "hub")
    for root in roots:
        if list((root / repo).glob("snapshots/*/model.bin")):
            os.environ["HF_HUB_OFFLINE"] = "1"
            os.environ["TRANSFORMERS_OFFLINE"] = "1"
            return


'''
    new_anchor = anchor + "    _vdi_offline_guard(model_name)  # [vdi-patch]\n"
    text = text.replace(anchor, helper + new_anchor, 1)
    return text


def _p9_t2s(text: str) -> str:
    """whisper 对中文经常直接吐繁体，简体环境下笔记读起来别扭。
    转写结果落盘前统一做一次繁转简，没装 opencc 就原样保留。"""
    if "_vdi_to_simplified" in text:
        return text
    anchor = "def _load_model(model_name: str):"
    if anchor not in text:
        raise RuntimeError("P9 匹配失败：找不到模型加载函数")
    helper = '''def _vdi_to_simplified(text: str) -> str:  # [vdi-patch]
    """繁体转简体。缺 opencc 时静默跳过，不影响主流程。"""
    if not text or os.environ.get("VDI_NO_T2S") == "1":
        return text
    conv = getattr(_vdi_to_simplified, "_cc", None)
    if conv is None:
        try:
            import opencc

            conv = opencc.OpenCC("t2s")
        except Exception:
            conv = False
        _vdi_to_simplified._cc = conv
    if not conv:
        return text
    try:
        return conv.convert(text)
    except Exception:
        return text


'''
    text = text.replace(anchor, helper + anchor, 1)
    old = '            transcript = "\\n".join(segment.text.strip() for segment in segments if segment.text.strip()).strip()'
    if old not in text:
        raise RuntimeError("P9 匹配失败：找不到转录文本拼接")
    new = old + "\n            transcript = _vdi_to_simplified(transcript)  # [vdi-patch]"
    return text.replace(old, new, 1)


def _p10_asr_prompt(text: str) -> str:
    """默认调用不带任何提示词，模型不知道题材、也不加句末标点：
    实测同一段 3 分钟音频，标点密度 4.2/百字 → 加提示后 11.2/百字，
    "春秋"从"聊成秋"变成正确写法。提示词用视频自带的话题标签拼，不写死题材。"""
    if "_vdi_build_prompt" in text:
        # 修历史 bug：早期版本把换行写成了字面量 \n，导致简繁转换那行成了注释
        broken = "transcript = _vdi_norm_punct(transcript)  # [vdi-patch]\\n"
        if broken in text:
            text = text.replace(
                broken,
                "transcript = _vdi_norm_punct(transcript)  # [vdi-patch]\n",
                1,
            )
        # 已打过：把标点映射升级成能处理 whisper 吐的小型标点（U+FE50 一系）
        v1 = '        s = s.replace("﹑", "、").replace("‧", "·").replace("—", "，")'
        v2 = (
            '        s = s.replace("﹔", "。").replace("﹑", "、")\n'
            '        s = s.replace("‧", "·").replace("﹒", "。")\n'
            '        s = s.replace("—", "，").replace("–", "，")'
        )
        v3 = (
            '        s = s.replace("﹔", "；").replace("﹑", "、")\n'
            '        s = s.replace("‧", "·").replace("﹒", "。")\n'
            '        s = s.replace("﹐", "，").replace("﹕", "：")\n'
            '        s = s.replace("﹖", "？").replace("﹗", "！")\n'
            '        s = s.replace("—", "，").replace("–", "，")'
        )
        for old in (v1, v2):
            if old in text:
                return text.replace(old, v3, 1)
        return text

    anchor = "def _load_model(model_name: str):"
    if anchor not in text:
        raise RuntimeError("P10 匹配失败：找不到模型加载函数")

    helper = '''def _vdi_build_prompt(item: dict[str, Any]) -> str:  # [vdi-patch]
    """用视频标题里的话题标签拼一条转写提示，给模型补上下文和标点示范。"""
    if os.environ.get("VDI_NO_PROMPT") == "1":
        return ""
    raw = " ".join(
        str(item.get(key) or "") for key in ("title", "description")
    )
    tags: list[str] = []
    for tag in re.findall(r"#([^\\s#]{2,12})", raw):
        if tag not in tags:
            tags.append(tag)
    prompt = "以下是一段中文口播。请用简体中文逐句转写，像正常文章一样加上标点符号。"
    if tags:
        prompt += "本视频话题：" + "、".join(tags[:8]) + "。"
    return prompt


def _vdi_norm_punct(text: str) -> str:  # [vdi-patch]
    """whisper 的中文标点常是半角，个别符号还会串码，统一成正常中文标点。"""
    if not text or os.environ.get("VDI_NO_PUNCT") == "1":
        return text
    out: list[str] = []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        for bad, good in ((",", "，"), (";", "；"), (":", "："), ("?", "？"), ("!", "！")):
            s = s.replace(bad, good)
        s = s.replace("﹔", "；").replace("﹑", "、")
        s = s.replace("‧", "·").replace("﹒", "。")
        s = s.replace("﹐", "，").replace("﹕", "：")
        s = s.replace("﹖", "？").replace("﹗", "！")
        s = s.replace("—", "，").replace("–", "，")
        s = re.sub(r"，{2,}", "，", s)
        s = re.sub(r"。{2,}", "。", s)
        s = re.sub(r"^[，。、；：]+", "", s)
        s = s.strip()
        if s:
            out.append(s)
    return "\\n".join(out)


'''
    text = text.replace(anchor, helper + anchor, 1)

    old = '            segments, _ = model.transcribe(str(audio_path), vad_filter=True, task="transcribe")'
    if old not in text:
        raise RuntimeError("P10 匹配失败：找不到转写调用")

    new = '''            _prompt = _vdi_build_prompt(item)  # [vdi-patch]
            _cjk = bool(re.search(r"[\\u4e00-\\u9fff]", str(item.get("title") or "") + str(item.get("description") or "")))
            segments, _ = model.transcribe(
                str(audio_path),
                vad_filter=True,
                task="transcribe",
                language="zh" if _cjk else None,
                initial_prompt=_prompt or None,
                beam_size=int(os.environ.get("VDI_BEAM", "5")),
                condition_on_previous_text=True,
            )'''
    text = text.replace(old, new, 1)

    anchor2 = '            transcript = _vdi_to_simplified(transcript)  # [vdi-patch]'
    if anchor2 in text:
        text = text.replace(
            anchor2,
            "            transcript = _vdi_norm_punct(transcript)  # [vdi-patch]\n" + anchor2,
            1,
        )
        return text
    old2 = '            transcript = "\\n".join(segment.text.strip() for segment in segments if segment.text.strip()).strip()'
    if old2 not in text:
        raise RuntimeError("P10 匹配失败：找不到转录文本拼接")
    return text.replace(
        old2,
        old2 + "\n            transcript = _vdi_norm_punct(transcript)  # [vdi-patch]",
        1,
    )


def _p11_no_resync(text: str) -> str:
    """已经入过库的条目不再重复转写。

    上游每次同步都把候选列表整体送进转写，包括已经入库的旧视频。一批 5 条里
    4 条是旧的，就要白等十几分钟；更麻烦的是我们改过提示词，旧条目重转出来
    的文本和账本记的不一样，账本校验会报 promoted item changed，整批新条目
    一起被拦下。这里在转写之前先把已入库的剔掉。
    """
    if "_vdi_drop_known" in text:
        return text
    anchor = "    raw_items = _apply_configured_stages(list(raw_items), config)"
    if anchor not in text:
        raise RuntimeError("P11 匹配失败：找不到 _apply_configured_stages 调用")

    helper = '''def _vdi_drop_known(config, items):  # [vdi-patch]
    """已入库的条目不再重复转写。要强制重转，设 VDI_RESYNC=1。"""
    import os

    if os.environ.get("VDI_RESYNC") == "1":
        return items
    try:
        from .workflow import load_ledger

        known = load_ledger(config)
    except Exception:
        return items
    kept = []
    for item in items:
        key = str(item.get("source") or "collection") + ":" + str(item.get("aweme_id") or "")
        if key in known:
            continue
        kept.append(item)
    return kept


def _sync('''
    text = text.replace("def _sync(", helper, 1)
    text = text.replace(
        anchor,
        "    raw_items = _vdi_drop_known(config, list(raw_items))  # [vdi-patch] 已入库的不重转\n" + anchor,
        1,
    )
    return text


def _p11_skip_changed(text: str) -> str:
    """单条旧条目内容变化时跳过，不要中断整批入库。"""
    if "# [vdi-patch] 旧条目内容变了" in text:
        return text
    old = '''            raise ValueError(
                f"promoted item changed: {item['aweme_id']}; manual migration required"
            )'''
    new = (
        "            already_promoted += 1  # [vdi-patch] 旧条目内容变了，跳过；要更新走单独重转\n"
        "            continue"
    )
    if old not in text:
        raise RuntimeError("P11 匹配失败：找不到 promoted item changed 抛错")
    text = text.replace(old, new, 1)

    old2 = '            raise ValueError(f"ledger content conflict for {aweme_id}")'
    new2 = (
        "            skipped += 1  # [vdi-patch] 内容冲突，跳过而不是中断整批\n"
        "            continue"
    )
    if old2 in text:
        text = text.replace(old2, new2, 1)
    return text


PACKAGES = {
    "douyin_favorites_knowledge": [
        ("browser_collector.py", "喜欢列表取不到 sec_user_id", _p1_sec_user_id),
        ("workflow.py", "笔记平铺根目录，不分子文件夹", _p2_note_subdir),
        ("workflow.py", "标题混入抖音降级提示", _p3_clean_title),
        ("cli.py", "日报列出无口播的空条目", _p4_daily_report),
        ("local_whisper.py", "ffmpeg 只在系统 PATH 里找", _p5_ffmpeg_locate),
        ("local_whisper.py", "转写写死 CPU，有显卡也不用", _p6_gpu_device),
        ("browser_collector.py", "启动带 --no-sandbox 警告条、视口固定", _p7_browser_flags),
        ("local_whisper.py", "模型已缓存仍联网校验，断网就废", _p8_hf_offline),
        ("local_whisper.py", "中文转写吐繁体，简体环境没法读", _p9_t2s),
        ("local_whisper.py", "转写不带提示词，标点稀少、专名错得多", _p10_asr_prompt),
        ("cli.py", "已入库条目每次重复转写，白等十几分钟且会校验失败", _p11_no_resync),
        ("workflow.py", "单条旧条目内容变化就中断整批入库", _p11_skip_changed),
    ],
    # 上游只声明 av<13，装不到时整条转写链就废了，这里补上对新版 av 的兼容
    "faster_whisper": [
        ("audio.py", "av 13+ 不兼容导致转写必崩", _p0_av_compat),
    ],
}


# ---------------------------------------------------------------- 执行


def _locate(module: str) -> Path | None:
    spec = importlib.util.find_spec(module)
    if spec is None or not spec.origin:
        return None
    return Path(spec.origin).parent


def _apply(pkg: Path, patches: list, check_only: bool) -> bool:
    cache = {p.name: p.read_text(encoding="utf-8") for p in pkg.glob("*.py")}
    changed: dict[str, str] = {}
    ok = True

    for filename, desc, fn in patches:
        if filename not in cache:
            print(f"  [跳过] {desc} —— 找不到 {filename}")
            ok = False
            continue
        after = changed.get(filename, cache[filename])
        try:
            result = fn(after)
        except RuntimeError as exc:
            print(f"  [失败] {desc} —— {exc}")
            ok = False
            continue
        if result == after:
            print(f"  [已就绪] {desc}")
        else:
            changed[filename] = result
            print(f"  [已修补] {desc}")

    if check_only:
        return ok

    for filename, text in changed.items():
        (pkg / filename).write_text(text, encoding="utf-8")
        # 清掉旧字节码，避免 Python 读到打补丁前的缓存
        for pyc in (pkg / "__pycache__").glob(f"{Path(filename).stem}.*.pyc"):
            pyc.unlink(missing_ok=True)
        print(f"  已写入 {filename}")
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description="给视频情报局依赖的两套库打补丁")
    parser.add_argument("--check", action="store_true", help="只检查，不写入")
    args = parser.parse_args()

    ok = True
    required = {"douyin_favorites_knowledge": False}
    for module, patches in PACKAGES.items():
        pkg = _locate(module)
        if pkg is None:
            if required.get(module, True):
                print(f"[缺失] {module} —— 请先安装核心 wheel，再运行本脚本")
                ok = False
            else:
                print(f"[跳过] {module} —— 未安装")
            continue
        print(f"[{module}] {pkg}")

        # 上游源码里混进来的备份文件，不影响运行，清掉省得误读
        for junk in pkg.glob("*.bak"):
            if not args.check:
                junk.unlink()
            print(f"  [清理] {junk.name}")

        if not _apply(pkg, patches, args.check):
            ok = False

    if args.check:
        print("\n检查模式，未写入任何文件。")
        return 0 if ok else 1

    print("\n补丁完成。" if ok else "\n部分补丁失败，见上方信息。")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

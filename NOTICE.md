# 第三方组件声明

本仓库分两层：作者自己写的安装与文档部分，和上游作者写的引擎部分。权属不同，分开说。

## 上游引擎（两个包，作者均为 Cheng Chen）

| 组件 | 版本 | 许可证 | 在本仓库中的状态 |
|---|---|---|---|
| [douyin-favorites-to-knowledge](https://github.com/tars1230/douyin-favorites-to-knowledge) | 2.3.3 | MIT | `wheels/douyin_favorites_to_knowledge-2.3.3-py3-none-any.whl` 原样附带，保留上游许可证与版权声明 |
| douyin-knowledge-core | 0.2.1 | 专有（LicenseRef-Proprietary） | **不随本仓库分发**。安装时从上游公开地址下载到本机运行环境自用 |

`douyin-knowledge-core` 的许可证写明：未经版权人书面许可，不授予复制、修改、分发或并入其他软件的权利。因此本仓库不含该组件，安装脚本只在运行时按上游公开地址取用，装进用户本机的独立环境，不再向外分发。

上游引擎完整版权声明：Copyright (c) 2026 Cheng Chen。

## 本仓库作者编写的部分

| 文件 | 内容 |
|---|---|
| `scripts/install.py` | 安装器：建独立环境、装依赖、取引擎、调补丁 |
| `scripts/patch_runtime.py` | 兼容补丁：以运行时字符串替换的方式修正已安装 MIT 包中的已知缺陷，不含上游源码 |
| `scripts/runner.py` | 执行器：把上游 CLI 包成 WorkBuddy 可调用的命令 |
| `scripts/kb_status.py`、`scripts/kb_index.py` | 知识库体检与主题聚类工具 |
| `README.md`、`SKILL.md`、`使用说明.html`、`一键安装*` | 文档与安装入口 |

这部分按 MIT 授权，见 LICENSE。

## 关于补丁

`scripts/patch_runtime.py` 不重新分发上游代码。它在用户本机对**已安装**的 MIT 包做原地字符串替换，目的是修掉会直接导致失败的问题（依赖版本不兼容、登录态字段缺失、转写丢标点等）。上游若升级到已修复这些问题的版本，补丁会自动识别并跳过。

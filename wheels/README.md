# wheels 目录说明

这里只放**可以随仓库分发**的 wheel。

- `douyin_favorites_to_knowledge-2.3.3-py3-none-any.whl`：上游引擎主包，MIT，原样附带。

另一个组件 `douyin_knowledge_core-0.2.1-py3-none-any.whl` 是上游作者的**专有**组件，许可证不允许重新分发，所以不在仓库里。安装脚本会在装引擎这一步从上游公开地址下载：

```
https://github.com/tars1230/douyin-favorites-to-knowledge/raw/v2.3.3/vendor/wheels/douyin_knowledge_core-0.2.1-py3-none-any.whl
```

不想让安装脚本联网取，也可以自己下载这个文件放进本目录，安装时会优先用本地文件。

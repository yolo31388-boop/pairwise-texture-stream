# pairwise-texture-stream

开放世界游戏跑起来后，纹理流送把显存打满：mip 请求没有按屏幕投影误差排序，远处 4K 贴图先加载；budget 只算纹理字节，没算上传和 staging 开销；LRU 把正在被材质引用的纹理淘汰，画面出现黑块；IO 请求没有合并，同一张图的多个 mip 重复读盘；加载失败没有 fallback，材质直接变紫；相机传送后没有清请求队列，旧位置的高清纹理还在占坑。render/texture_stream.py 是核心，tests/test_texture_stream.py 15个红。要修的是：按投影误差和可见性排序；budget 含上传/staging；引用计数保护；合并同图 mip IO；失败回退低 mip；传送时取消过期请求。

## 运行

```bash
python -m pytest tests -q
```

初始状态：15 个用例失败。修复实现使全部用例通过，不要修改 `tests/` 下的测试。

语言/框架：Python 3, pytest；环境可复现等级：无外部依赖。

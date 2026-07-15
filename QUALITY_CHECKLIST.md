# 九项质量自检表：2.1.0

| 质量方面 | 状态 | 设计与可核验证据 |
| --- | --- | --- |
| 输入校验 | 通过 | `validation.py` 验证 HTTP(S)、主机、凭据和 fragment；配置与模型拒绝错误类型、布尔冒充整数、NaN/无穷超时；CLI 使用类型和 choices。 |
| 边界检查 | 通过 | 并发 1-64、重试 1-10、PNG 0-9、像素/瓦片数/响应字节硬上限；Deep Zoom 边缘瓦片按左右/上下 overlap 精确验尺寸；坐标越界测试。 |
| 异常处理 | 通过 | HTTP、元数据、下载、响应过大、拼接、写盘分别转换成领域异常；CLI 返回 1 且不输出 traceback；非瞬态 4xx 不重试。 |
| 资源生命周期管理 | 通过 | AsyncClient 使用 `async with`；流响应由上下文关闭；任务取消后 gather；Pillow 图像 paste 后立即 close；临时文件失败即删除；最终文件原子替换。 |
| 并发控制 | 通过 | 仅维护固定下载窗口；最大并发与连接池显式关联；解码批次有界；canvas 只在事件循环线程串行写入；取消路径有测试。 |
| 性能 | 通过 | 下载、解码、拼接流水化；不再保留全量瓦片；Pillow 解码放在线程池；PNG 默认快速无损级别 1；默认并发由真实 8/16/24/32 测量选为 24。 |
| 韧性 | 通过 | 408/429/5xx 和传输错误有限重试，指数退避 + jitter，支持且封顶 `Retry-After`；直图失败/尺寸不符自动回退瓦片；输出使用同目录原子替换。 |
| 可测试性 | 通过 | HTTP client/transport、settings、metadata、progress callback 可注入；纯函数拆分 URL、尺寸、裁剪、文件名；116 个默认测试、真实联网 opt-in、88.95% 分支覆盖率。 |
| 可维护性 | 通过 | 模块边界清晰；运行时版本集中于 `_version.py` 并与 pyproject 互测；Ruff、严格 marker、3.10-3.14 CI、tag/version 发布门禁、CHANGELOG 与测试报告齐备。 |

## 发布门禁

- [x] README 不含 Star History 或其远程图表 URL。
- [x] 版本由 2.0.0 升至向后兼容的功能版本 2.1.0。
- [x] 本地单元、集成、系统、联网和覆盖率测试通过。
- [x] Python 3.12、3.13、3.14 本地通过。
- [x] Python 3.10-3.14 GitHub CI 与独立构建任务通过。
- [x] wheel 与 sdist 隔离构建并通过 `twine check --strict`。
- [ ] 从最终 wheel/sdist 在全新环境安装并运行 CLI（最终构建后执行）。
- [ ] GitHub Release 与 PyPI 2.1.0 发布并核验哈希/安装（最终步骤）。

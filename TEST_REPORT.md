# 测试报告：2.1.0

报告日期：2026-07-15（Asia/Shanghai）

## 结论

发布前本地测试门禁与发布后线上核验均通过。测试覆盖输入校验、边界、重试、响应大小、任务取消、
资源清理、流水线并发、Deep Zoom 拼接、CLI 端到端、真实 Artsy 元数据和真实
直图/瓦片下载。Python 3.12、3.13、3.14 本地全量测试通过；Python 3.10-3.14
GitHub CI 矩阵与独立构建任务全部通过（run 29391174977）。GitHub Release 与
PyPI 2.1.0 已发布，两端产物哈希一致，并已从公共 PyPI 索引完成全新安装验证。

## 环境

- macOS 15.7.7，Apple Silicon arm64
- CPython 3.14.6（主覆盖率环境）；兼容性复测 CPython 3.12、3.13
- HTTPX 0.28.1、Pillow 12.2.0
- pytest 9.1.0、pytest-cov 7.1.0、Ruff 0.15.17
- build 1.5.0、Twine 6.2.0

## 分层结果

| 层级 | 范围 | 结果 |
| --- | --- | --- |
| 单元测试 | 校验器、配置、模型、URL/slug、重试、路径、拼接数学 | 99 passed |
| 集成测试 | MockTransport 下载、直图回退、流水线、API 包装、打包元数据 | 16 passed |
| 系统测试（本地 HTTP） | 独立进程运行 CLI，GraphQL→瓦片→拼接→原子写盘 | 1 passed |
| 联网冒烟 | 真实 Artsy GraphQL 元数据 | 1 passed |
| 全量默认套件 | 联网用例默认显式跳过 | 116 passed, 1 skipped |
| 静态检查 | `ruff check .`、`git diff --check` | passed |
| 覆盖率 | 语句 + 分支；门槛 85% | 88.95% |
| 构建校验 | 隔离构建 wheel + sdist，Twine strict | passed |
| 全新环境安装 | Python 3.12 wheel + Python 3.14 sdist，`pip check`、CLI、真实元数据 | passed |

默认跳过项不是失败：`tests/test_live_metadata.py` 仅在
`RUN_LIVE_TESTS=1` 时访问外部服务，并已在本报告的联网冒烟阶段单独通过。

## Python 版本兼容性

| Python | 平台 | 结果 |
| --- | --- | --- |
| 3.10 | GitHub Actions / Ubuntu | 116 passed, 1 skipped |
| 3.11 | GitHub Actions / Ubuntu | 116 passed, 1 skipped |
| 3.12 | macOS arm64 | 116 passed, 1 skipped |
| 3.13 | macOS arm64 | 116 passed, 1 skipped |
| 3.14.6 | macOS arm64 | 116 passed, 1 skipped；coverage 88.95% |

GitHub CI 证据：<https://github.com/inostarlin-passion/ArtsyTiledImageDownloader/actions/runs/29391174977>

## 真实系统验证

测试作品：`yayoi-kusama-stars-11`。

- 真实元数据：1 张图，2547×3543，7×5，共 35 个瓦片。
- 直图路径：成功输出 2547×3543 JPEG，冷启动观测 3.2 秒。
- 强制瓦片路径：成功输出 2547×3543 JPEG，冷启动观测 4.4 秒；峰值 RSS
  约 116.9 MB。
- 直图与瓦片结果尺寸一致；RGB 通道逐像素 RMS 差为 1.4010、1.1670、
  1.6106，最大通道差 21/19/19，符合 JPEG 再编码预期。

联网耗时受 CDN、连接建立和缓存影响，仅作为系统可用性证据，不作为稳定回归阈值。

## 性能与并发证据

固定 4096×4096、256 个 JPEG 瓦片、16 并发、每请求 20 ms 的本地模拟：

| 指标 | 2.0.0 基线 | 2.1.0 | 变化 |
| --- | ---: | ---: | ---: |
| 端到端中位数（3 次） | 0.442388 s | 0.438073 s | 快 1.0% |
| 最大 RSS | 126.8 MB | 123.5 MB | 低 2.6% |

固定拼接/保存微基准的中位数处于噪声范围内（0.143578 s 对 0.144040 s），
但最大 RSS 从 109.8 MB 降至 102.7 MB（约 6.4%）。关键改进是内存复杂度：
2.0.0 保存全部 `N` 个压缩瓦片；2.1.0 生产路径最多保留一个解码批次和一个补位
下载窗口，即 `O(concurrency)`，不再随总瓦片数线性增长。确定性性能测试验证：并发为
2、总数为 10 且解码被阻塞时，只发出 4 个请求，其余 6 个不会被提前缓冲。

真实服务的同轮并发观测为：8→2.2 s、16→2.0 s、24→1.9 s、32→3.5 s。
因此默认值取 24，而不是盲目提高到上限；并发仍可由用户在 1-64 内调整。

## 关键命令

```bash
ruff check .
pytest --cov --cov-report=term-missing
pytest -m "not integration and not system"
pytest -m "integration and not system"
pytest -m "system and not live"
RUN_LIVE_TESTS=1 pytest tests/test_live_metadata.py
python -m build
python -m twine check --strict dist/*
```

## 发布后验证

- 发布工作流：<https://github.com/inostarlin-passion/ArtsyTiledImageDownloader/actions/runs/29391616089>
- GitHub Release：<https://github.com/inostarlin-passion/ArtsyTiledImageDownloader/releases/tag/v2.1.0>
- PyPI：<https://pypi.org/project/artsy-tiled-image-downloader/2.1.0/>
- Release 为正式版而非 draft/prerelease；wheel 与 sdist 均已附加。
- Trusted Publisher 工作流的测试、构建、Release 附件上传与 PyPI 上传任务全部通过。

| 文件 | 大小 | GitHub / PyPI SHA-256 |
| --- | ---: | --- |
| `artsy_tiled_image_downloader-2.1.0-py3-none-any.whl` | 21,946 B | `7280b62367cfc989531a6827b3c9e3fb3cc63bb38e98632c213523c2c5f1c03d` |
| `artsy_tiled_image_downloader-2.1.0.tar.gz` | 35,150 B | `479f96ad806e1b66e48e4172609fa1ac0c760842f7a62ec79ae4c882a90d2c7c` |

从公共 PyPI simple index 使用 `--no-cache-dir` 安装 2.1.0 后，CLI 输出
`artsy-downloader 2.1.0`，`pip check` 无依赖冲突；随后执行真实作品的
`--metadata-only` 系统测试，1.3 秒返回 2547×3543、7×5、共 35 个瓦片。

## 残余风险

- 外部 Artsy GraphQL/Deep Zoom 接口不是本项目控制的稳定 API；字段或访问策略变化仍可能
  导致联网失败。代码通过清晰的 `MetadataError`、有限重试和本地系统测试降低诊断成本。
- 网络最优并发取决于地区、CDN 和限流；保留 CLI 参数和 64 的硬上限，429/5xx 使用退避重试。
- 最终输出画布仍需约 `width × height × 3` 字节，这是生成单张 RGB 图像的必要下界；
  `max_pixels` 在分配前实施硬限制。

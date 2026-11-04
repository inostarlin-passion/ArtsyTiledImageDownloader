# 下载修复验收用例

对应设计 [technical_design_document.md](technical_design_document.md)。每个编号对应 `tests/test_download_regressions.py` 中的 `test_aNN_*`。参数化项独立运行。

| 验收编号 | 类型 | 测试目的 | 前置条件 | 输入数据 | 操作步骤 | 预期结果 | 后置条件 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| A01 | 动态 | 拒绝错误关联 | 有效作品元数据 | 不同、缺失或重复 ID | 解析元数据 | 直链为空 | 保留瓦片元数据 |
| A02 | 动态 | 确认唯一关联 | 有效作品元数据 | 正确 ID 排在第二位 | 解析元数据 | 取得正确直链 | 顺序不影响身份 |
| A03 | 动态 | 拒绝截断图 | 模拟 HTTP | 截断 JPEG 与合法瓦片 | 下载图片 | 以瓦片方式保存 | 输出可解码 |
| A04 | 动态 | 拒绝格式不符 | 模拟 HTTP | 同尺寸 PNG 候选与 JPEG 瓦片 | 下载图片 | 以瓦片方式保存 JPEG | 扩展名匹配实际格式 |
| A05 | 动态 | 解压保护触发回退 | 降低 Pillow 像素保护阈值 | 尺寸在项目上限内的候选与合法瓦片 | 下载图片 | 以瓦片方式保存 | 保护阈值不变 |
| A06 | 动态 | 保留合法直链 | 模拟 HTTP | 同尺寸同格式完整 JPEG | 下载图片 | 选择直链 | 字节原样保存 |
| A07 | 动态 | 提前停止超长响应 | 可计数异步流 | 偏小或缺失长度声明 | 请求限长正文 | 超限后不再读下一块 | 流已关闭 |
| A08 | 动态 | 防止 HTTP 解压放大 | 可计数异步流 | 带 gzip 编码的响应 | 请求限长正文 | 发送 identity 且拒绝 gzip | 正文未被读取 |
| A09 | 动态 | 限制 GraphQL 正文 | 可计数异步流 | 超过自定义上限的元数据 | 请求作品元数据 | 抛出 MetadataError | 流已关闭 |
| A10 | 动态 | 跳过重定向正文 | 启用重定向 | 大正文重定向与合法最终正文 | 请求限长正文 | 只读取最终正文 | 中间流已关闭 |
| A11 | 静态 | 核对资源预算及入口 | 读取项目源码 | CLI 和配置的 AST | 核对配置字段、解析及透传 | 两种上限均接入 CLI 与配置 | 不执行网络或写盘 |
| A12 | 动态 | 验证并发共享额度 | 模拟 HTTP、监视画布分配 | 三张图与只容纳两张的额度 | 并发下载 | 峰值两张且三张均完成 | 全部画布释放 |
| A13 | 动态 | 单图超限提前失败 | 禁止画布分配 | 额度小于单图估值 | 下载拼接 | 明确报告预算错误 | 没有请求或文件 |
| A14 | 动态 | 直链取消时不提交 | 线程门闩和已有目标 | 合法直链 | 保存阶段连续取消并释放线程 | 取消后保留旧目标 | 临时文件清除 |
| A15 | 动态 | 拼接取消时保护画布 | 线程门闩和已有目标 | 合法瓦片 | 保存阶段连续取消并释放线程 | 画布仍可编码且保留旧目标 | 临时文件清除 |
| A16 | 动态 | 正常保存提交 | 模拟 HTTP | 合法直链或瓦片 | 等待下载完成 | 目标完整且替换旧内容 | 无临时文件 |
| A17 | 动态 | 保留 RGBA alpha | 模拟 HTTP 或同步拼接 | RGB 和 RGBA 混合瓦片 | 拼接后读取像素 | 透明与不透明像素均正确 | 尺寸保持 |
| A18 | 动态 | 保留调色板透明度 | 模拟 HTTP 或同步拼接 | 带 tRNS 的 PNG 瓦片 | 拼接后读取像素 | 调色板透明像素的 alpha 为零 | 尺寸保持 |

---

## 历史记录

# 测试用例说明：下载耗时优化

版本：1.0  
日期：2026-09-03（Asia/Shanghai）  
对应设计文档：[technical_design_document.md](technical_design_document.md)

## 1. 用例总览

| 用例 ID | 对应原子验收标准 | 类型 | 覆盖状态 | 固化代码 |
| --- | --- | --- | --- | --- |
| TC-PERF-01 | AC-01 | 静态 + 动态 | 初态 | `test_ac_01_fast_defaults_are_explicit_and_bounded` |
| TC-PERF-02 | AC-02 | 动态性能 | 暂态、终态 | `test_ac_02_mean_tile_download_time_is_reduced_by_50_percent` |
| TC-PERF-03 | AC-03 | 动态功能 | 终态 | `test_ac_03_optimized_pipeline_preserves_dimensions_and_pixels` |
| TC-PERF-04 | AC-04 | 动态并发 | 暂态、终态 | `test_ac_04_tile_and_shared_artwork_request_windows_are_bounded` |
| TC-PERF-05 | AC-05 | 动态性能 + 功能 | 初态、暂态、终态 | `test_ac_05_artwork_parallelism_is_fast_and_keeps_result_order` |
| TC-PERF-06 | AC-06 | 动态资源 | 暂态、终态 | `test_ac_06_cancelled_downloads_release_all_inflight_requests` |
| TC-PERF-07 | AC-07 | 动态安全 | 初态、暂态、终态 | `test_ac_07_fast_response_path_still_enforces_byte_limit` |
| TC-PERF-08 | AC-08 | 静态 + 动态 CLI | 初态 | `test_ac_08_cli_uses_the_optimized_defaults` |
| TC-PERF-09 | AC-09 | 联网动态 | 初态、终态 | `test_live_sample_metadata_matches_page_and_deep_zoom_contract` |

本地用例位于 `tests/test_performance_acceptance.py`，使用 `MockTransport` 或确定性异步 transport，不依赖外网。TC-PERF-09 位于 `tests/test_live_metadata.py`，只有设置 `RUN_LIVE_TESTS=1` 才执行。

## 2. 结构化测试用例

### TC-PERF-01：默认并发配置明确且有界

**测试目的**

确认性能优化不是隐式创建无限任务：默认瓦片并发为 64，图片并发为 4，并且两个默认值都处于各自硬上限内。

**前置条件**

- Python 环境可导入 `DownloaderSettings`。
- 测试使用临时输出目录，不访问网络。

**输入数据**

- `DEFAULT_CONCURRENCY=64`、`MAX_ALLOWED_CONCURRENCY=64`。
- `DEFAULT_IMAGE_CONCURRENCY=4`、`MAX_ALLOWED_IMAGE_CONCURRENCY=8`。
- `DownloaderSettings(output_dir=tmp_path)`。

**操作步骤**

1. 导入配置常量并创建默认 settings。
2. 比较 settings 实例值与默认常量。
3. 比较默认值与硬上限。

**预期结果**

- `settings.concurrency == 64` 且 `64 <= MAX_ALLOWED_CONCURRENCY`。
- `settings.image_concurrency == 4` 且 `4 <= 8`。
- 不发生异常，不创建输出文件。

**后置条件**

临时目录可安全清理，未产生网络请求或后台任务。

### TC-PERF-02：平均瓦片端到端耗时至少下降 50%

**测试目的**

在输入、响应体、机器和每请求延迟均固定的条件下，验证修改后的默认瓦片并发确实达到目标，而不是只验证配置数字变大。

**前置条件**

- 本地确定性异步 transport，每个请求等待 50ms 后返回同一合法 JPEG。
- 事件循环和文件系统可用。
- 测试不访问 Artsy CDN。

**输入数据**

- `ImageMetadata`: 4096×4096，tile size 256，格式 JPEG，共 256 个瓦片。
- 基线 profile：`concurrency=24`。
- 优化 profile：`concurrency=DEFAULT_CONCURRENCY=64`。
- 每个 profile 在验收测试中重复 3 次；发布基准脚本重复 5 次。

**操作步骤**

1. 分别构造基线和优化 settings。
2. 对每次运行从 `download_and_stitch_tiles()` 开始计时，直到原子输出完成。
3. 分别计算两组算术平均值。
4. 按 `1 - optimized_mean / legacy_mean` 计算下降比例。

**预期结果**

- 优化 profile 的平均耗时不大于基线平均耗时的 50%。
- 验收断言 `reduction >= 0.50`。
- 每次运行都生成完整输出，不能以异常或缺瓦片作为“更快”。

**后置条件**

所有临时输出位于 `tmp_path`，客户端关闭，未留下未关闭的请求任务。

### TC-PERF-03：优化不改变最终像素

**测试目的**

确认并发、解码和流水线调整没有改变 Deep Zoom 的裁剪坐标、拼接顺序或输出尺寸。

**前置条件**

- 使用四个 2×2 PNG 瓦片的本地 MockTransport。
- 输出目录为 pytest 临时目录。

**输入数据**

- 4×4 图像，tile size 2，overlap 0。
- 四块瓦片颜色依次为红、绿、蓝、黄。

**操作步骤**

1. 调用优化后的 `download_and_stitch_tiles()`。
2. 使用 Pillow 打开生成文件。
3. 读取四个角点和整体尺寸。

**预期结果**

- 输出尺寸为 4×4。
- `(0,0)`、`(3,0)`、`(0,3)`、`(3,3)` 分别为红、绿、蓝、黄。
- 所有请求成功且只生成一个最终文件。

**后置条件**

Pillow 读取句柄关闭，输出文件保持完整可读。

### TC-PERF-04：单图与多图请求窗口均有界

**测试目的**

验证单图 tile window 不超过配置值，并验证 3 张图同时工作时共享请求 semaphore 能限制总的 HTTP 活动数。

**前置条件**

- 确定性 transport 记录 `active` 和 `max_active`。
- 关闭直图路径，强制走瓦片。

**输入数据**

- 单图：10 个 1×1 PNG 瓦片，`concurrency=3`。
- 多图：3 张 4×4 PNG 图，每张 4 个 2×2 瓦片，`concurrency=3`、`image_concurrency=3`。

**操作步骤**

1. 先调用 `download_tiles()`，在请求开始/结束时记录活动数。
2. 再调用 `download_images()`，让 3 个 image worker 同时执行。
3. 等待所有输出完成并读取 transport 的最大活动数。

**预期结果**

- 单图 `max_active <= 3`，且 10 个瓦片全部返回。
- 多图总 `max_active <= 3`，3 个结果均按输入顺序返回。
- 没有通过预取全部瓦片来增加活动数。

**后置条件**

所有 semaphore 获取都已释放，三个输出文件可被清理。

### TC-PERF-05：同一作品多图并行且保持顺序

**测试目的**

验证示例页这类 6 张图的图片级并行收益，同时确保 API 返回顺序和 metadata index 不因完成先后不同而改变。

**前置条件**

- 确定性 transport 对每张直图请求等待 50ms。
- 6 张图均提供与 metadata 尺寸一致的 1×1 PNG 直图。

**输入数据**

- 6 个唯一直图 URL。
- 串行对照：`image_concurrency=1`。
- 优化 profile：`image_concurrency=4`。

**操作步骤**

1. 分别以 1 和 4 个 image worker 运行 `download_images()`，每种 profile 重复 3 次。
2. 记录 transport 的最大活动请求数和总耗时。
3. 检查返回结果的 metadata index 序列。

**预期结果**

- 优化 profile 的最大活动请求数不超过 4。
- 返回 index 为 `[0, 1, 2, 3, 4, 5]`。
- 优化平均耗时不大于串行平均耗时的 50%。
- 6 个输出均为 `method="direct"`。

**后置条件**

所有输出写入测试临时目录；worker 已结束，客户端已关闭。

### TC-PERF-06：取消路径释放活动请求

**测试目的**

验证在暂态下载中取消任务不会遗留 transport 请求、后台 tile task 或未释放 semaphore。

**前置条件**

- BlockingTransport 在第一个请求启动后阻塞，且在 `finally` 中递减活动计数。
- 设置 `concurrency=4`，图像包含 8 个瓦片。

**输入数据**

- 一个可取消的 `download_tiles()` task。
- `started` 事件表示至少一个请求已经进入暂态。

**操作步骤**

1. 创建下载 task 并等待 `started`。
2. 调用 `task.cancel()`。
3. 等待 task，并要求收到 `asyncio.CancelledError`。
4. 关闭 AsyncClient，读取 transport 活动数。

**预期结果**

- 取消异常向调用方传播，不被吞掉。
- transport 活动数为 0。
- 无输出文件或半成品最终文件。

**后置条件**

所有 pending tile task 已由 `gather(..., return_exceptions=True)` 回收，临时目录可删除。

### TC-PERF-07：响应快速路径仍拒绝超限数据

**测试目的**

确认 `Content-Length` 快速读取优化没有绕过原有响应字节上限。

**前置条件**

- MockTransport 返回带 `Content-Length: 4` 的响应。
- `request_bytes_with_retries()` 的 `max_bytes=3`。

**输入数据**

- URL：`https://images.example/too-large.png`。
- 响应体：`b"data"`，声明长度 4。

**操作步骤**

1. 使用 `create_async_client()` 发起 `request_bytes_with_retries()`。
2. 等待响应处理结束。

**预期结果**

- 抛出 `ResponseTooLargeError`。
- 错误信息包含 `limit 3`。
- 不进入不必要的重试，不写入输出文件。

**后置条件**

客户端和 response context 均关闭。已有 `tests/test_http.py` 同时覆盖有/无 Content-Length 两种超限路径及瞬态重试路径。

### TC-PERF-08：CLI 采用库的优化默认值

**测试目的**

确认命令行默认值没有与库配置分叉，并确认用户可以显式指定图片级并发。

**前置条件**

- 可构造 CLI parser。
- 不执行真正下载。

**输入数据**

- 参数：`--output-dir <tmp_path> example-artwork`。
- 库默认：瓦片 64，图片 4。

**操作步骤**

1. 调用 `build_parser().parse_args()`。
2. 读取 `args.concurrency` 和 `args.image_concurrency`。
3. 与配置模块常量比较。

**预期结果**

- `args.concurrency == DEFAULT_CONCURRENCY`。
- `args.image_concurrency == DEFAULT_IMAGE_CONCURRENCY`。
- parser 能接受 `--image-concurrency 1..8`，非法值最终由 settings 拒绝。

**后置条件**

不创建客户端、不访问网络、不产生输出文件。

### TC-PERF-09：示例 URL 的联网 metadata 契约

**测试目的**

把页面事实、GraphQL 返回和项目 Deep Zoom 解析进行一次联网交叉验证，确认性能基准使用的样例规模没有脱离真实输入。

**前置条件**

- 设置 `RUN_LIVE_TESTS=1`。
- 外网可以访问 Artsy Metaphysics endpoint。
- 不执行图像下载，只获取 metadata。

**输入数据**

`https://www.artsy.net/artwork/meguru-yamaguchi-splitting-horizon-no-dot-10-11`

**操作步骤**

1. 通过项目 `fetch_metadatas()` 请求 GraphQL。
2. 检查返回 metadata 数量、第一张图尺寸和总瓦片数。
3. 检查第一张图存在直图候选。

**预期结果**

- 返回 6 张图。
- 第一张图为 3865×4951。
- 6 张图合计 207 个全分辨率瓦片。
- 第一张图至少有一个合法直图 URL。

**后置条件**

HTTP 客户端由 `fetch_metadatas()` 的 context manager 关闭；失败时用明确的 metadata/domain error 报告。默认测试不访问外网，而是在显式 live 阶段执行。

## 3. 覆盖性约束

| 维度 | 覆盖方式 |
| --- | --- |
| 静态测试 | 常量/边界断言、CLI parser 默认值、Ruff 检查。 |
| 动态测试 | 确定性 transport、Pillow 实际输出、并发活动数和实测墙钟时间。 |
| 初态 | settings/parser 创建、请求开始前的预算和 live metadata 入口。 |
| 暂态 | delayed transport、并行 worker、响应读取、取消中的 pending task。 |
| 终态 | 平均耗时结论、完整文件、像素、返回顺序、资源活动数为 0。 |
| 外部交叉验证 | Artsy 页面 → GraphQL → Deep Zoom 字段 → Pillow/瓦片计数；只作为 opt-in 证据。 |

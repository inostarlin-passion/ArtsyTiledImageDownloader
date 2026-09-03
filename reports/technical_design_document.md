# 技术设计文档：下载耗时优化

版本：1.0  
日期：2026-09-03（Asia/Shanghai）  
范围：`artsy_tiled_image_downloader` 的瓦片下载、拼接和同一作品的多图下载

## 1. 目标、指标与边界

### 1.1 目标

将下载操作的平均墙钟耗时降低至少 50%，并保持以下不变量：

- Deep Zoom 的坐标、瓦片尺寸、边缘 overlap 和最终像素不变。
- 下载窗口有界；并发度不能通过一次性创建全部瓦片任务来换取速度。
- 单个响应的字节上限、重试策略、取消清理和原子写盘继续有效。
- 同一作品的多张图可以并行，但所有图片共享一个请求预算。

### 1.2 可验收的性能指标

性能指标定义为：从第一次图像/瓦片请求开始，到目标输出文件完成原子替换的墙钟时间；元数据请求时间单独记录，不计入该指标。对一个固定 workload，取 5 次独立运行的算术平均值：

```text
reduction = 1 - mean(after) / mean(before)
通过条件：reduction >= 0.50
```

主要基准使用 4096×4096、256 个 JPEG 瓦片、每个请求固定延迟 50ms。该基准隔离了网络并发带来的收益，避免 CDN、地区、缓存和限流把一次偶然结果误判为稳定性能结论。真实 Artsy URL 只承担联网元数据契约和可用性验证，不承诺外网固定耗时 SLA。

## 2. 问题分解与证据链

本任务按“问题分解 → 证据缺口 → 交叉验证 → 可核验结论”执行：

1. **确认输入规模。** 从示例页面确认作品身份和图片数量，再查询项目实际使用的 GraphQL endpoint，得到 Deep Zoom 的尺寸、TileSize、Overlap 和直图候选。
2. **确认请求模型。** 对尺寸计算瓦片数，检查项目的请求代码是否有连接池、任务窗口、解码流水线和写盘瓶颈。
3. **识别证据缺口。** 旧报告只给出 2.0.0/2.1.0 在 16 并发下约 1% 的端到端差异，不能支持“减少 50%”；同时旧实现对同一作品的图片仍按顺序下载。
4. **建立可重复对照。** 使用固定响应体和固定请求延迟，分别测量修改前 profile（瓦片并发 24、图片串行）和修改后默认 profile（瓦片并发 64、图片并发 4）。
5. **交叉验证结论。** 用静态配置测试、动态 MockTransport 测试、像素级输出测试、取消/限流测试以及可选联网测试分别验证性能、正确性和安全性。

## 3. 已核验事实、来源和显式前提

| 编号 | 经核验事实 | 来源与交叉验证 | 结论用途 |
| --- | --- | --- | --- |
| F-01 | 示例页面是 Meguru Yamaguchi 的 `Splitting Horizon No.10`，页面展示 6 张图并给出 100×75cm 的作品尺寸。 | [Artsy 示例页](https://www.artsy.net/artwork/meguru-yamaguchi-splitting-horizon-no-dot-10-11)；页面图片轮播显示 “1 of 6”，页面正文显示作品信息。 | 选择真实样例并校验 slug/图片数量。 |
| F-02 | 对 slug 执行项目现有 GraphQL 查询，返回 `__typename=Artwork`、相同 slug、6 个 Image figure；第一张 Deep Zoom 为 3865×4951、TileSize=512、Overlap=0，全部 6 张图共 207 个全分辨率瓦片。 | 2026-09-03 通过 `https://metaphysics-production.artsy.net/v2` 返回 HTTP 200；字段由 `metadata.py` 的查询解析，瓦片总数由 `ImageMetadata.tile_count` 重新计算。 | 定义真实样例的 metadata 契约和测试输入规模。 |
| F-03 | 第一张 `normalized.jpg` 的实际 JPEG 尺寸为 3865×4951，与 Deep Zoom 尺寸一致，因此直图路径是合法的优化路径。 | GraphQL 返回的 URL 与 Pillow 对该响应的尺寸检查交叉验证。 | 保留直图优先，避免无谓下载 80 个瓦片。 |
| F-04 | HTTPX 的 Client 会复用连接池；`Limits` 可以约束最大连接数和 keep-alive 连接数；异步客户端应复用而不是在热循环内反复创建。 | [HTTPX Clients](https://www.python-httpx.org/advanced/clients/)、[HTTPX Resource Limits](https://www.python-httpx.org/advanced/resource-limits/)、[HTTPX Async Support](https://www.python-httpx.org/async/)；实现使用一个 `AsyncClient` 和应用层信号量。 | 选择共享客户端和有界请求预算。 |
| F-05 | Deep Zoom 的 overlap 是加在瓦片内容边界之外的边缘像素；非边缘瓦片的编码尺寸可能大于内容尺寸。 | [OpenSeadragon DZI 格式说明](https://github.com/openseadragon/openseadragon/wiki/The-DZI-File-Format)；项目 `ImageMetadata.expected_tile_size()` 和现有边界测试独立计算。 | 优化不得改变裁剪和拼接数学。 |
| F-06 | Pillow 的 PNG `compress_level=1` 优先速度，取值范围为 0–9。 | [Pillow Image file formats](https://pillow.readthedocs.io/en/stable/handbook/image-file-formats.html)；项目默认值和 `test_stitch_tiles_validates_png_compression` 校验。 | 保留快速无损写盘配置，避免把压缩级别误当作有损优化。 |

### 3.1 尚未能由外网证明的事项

- Artsy 的 CDN、HTTP/2 是否持续允许 64 个并发请求，会随时间、地区、缓存和限流变化；联网测试只证明当前 metadata 可用，不证明固定耗时。
- 示例页的页面内容和 GraphQL 字段不是本项目控制的稳定 API；因此性能门禁采用本地确定性传输，联网测试设为显式 opt-in。
- “减少 50%”只有在显式前提“请求延迟占主要耗时、输入规模和机器固定、比较同一输出语义”下成立；对单个已经命中直图缓存的请求，不能推导出同样比例的外网收益。

## 4. 原子化验收标准

| ID | 原子验收标准 | 测试类型 | 生命周期 |
| --- | --- | --- | --- |
| AC-01 | 默认瓦片并发为 64，且不超过硬上限；默认作品图片并发为 4，且不超过 8。 | 静态 + 动态配置 | 初态 |
| AC-02 | 固定基准下，修改后端到端平均耗时相对修改前减少至少 50%。 | 动态性能 | 暂态 → 终态 |
| AC-03 | 优化后的瓦片流水线输出尺寸和关键像素与 Deep Zoom 拼接契约一致。 | 动态功能 | 终态 |
| AC-04 | 单图瓦片任务窗口和多图共享请求窗口均不超过配置值。 | 动态并发 | 暂态 |
| AC-05 | 6 张图可在有界图片 worker 内并行，返回结果仍按 metadata 顺序排列，且平均耗时至少减少 50%。 | 动态性能 + 功能 | 初态 → 暂态 → 终态 |
| AC-06 | 取消下载时，未完成请求和信号量均可释放，不留下活动请求或半成品输出。 | 动态资源 | 暂态 → 终态 |
| AC-07 | 带 `Content-Length` 的快速读取分支仍执行响应字节上限检查；超限响应必须抛出领域异常。 | 动态安全 | 初态 → 暂态 → 终态 |
| AC-08 | CLI 默认值与库默认值一致，并暴露图片级并发参数。 | 静态 + 动态 CLI | 初态 |
| AC-09 | 示例 URL 的联网 metadata 仍与页面/Deep Zoom 契约一致。 | 联网动态（opt-in） | 初态 → 终态 |

## 5. 修改前基线与瓶颈

修改前代码（仓库 HEAD `5b20ead`，2.1.0）已有连接池、24 个瓦片任务的有界窗口和下载/解码流水线，但有两个可量化瓶颈：

1. 默认单图窗口为 24。对 256 个、每请求 50ms 的瓦片，网络阶段至少要经历约 11 个批次；本地拼接/保存还要在网络之后完成。
2. `download_artwork()` 和 CLI 对同一作品的多张图片逐张等待；示例页的 6 张图片不能利用图片之间的独立性。

修改前基准在代码编辑前立即运行 5 次，端到端样本为 `0.653310, 0.642406, 0.637955, 0.638020, 0.639423s`，均值 `0.642223s`。

## 6. 方案设计

### 6.1 并发模型

```text
GraphQL metadata
        │
        ▼
固定数量 image workers（默认 ≤ 4）
        │
        ├── 共享 request semaphore（默认 ≤ 64）
        │       │
        │       └── HTTPX AsyncClient / connection pool
        │
        └── 每张图：有界 tile window → 并行 Pillow decode
                                      → 事件循环线程串行 paste
                                      → 同目录 atomic replace
```

### 6.2 配置变更

- `DEFAULT_CONCURRENCY` 从 24 调整为 64；硬上限仍为 64，显式传入的 1–64 值继续有效。
- 新增 `image_concurrency`，默认 4，允许范围 1–8，并由 CLI 的 `--image-concurrency` 暴露。
- 作品级下载通过固定数量 worker 消费 metadata，不为每张图都创建无限制的工作队列。

### 6.3 共享请求预算

`download_images()` 创建一个大小为 `settings.concurrency` 的 `asyncio.Semaphore`，传入每张图的直图请求和瓦片请求。这样即使 4 张图同时走瓦片路径，所有正在进行的 HTTP 请求总数仍不超过 64；单图调用没有共享 semaphore 时，仍由自己的 tile window 保证上限。

### 6.4 HTTP 响应快速路径

CDN 通常返回 `Content-Length`。当声明长度不超过上限时，使用 `response.aread()` 读取，省去 `bytearray` 和逐 chunk Python 循环；读取完成后再次检查实际长度。没有声明长度的响应继续采用逐 chunk 流式检查，因此安全上限不会被删除。

### 6.5 正确性、失败和资源策略

- 不改变 `tile_url()`、`expected_tile_size()`、`_tile_crop_box()` 和 paste 坐标。
- worker 结果写入预分配列表，最终按 metadata 输入顺序返回。
- 任意 worker 失败或外部取消时，取消剩余 worker；每张图的 pipeline 再取消未完成瓦片并等待取消完成。
- Pillow 图像在 paste 后立即关闭；最终图像用同目录临时文件原子替换。
- 429、5xx 和传输错误仍使用原有有限重试；响应超限直接失败，不进入无意义重试。

## 7. 性能结果

### 7.1 可重复基准

命令：

```bash
./.venv/bin/python tests/benchmark_download.py --repeats 5 --delay-ms 50
```

瓦片端到端比较如下。修改前数值为编辑前 HEAD 的 5 次测量；修改后数值由上述脚本在同一工作区、同一输入和同一机器上测得。

| 指标 | 修改前（24 并发） | 修改后（64 并发） | 变化 |
| --- | ---: | ---: | ---: |
| 5 次平均端到端耗时 | 0.642223s | 0.262027s | **下降 59.20%** |
| 单次样本数 | 0.653310 / 0.642406 / 0.637955 / 0.638020 / 0.639423s | 0.264028 / 0.260207 / 0.261837 / 0.261522 / 0.262541s | — |

作品级 6 张直图的配置对照为串行 1 worker 与默认 4 workers：

| 指标 | 串行基线 | 修改后默认 | 变化 |
| --- | ---: | ---: | ---: |
| 5 次平均耗时 | 0.319306s | 0.109851s | **下降 65.60%** |

计算示例：`1 - 0.262027 / 0.642223 = 0.591999`。两项均超过 50% 门槛。

### 7.2 性能结论的适用范围

结论是“在固定请求延迟、固定输入和固定机器的基准前提下通过性能验收”，不是对所有 Artsy CDN 环境的无条件承诺。若遇到 429、连接池拥塞或高错误率，使用 `--concurrency` 和 `--image-concurrency` 降低压力；真实联网结果应作为可用性和趋势信号单独观察。

## 8. 受影响文件

| 文件 | 变更 |
| --- | --- |
| `artsy_tiled_image_downloader/config.py` | 默认并发、图片并发配置及边界校验。 |
| `artsy_tiled_image_downloader/http.py` | 已知响应长度的快速读取，同时保留实际长度校验。 |
| `artsy_tiled_image_downloader/download.py` | 共享请求 semaphore、有界 image worker、单图请求限流。 |
| `artsy_tiled_image_downloader/cli.py` | CLI 默认值、`--image-concurrency` 和多图并行调用。 |
| `tests/test_performance_acceptance.py` | 9 条原子验收标准中的 8 条本地静态/动态测试。 |
| `tests/test_live_metadata.py` | 示例 URL 的 opt-in 联网契约测试。 |
| `tests/benchmark_download.py` | 可重复的前后配置基准脚本。 |
| `reports/*.md` | 设计、结构化测试用例和完成证据。 |

## 9. 复现入口

```bash
./.venv/bin/ruff check .
./.venv/bin/pytest
./.venv/bin/pytest tests/test_performance_acceptance.py -q
./.venv/bin/python tests/benchmark_download.py --repeats 5 --delay-ms 50
RUN_LIVE_TESTS=1 ./.venv/bin/pytest tests/test_live_metadata.py -q
```

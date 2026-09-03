# 测试完成报告：下载耗时优化

报告日期：2026-09-03（Asia/Shanghai）  
基线代码：仓库 HEAD `5b20ead`（编辑前）  
验证代码：当前工作区修改后的代码

## 1. 总体结论

任务通过。固定 workload 下，瓦片下载端到端平均耗时从 **0.642223s** 降至 **0.262027s**，下降 **59.20%**，超过 50% 验收门槛；同一作品 6 张直图的平均耗时从串行 profile 的 **0.319306s** 降至默认 4-worker profile 的 **0.109851s**，下降 **65.60%**。

优化没有牺牲输出正确性、并发上限、响应大小限制或取消清理。示例 URL 的联网 metadata 契约测试也已通过。

## 2. 修改内容

| 模块 | 完成项 |
| --- | --- |
| `config.py` | 默认瓦片并发 24→64；新增图片并发 1–8，默认 4。 |
| `download.py` | 固定 image worker；跨图片共享最多 64 个请求的 semaphore；保留单图有界 tile window、并行解码和原子写盘。 |
| `http.py` | 对已声明 `Content-Length` 的响应使用 `aread()` 快速路径，并在读取后再次检查实际字节数。 |
| `cli.py` | 默认值与库一致；新增 `--image-concurrency`；CLI 多图保持 metadata 顺序返回。 |
| 测试/基准 | 新增 8 条本地原子验收测试、1 条示例 URL opt-in 联网测试和可重复基准脚本。 |

## 3. 平均耗时证据

### 3.1 性能前提

- 固定 4096×4096 输出、256 个 256×256 JPEG 瓦片。
- 每个模拟请求固定等待 50ms，响应体和机器不变；不访问 CDN，不发生重试。
- 计时范围是第一次图像请求到输出文件原子替换完成，不包含 GraphQL metadata 请求。
- 每组 5 次，取算术平均值。
- 修改前数据在编辑代码前、HEAD `5b20ead` 上采集；修改后数据用工作区脚本采集。

### 3.2 单图瓦片端到端对比

| 样本 | 修改前：2.1.0 默认 24 并发 | 修改后：默认 64 并发 |
| --- | ---: | ---: |
| 1 | 0.653310s | 0.264028s |
| 2 | 0.642406s | 0.260207s |
| 3 | 0.637955s | 0.261837s |
| 4 | 0.638020s | 0.261522s |
| 5 | 0.639423s | 0.262541s |
| **平均** | **0.642223s** | **0.262027s** |
| **下降比例** | — | **59.20%** |

公式：`1 - 0.262027 / 0.642223 = 0.591999`。

### 3.3 六图并行对比

该 workload 模拟示例页面 GraphQL 返回的 6 张图，每张直图响应等待 50ms。串行 profile 使用 `image_concurrency=1`，优化 profile 使用默认 4。

| 指标 | 串行 profile | 默认并行 profile |
| --- | ---: | ---: |
| 5 次平均耗时 | 0.319306s | 0.109851s |
| 下降比例 | — | **65.60%** |

### 3.4 可重复命令

```bash
./.venv/bin/python tests/benchmark_download.py --repeats 5 --delay-ms 50
```

脚本还会输出“当前代码的 legacy 配置”对照：瓦片 24 并发均值 0.633786s，优化均值 0.262027s，下降 58.66%。这项对照用于检测配置变化本身；3.2 的 0.642223s 是在修改前源码上先行捕获的正式 baseline，因此没有把快速响应读取的微小收益错误归入并发优化。

## 4. 原子验收结果

| ID | 验收内容 | 代码证据 | 结果 |
| --- | --- | --- | --- |
| AC-01 | 默认并发明确且不越界 | `test_ac_01_fast_defaults_are_explicit_and_bounded` | 通过 |
| AC-02 | 平均耗时下降至少 50% | `test_ac_02_mean_tile_download_time_is_reduced_by_50_percent`；基准脚本 59.20% | 通过 |
| AC-03 | 尺寸和像素保持正确 | `test_ac_03_optimized_pipeline_preserves_dimensions_and_pixels` | 通过 |
| AC-04 | 单图/多图请求窗口有界 | `test_ac_04_tile_and_shared_artwork_request_windows_are_bounded` | 通过 |
| AC-05 | 六图并行、顺序稳定且加速 | `test_ac_05_artwork_parallelism_is_fast_and_keeps_result_order` | 通过 |
| AC-06 | 取消释放活动请求 | `test_ac_06_cancelled_downloads_release_all_inflight_requests` | 通过 |
| AC-07 | 快速读取仍执行字节上限 | `test_ac_07_fast_response_path_still_enforces_byte_limit`；`tests/test_http.py` 重试/超限用例 | 通过 |
| AC-08 | CLI 与库默认值一致 | `test_ac_08_cli_uses_the_optimized_defaults` | 通过 |
| AC-09 | 示例 URL metadata 契约一致 | `test_live_sample_metadata_matches_page_and_deep_zoom_contract` | 通过（联网 opt-in） |

## 5. 测试执行结果

### 5.1 本地静态、动态和覆盖率

环境：macOS 15.7.9 arm64，CPython 3.14.7，HTTPX 0.28.1，Pillow 12.2.0。

```text
./.venv/bin/ruff check .
All checks passed!

./.venv/bin/pytest --cov --cov-report=term-missing
126 passed, 2 skipped
TOTAL coverage: 89.11%
```

另行执行 `git diff --check` 通过。两个 skipped 是默认关闭的联网用例，不是失败。

### 5.2 示例 URL 联网验证

```text
RUN_LIVE_TESTS=1 ./.venv/bin/pytest tests/test_live_metadata.py -q
2 passed
```

联网查询结果与页面交叉核验：页面显示 6 张图；GraphQL 返回相同 slug 和 6 个 deep-zoom figures；项目重新计算总瓦片数为 207；第一张图为 3865×4951 且存在直图候选。该阶段只请求 metadata，不将外网波动作为性能门禁。

同一 URL 的 CLI metadata-only 冒烟输出为：`Images: 6`、`Image 1/6: 3865x4951, 10x8 (80 tiles)`、`Image 2/6: 3128x4156, 9x7 (63 tiles)`，其余 4 张均为 2000×2000、4×4（每张 16 tiles），总计 207 tiles。

## 6. 证据链与复核入口

1. 页面事实：[Artsy 示例页](https://www.artsy.net/artwork/meguru-yamaguchi-splitting-horizon-no-dot-10-11)。
2. 结构化 metadata：项目使用的 [Artsy Metaphysics endpoint](https://metaphysics-production.artsy.net/v2)，可由 `fetch_metadatas()` 复核。
3. 瓦片语义：[Deep Zoom Image format](https://github.com/openseadragon/openseadragon/wiki/The-DZI-File-Format)，与 `ImageMetadata.expected_tile_size()` 交叉核验。
4. 连接复用/限制：[HTTPX Clients](https://www.python-httpx.org/advanced/clients/) 和 [Resource Limits](https://www.python-httpx.org/advanced/resource-limits/)。
5. 测试和基准代码：[`tests/test_performance_acceptance.py`](../tests/test_performance_acceptance.py)、[`tests/benchmark_download.py`](../tests/benchmark_download.py)。

## 7. 残余风险和结论边界

- 64 并发是可配置上限，不是所有网络环境的最优值；发生 429、连接池拥塞或高延迟时应降低 `--concurrency` / `--image-concurrency`。
- 示例 URL 默认优先使用同分辨率直图；对已命中本地/CDN 缓存的单请求，不能把本地瓦片基准的 59.20% 外推为实际外网固定收益。
- 因此最终结论严格表述为：**代码在显式、可重复的固定 workload 前提下，将平均下载耗时降低超过 50%，并通过全部原子验收标准；真实联网部分已完成契约验证，但不构成外网 SLA。**

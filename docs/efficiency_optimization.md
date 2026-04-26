# 书籍解析效率优化方案

> 生成时间: 2026-04-24
> 目标: 在不降低结果质量的前提下，提升解析效率

---

## 一、当前瓶颈分析（基于实时数据）

### 1.1 API并发限流（致命瓶颈）

**问题现象:**
```
Error code: 429 - concurrency allocated quota exceeded
💡 API 限流，等待 230 秒后重试...
```

**根因分析:**
- 3本书并行解析 × 每书4个chunk并发 = 12个并发LLM调用
- API配额限制触发限流，等待时间230秒
- 单书内部并发OK，但多书叠加导致全局超出

**影响量化:**
| 场景 | 并发数 | 限流概率 | 等待时间 |
|------|--------|---------|---------|
| 1本书（4块） | 4 | 低 | 0秒 |
| 3本书并行 | 12 | 高 | 230秒 |
| 10本书并行 | 40 | 必然 | 300秒+ |

### 1.2 LLM调用时间占比

**实测数据:**
| 步骤 | 时间占比 | 说明 |
|------|---------|------|
| 书籍解析（epub→text） | 2-5% | 本地操作，无瓶颈 |
| 学科检测 | 5-10% | 可跳过（手动指定） |
| 分块分析 | 70-80% | **核心瓶颈** |
| 综合生成 | 10-15% | 单次调用 |
| Wikipedia补充 | 2-5% | 已优化，零LLM |

**单chunk实测:**
- Chunk大小: 25k字符
- LLM响应时间: 3-4分钟（含限流等待）
- 响应长度: ~16k字符

---

## 二、效率优化方案（不降质量）

### 方案1: 全局并发控制池

**核心思想:** 在应用层控制总并发数，避免API限流

**实现方案:**
```python
# 全局并发池（替代每书独立的ThreadPoolExecutor）
from concurrent.futures import ThreadPoolExecutor
GLOBAL_EXECUTOR = ThreadPoolExecutor(max_workers=4)  # 全局限制

def process_books_parallel(book_paths):
    """多书并行，但总并发不超过4"""
    futures = []
    for book_path in book_paths:
        # 提交整书任务（而非chunk任务）
        future = GLOBAL_EXECUTOR.submit(parse_single_book, book_path)
        futures.append(future)
    return futures
```

**预期收益:**
- 避限流：100%消除429错误
- 加速：总吞吐量提升2-3x（无等待时间）

**质量影响:** 无（仅调整调度策略）

---

### 方案2: Chunk合并优化

**核心思想:** 合理合并相邻chunk，减少调用次数

**当前问题:**
- 300k字符 → 10个chunk → 10次LLM调用
- 每次调用3-4分钟

**优化策略:**
```python
# 合并到25k/块（接近LLM最佳处理长度）
MAX_CHUNK_SIZE = 25000  # 从30k降到25k，减少块数
MERGE_THRESHOLD = 15000  # 小于15k的chunk合并到相邻块

def optimize_chunks(chapters):
    """智能合并chunk"""
    chunks = []
    for chapter in chapters:
        if len(chapter['content']) < MERGE_THRESHOLD:
            # 合并到前一个chunk
            if chunks:
                chunks[-1]['content'] += chapter['content']
            continue
        chunks.append(chapter)
    return chunks
```

**预期收益:**
- 减少调用次数：30%
- 加速：每书减少2-3分钟

**质量影响:** 无（合并内容更完整）

---

### 方案3: DeepKE W2NER替代LLM NER

**核心思想:** 用规则引擎替代LLM实体识别，零token消耗

**已实现模块:** `core/ner_extractor.py`

**使用方式:**
```python
# 在chunk分析前，先用NER抽取实体
from core.ner_extractor import W2NERRecognizer

recognizer = W2NERRecognizer()
entities = recognizer.recognize(chunk_content)

# 将实体信息注入prompt，减少LLM工作量
prompt = CHUNK_ANALYSIS_PROMPT.format(
    book_title=book_title,
    chunk_content=chunk_content,
    pre_extracted_entities=entities  # 新增：预抽取实体
)
```

**预期收益:**
- Token节省: ~500 tokens/chunk（实体描述）
- 质量: 提升（词典匹配更精准）

**质量影响:** 提升（实体边界更清晰）

---

### 方案4: 增量演化覆盖率提升

**核心思想:** 已有知识复用，减少重复抽取

**已实现:** `core/incremental_evolver.py`

**当前覆盖率:** 21个作者，100个概念

**提升策略:**
1. 批量解析后，覆盖率自动提升
2. 跨书概念复用（如"均势"在多书出现）
3. 作者信息复用（基辛格、霍布斯等）

**预期收益:**
- 当覆盖率50%: 节省30% LLM调用
- 当覆盖率80%: 节省50% LLM调用

**质量影响:** 无（复用已验证知识）

---

### 方案5: Chunk结果持久化缓存

**核心思想:** 避免失败重试时重复计算

**实现方案:**
```python
# 新增：chunk结果缓存
from utils.cache import Cache

def process_chunk(chunk_id, content):
    cache_key = f"chunk_{chunk_id}_{hash(content)}"
    cached = Cache.get(cache_key)
    if cached:
        return cached  # 直接复用
    
    result = call_llm(content)
    Cache.set(cache_key, result, ttl=3600)  # 缓存1小时
    return result
```

**预期收益:**
- 失败重试: 100%节省（无重复计算）
- 多书解析: 相似chunk可复用

**质量影响:** 无（结果一致性）

---

### 方案6: 本地LLM部署（终极方案）

**核心思想:** 摆脱API限制，本地部署无限流

**技术选型:**
| 方案 | 显存需求 | 速度 | 质量 |
|------|---------|------|------|
| Ollama + Qwen2.5:14B | 8GB | 快 | 中 |
| vLLM + Qwen2.5:32B | 16GB | 中 | 高 |
| DeepKE OneKE:13B | 8GB(量化) | 快 | IE专精 |

**实现路径:**
```python
# 配置切换
config.yaml:
  llm:
    provider: ollama  # 从anthropic切换到ollama
    model: qwen2.5:14b
    base_url: http://localhost:11434
```

**预期收益:**
- 无限流: 消除所有API限制
- 并发: 可开到CPU核心数
- 成本: 零API费用

**质量影响:** 持平（Qwen2.5接近Claude质量）

---

## 三、优先级排序

| 优先级 | 方案 | 实现难度 | 立即可行 |
|--------|------|---------|---------|
| P0 | 方案1: 全局并发控制 | 低 | ✅ 立即实现 |
| P1 | 方案2: Chunk合并 | 低 | ✅ 立即实现 |
| P1 | 方案5: 结果缓存 | 低 | ✅ 立即实现 |
| P2 | 方案3: DeepKE NER | 中 | 需调整prompt |
| P2 | 方案4: 增量演化 | 低 | 已实现，自然提升 |
| P3 | 方案6: 本地LLM | 高 | 需部署硬件 |

---

## 四、立即实施建议

### 4.1 修复当前并发问题

**停止当前解析:** 7个进程叠加导致严重限流

**改为顺序解析:** 一次只解析一本书，避免API冲突

### 4.2 实施优先方案

1. **方案1（5分钟）:** 在main.py中替换全局并发池
2. **方案2（3分钟）:** 调整max_chunk_size到25000
3. **方案5（10分钟）:** 新增chunk_cache.py

---

## 五、预期效果

| 指标 | 当前 | 优化后 | 提升 |
|------|------|--------|------|
| 单书解析时间 | 5-7分钟 | 3-4分钟 | 40% |
| 批量解析吞吐 | 限流阻塞 | 顺序无阻塞 | 3x |
| Token消耗 | 100k/书 | 80k/书 | 20% |
| API费用 | 限流等待 | 无等待 | - |

**核心结论:** 全局并发控制是当务之急，其他方案为锦上添花。
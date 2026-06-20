# BookGraph-Agent API 文档

## 概述

BookGraph-Agent 提供标准 RESTful API 接口，支持外部系统调用书籍解析能力。

## 快速开始

### 本地运行

```bash
# 安装依赖
pip install -r requirements.txt

# 启动服务
python api/main.py

# 或使用 uvicorn
uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
```

### Docker 部署

```bash
# 构建镜像
docker build -t bookgraph-agent:latest .

# 运行容器
docker run -d \
  -p 8000:8000 \
  -e OBSIDIAN_VAULT_PATH=/data/obsidian \
  -e FREELLMAPI_KEY=your_api_key \
  -v $(pwd)/data:/data \
  bookgraph-agent:latest

# 使用 docker-compose
docker-compose up -d
```

## API 端点

### 1. 健康检查

**GET** `/health`

检查服务状态。

**响应示例：**
```json
{
  "status": "healthy",
  "version": "1.0.0",
  "timestamp": "2026-06-21T12:00:00"
}
```

### 2. 提交解析任务

**POST** `/api/v1/parse`

提交书籍解析任务（异步）。

**请求体：**
```json
{
  "book_path": "/path/to/book.pdf",
  "discipline": "哲学",
  "config": {
    "llm": {
      "max_parallel": 4
    }
  }
}
```

**响应示例：**
```json
{
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "pending",
  "progress": 0.0,
  "message": "任务已创建，等待处理",
  "created_at": "2026-06-21T12:00:00",
  "updated_at": "2026-06-21T12:00:00"
}
```

### 3. 查询任务状态

**GET** `/api/v1/status/{task_id}`

查询任务执行状态和进度。

**响应示例：**
```json
{
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "processing",
  "progress": 0.5,
  "message": "正在处理 chunk 15/30",
  "created_at": "2026-06-21T12:00:00",
  "updated_at": "2026-06-21T12:05:00"
}
```

**状态说明：**
- `pending`: 等待处理
- `processing`: 正在处理
- `completed`: 已完成
- `failed`: 处理失败
- `cancelled`: 已取消

### 4. 获取任务结果

**GET** `/api/v1/result/{task_id}`

获取任务最终结果（仅在任务完成后可用）。

**响应示例：**
```json
{
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
  "success": true,
  "output_path": "/data/obsidian/📚 知识图谱/哲学/西方哲学/书籍图谱/沉思录.md",
  "metadata": {
    "title": "沉思录",
    "author": "马可·奥勒留",
    "discipline": "哲学"
  },
  "elapsed_seconds": 240.5
}
```

### 5. 列出任务

**GET** `/api/v1/tasks?status=processing&limit=10`

列出所有任务或按状态筛选。

**查询参数：**
- `status`: 按状态筛选（可选）
- `limit`: 返回数量限制（默认 20）

**响应示例：**
```json
[
  {
    "task_id": "550e8400-e29b-41d4-a716-446655440000",
    "status": "completed",
    "progress": 1.0,
    "message": "处理完成",
    "created_at": "2026-06-21T12:00:00",
    "updated_at": "2026-06-21T12:04:00"
  }
]
```

### 6. 取消任务

**DELETE** `/api/v1/task/{task_id}`

取消正在执行的任务（仅限 pending 状态）。

**响应示例：**
```json
{
  "message": "任务已取消",
  "task_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

## 使用示例

### Python 客户端

```python
import requests
import time

# 提交任务
response = requests.post(
    "http://localhost:8000/api/v1/parse",
    json={"book_path": "/path/to/book.pdf", "discipline": "哲学"}
)
task_id = response.json()["task_id"]

# 轮询状态
while True:
    status = requests.get(f"http://localhost:8000/api/v1/status/{task_id}").json()
    
    if status["status"] in ["completed", "failed"]:
        break
    
    print(f"进度: {status['progress'] * 100:.1f}%")
    time.sleep(10)

# 获取结果
result = requests.get(f"http://localhost:8000/api/v1/result/{task_id}").json()
print(f"输出路径: {result['output_path']}")
```

### curl 命令

```bash
# 提交任务
curl -X POST http://localhost:8000/api/v1/parse \
  -H "Content-Type: application/json" \
  -d '{"book_path": "/path/to/book.pdf", "discipline": "哲学"}'

# 查询状态
curl http://localhost:8000/api/v1/status/{task_id}

# 获取结果
curl http://localhost:8000/api/v1/result/{task_id}
```

## 错误处理

### 错误响应格式

```json
{
  "detail": "错误描述"
}
```

### 常见错误码

- `400 Bad Request`: 请求参数错误
- `404 Not Found`: 任务不存在
- `500 Internal Server Error`: 服务器内部错误

## 生产环境建议

### 1. 使用 Redis 替代内存任务管理

```python
# 安装 redis
pip install redis

# 使用 Celery 任务队列
from celery import Celery

app = Celery('bookgraph', broker='redis://localhost:6379/0')
```

### 2. 添加认证

```python
from fastapi.security import HTTPBearer

security = HTTPBearer()

@app.post("/api/v1/parse", dependencies=[Depends(security)])
async def parse_book(request: ParseBookRequest):
    ...
```

### 3. 限流保护

```python
from fastapi_limiter import FastAPILimiter
from fastapi_limiter.depends import RateLimiter

@app.post("/api/v1/parse", dependencies=[Depends(RateLimiter(times=10, seconds=60))])
async def parse_book(request: ParseBookRequest):
    ...
```

### 4. 日志和监控

```python
import logging
from prometheus_fastapi_instrumentator import Instrumentator

# 配置日志
logging.basicConfig(level=logging.INFO)

# Prometheus 监控
Instrumentator().instrument(app).expose(app)
```

## 许可证

MIT License

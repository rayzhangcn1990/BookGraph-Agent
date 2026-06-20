"""
BookGraph-Agent FastAPI 服务化封装

提供 RESTful API 接口，支持外部系统调用书籍解析能力
"""

from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from typing import Dict, List, Optional
import uuid
import logging
from datetime import datetime
import asyncio

logger = logging.getLogger("BookGraph-Agent")

# ═══════════════════════════════════════════════════════════
# FastAPI 应用
# ═══════════════════════════════════════════════════════════

app = FastAPI(
    title="BookGraph-Agent API",
    description="书籍解析与知识图谱生成服务",
    version="1.0.0"
)

# 任务管理器（简化版，生产环境应使用 Redis/Celery）
task_manager = {
    "tasks": {},  # task_id -> task_info
    "results": {}  # task_id -> result
}


# ═══════════════════════════════════════════════════════════
# 请求/响应模型
# ═══════════════════════════════════════════════════════════

class ParseBookRequest(BaseModel):
    """解析书籍请求"""
    book_path: str = Field(..., description="书籍文件路径（PDF/EPUB/MOBI）")
    discipline: Optional[str] = Field(None, description="学科（可选）")
    config: Optional[Dict] = Field(None, description="配置覆盖（可选）")


class TaskStatusResponse(BaseModel):
    """任务状态响应"""
    task_id: str
    status: str  # pending/processing/completed/failed
    progress: Optional[float] = None  # 0-1
    message: Optional[str] = None
    created_at: str
    updated_at: str


class TaskResultResponse(BaseModel):
    """任务结果响应"""
    task_id: str
    success: bool
    output_path: Optional[str] = None
    metadata: Optional[Dict] = None
    error: Optional[str] = None
    elapsed_seconds: float


class HealthResponse(BaseModel):
    """健康检查响应"""
    status: str
    version: str
    timestamp: str


# ═══════════════════════════════════════════════════════════
# 核心端点
# ═══════════════════════════════════════════════════════════

@app.get("/health", response_model=HealthResponse)
async def health_check():
    """健康检查端点"""
    return HealthResponse(
        status="healthy",
        version="1.0.0",
        timestamp=datetime.now().isoformat()
    )


@app.post("/api/v1/parse", response_model=TaskStatusResponse)
async def parse_book(request: ParseBookRequest, background_tasks: BackgroundTasks):
    """
    解析书籍（异步）

    提交书籍解析任务，立即返回 task_id，后台异步处理
    """
    # 生成任务 ID
    task_id = str(uuid.uuid4())

    # 初始化任务状态
    task_manager["tasks"][task_id] = {
        "status": "pending",
        "progress": 0.0,
        "message": "任务已创建，等待处理",
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
        "request": request.dict()
    }

    # 添加后台任务
    background_tasks.add_task(
        process_book_async,
        task_id,
        request.book_path,
        request.discipline,
        request.config
    )

    logger.info(f"任务创建: {task_id} - {request.book_path}")

    return TaskStatusResponse(
        task_id=task_id,
        status="pending",
        progress=0.0,
        message="任务已创建，等待处理",
        created_at=task_manager["tasks"][task_id]["created_at"],
        updated_at=task_manager["tasks"][task_id]["updated_at"]
    )


@app.get("/api/v1/status/{task_id}", response_model=TaskStatusResponse)
async def get_status(task_id: str):
    """
    查询任务状态

    返回任务的当前状态、进度和消息
    """
    if task_id not in task_manager["tasks"]:
        raise HTTPException(status_code=404, detail="任务不存在")

    task_info = task_manager["tasks"][task_id]

    return TaskStatusResponse(
        task_id=task_id,
        status=task_info["status"],
        progress=task_info.get("progress"),
        message=task_info.get("message"),
        created_at=task_info["created_at"],
        updated_at=task_info["updated_at"]
    )


@app.get("/api/v1/result/{task_id}", response_model=TaskResultResponse)
async def get_result(task_id: str):
    """
    获取任务结果

    返回任务的最终结果（仅在任务完成后可用）
    """
    if task_id not in task_manager["tasks"]:
        raise HTTPException(status_code=404, detail="任务不存在")

    task_info = task_manager["tasks"][task_id]

    if task_info["status"] not in ["completed", "failed"]:
        raise HTTPException(status_code=400, detail="任务尚未完成")

    if task_id not in task_manager["results"]:
        raise HTTPException(status_code=404, detail="结果不存在")

    result = task_manager["results"][task_id]

    return TaskResultResponse(
        task_id=task_id,
        success=result["success"],
        output_path=result.get("output_path"),
        metadata=result.get("metadata"),
        error=result.get("error"),
        elapsed_seconds=result.get("elapsed_seconds", 0.0)
    )


@app.get("/api/v1/tasks", response_model=List[TaskStatusResponse])
async def list_tasks(status: Optional[str] = None, limit: int = 20):
    """
    列出任务

    返回所有任务或按状态筛选的任务列表
    """
    tasks = []

    for task_id, task_info in task_manager["tasks"].items():
        if status and task_info["status"] != status:
            continue

        tasks.append(TaskStatusResponse(
            task_id=task_id,
            status=task_info["status"],
            progress=task_info.get("progress"),
            message=task_info.get("message"),
            created_at=task_info["created_at"],
            updated_at=task_info["updated_at"]
        ))

        if len(tasks) >= limit:
            break

    return tasks


@app.delete("/api/v1/task/{task_id}")
async def cancel_task(task_id: str):
    """
    取消任务

    取消正在执行的任务（仅限 pending 状态）
    """
    if task_id not in task_manager["tasks"]:
        raise HTTPException(status_code=404, detail="任务不存在")

    task_info = task_manager["tasks"][task_id]

    if task_info["status"] not in ["pending", "processing"]:
        raise HTTPException(status_code=400, detail="任务已执行完成，无法取消")

    # 更新状态
    task_info["status"] = "cancelled"
    task_info["message"] = "用户取消"
    task_info["updated_at"] = datetime.now().isoformat()

    return {"message": "任务已取消", "task_id": task_id}


# ═══════════════════════════════════════════════════════════
# 后台任务处理
# ═══════════════════════════════════════════════════════════

async def process_book_async(
    task_id: str,
    book_path: str,
    discipline: Optional[str] = None,
    config_override: Optional[Dict] = None
):
    """
    后台异步处理书籍

    Args:
        task_id: 任务 ID
        book_path: 书籍路径
        discipline: 学科
        config_override: 配置覆盖
    """
    start_time = datetime.now()

    try:
        # 更新状态：处理中
        task_manager["tasks"][task_id]["status"] = "processing"
        task_manager["tasks"][task_id]["message"] = "正在解析书籍"
        task_manager["tasks"][task_id]["updated_at"] = datetime.now().isoformat()

        # 加载配置
        import yaml
        with open("config.yaml", "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)

        if config_override:
            config.update(config_override)

        # 调用编排器
        from core.agent_orchestrator import BookGraphAgentOrchestrator
        orchestrator = BookGraphAgentOrchestrator(config)

        # 更新进度
        task_manager["tasks"][task_id]["progress"] = 0.1
        task_manager["tasks"][task_id]["message"] = "初始化完成"

        # 执行解析
        result = await orchestrator.run(book_path)

        # 更新状态：完成
        elapsed = (datetime.now() - start_time).total_seconds()

        task_manager["tasks"][task_id]["status"] = "completed"
        task_manager["tasks"][task_id]["progress"] = 1.0
        task_manager["tasks"][task_id]["message"] = "处理完成"
        task_manager["tasks"][task_id]["updated_at"] = datetime.now().isoformat()

        # 保存结果
        task_manager["results"][task_id] = {
            "success": result.success,
            "output_path": result.output_path,
            "metadata": result.metadata,
            "error": result.error,
            "elapsed_seconds": elapsed
        }

        logger.info(f"任务完成: {task_id} ({elapsed:.1f}秒)")

    except Exception as e:
        # 更新状态：失败
        elapsed = (datetime.now() - start_time).total_seconds()

        task_manager["tasks"][task_id]["status"] = "failed"
        task_manager["tasks"][task_id]["message"] = f"处理失败: {str(e)}"
        task_manager["tasks"][task_id]["updated_at"] = datetime.now().isoformat()

        # 保存错误结果
        task_manager["results"][task_id] = {
            "success": False,
            "error": str(e),
            "elapsed_seconds": elapsed
        }

        logger.error(f"任务失败: {task_id} - {e}")


# ═══════════════════════════════════════════════════════════
# 启动脚本
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

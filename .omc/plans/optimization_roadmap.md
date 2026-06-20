# BookGraph-Agent 优化路线图

## 执行阶段

### Phase 1: 性能优化（P0，1-2周）
- [ ] 完善原生异步处理（`NativeAsyncChunkProcessor`）
- [ ] 实现降级策略自动化（重试耗尽后自动降级）
- [ ] 质量门控前置（Per-Chunk 检查）

### Phase 2: Agent工具化（P1，2-4周）
- [ ] 工具层封装（`BookParserTool`, `ChunkProcessorTool`, `GraphGeneratorTool`）
- [ ] 编排层统一入口（`BookGraphAgentOrchestrator`）
- [ ] 混合缓存策略（L1内存 + L2文件 + L3向量）

### Phase 3: 记忆层与状态管理（P2，4-8周）
- [ ] 分层记忆实现（`AgentMemoryManager`）
- [ ] 自我反思机制（`AgentReflector`）
- [ ] 多轮对话支持

### Phase 4: API服务化（P3，8-12周）
- [ ] FastAPI端点实现
- [ ] MCP协议兼容
- [ ] Docker容器化部署

## 成功指标

| 指标 | 当前 | 目标 |
|------|------|------|
| 单书处理时长 | 10分钟 | 4-6分钟 |
| 批量吞吐量 | 1本/10分钟 | 3-5本/10分钟 |
| 缓存命中率 | 20% | 50-70% |
| 重试成功率 | 60% | 85% |
| 模块耦合度 | 高 | 低 |

## 风险监控

- 每周Review进度
- 性能基准测试（处理10本书统计耗时）
- 代码质量审查（模块依赖关系）

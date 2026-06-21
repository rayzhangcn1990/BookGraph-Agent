#!/bin/bash
# 设置定期质量检查的 Cron 任务

# 获取当前目录
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# 创建日志目录
mkdir -p "$PROJECT_DIR/logs"

# 添加 Cron 任务
# 每周日凌晨 3 点执行质量检查
CRON_JOB="0 3 * * 0 cd $PROJECT_DIR && /usr/bin/python3 $PROJECT_DIR/core/function_selector.py quality_check --vault \"\$OBSIDIAN_VAULT_PATH\" --output $PROJECT_DIR/logs/quality_report_\$(date +\\%Y\\%m\\%d).md >> $PROJECT_DIR/logs/quality_check.log 2>&1"

# 检查是否已存在
if crontab -l | grep -q "quality_check"; then
    echo "Cron 任务已存在，跳过"
else
    # 添加任务
    (crontab -l 2>/dev/null; echo "$CRON_JOB") | crontab -
    echo "✅ Cron 任务已添加：每周日凌晨 3 点执行质量检查"
fi

# 显示当前 Cron 任务
echo ""
echo "当前 Cron 任务："
crontab -l 2>/dev/null || echo "无"

echo ""
echo "日志目录: $PROJECT_DIR/logs"
echo "报告路径: $PROJECT_DIR/logs/quality_report_YYYYMMDD.md"

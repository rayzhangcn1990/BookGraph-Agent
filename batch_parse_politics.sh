#!/bin/bash
# 使用Claude Code解析政治学书籍脚本

set -e

BOOKS_DIR="/Users/rayzhang/Documents/书/1.哲学/1-1.政治学"
NOTES_DIR="/Users/rayzhang/Documents/知识体系/📚 知识图谱/政治学/书籍图谱"
LOG_FILE="/tmp/bookgraph_batch.log"

# 待解析书籍列表（按格式优先级排序）
UNPARSED_BOOKS=(
    "世界秩序.epub"
    "中国历史通论.epub"
    "中国的选择：中美博弈与战略抉择.epub"
    "兴盛与危机-论中国社会超稳定结构.epub"
    "制内市场：中国国家主导型政治经济学.epub"
    "历史的地理枢纽.epub"
    "大棋局：美国的首要地位及其地缘战略.epub"
    "开放社会及其敌人.epub"
    "当代学术入门：政治学.epub"
    "政治学——谁得到什么？何时和如何得到.epub"
    "政治学通识.epub"
    "文明的冲突与世界秩序的重建 .epub"
    "理解现代政治.epub"
    "硬球：政治是这样玩的.epub"
    "自由人的平等政治.epub"
    "近代中国社会的新陈代谢.epub"
    "社会契约论 - 卢梭.mobi"
    "政治经济学通识.pdf"
)

# 日志函数
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

# 检查书籍是否已解析
is_book_parsed() {
    local book_file="$1"
    local book_name=$(basename "$book_file" | sed 's/\.[^.]*$//')
    
    # 清理名称进行匹配
    local clean_name=$(echo "$book_name" | sed 's/：/:/g' | sed 's/（/(/g' | sed 's/）/)/g' | cut -d: -f1 | cut -d'(' -f1 | sed 's/ *$//')
    
    # 检查笔记是否存在
    if ls "$NOTES_DIR"/*.md 2>/dev/null | grep -q "$clean_name"; then
        return 0
    fi
    return 1
}

# 使用Claude Code解析单本书籍
parse_book_with_claude() {
    local book_file="$1"
    local book_name=$(basename "$book_file")
    
    log "开始解析: $book_name"
    
    # 构建Claude Code命令
    local claude_cmd="使用BookGraph-Agent解析书籍：$book_file，学科分类为政治哲学"
    
    # 使用Claude Code执行
    claude --acp --stdio "$claude_cmd" 2>&1 | tee -a "$LOG_FILE"
    
    local exit_code=${PIPESTATUS[0]}
    
    if [ $exit_code -eq 0 ]; then
        log "✅ 成功解析: $book_name"
        return 0
    else
        log "❌ 解析失败: $book_name (退出码: $exit_code)"
        return 1
    fi
}

# 主函数
main() {
    log "=========================================="
    log "开始批量解析政治学书籍"
    log "待解析书籍数: ${#UNPARSED_BOOKS[@]}"
    log "=========================================="
    
    local success_count=0
    local fail_count=0
    local skip_count=0
    
    for book in "${UNPARSED_BOOKS[@]}"; do
        local book_path="$BOOKS_DIR/$book"
        
        # 检查文件是否存在
        if [ ! -f "$book_path" ]; then
            log "⚠️  文件不存在: $book"
            ((fail_count++))
            continue
        fi
        
        # 检查是否已解析
        if is_book_parsed "$book_path"; then
            log "⏭️  跳过已解析: $book"
            ((skip_count++))
            continue
        fi
        
        # 解析书籍
        if parse_book_with_claude "$book_path"; then
            ((success_count++))
            
            # 随机sleep 200-500秒
            local sleep_time=$((200 + RANDOM % 301))
            log "⏳ 等待 ${sleep_time} 秒后继续..."
            sleep $sleep_time
        else
            ((fail_count++))
        fi
    done
    
    log "=========================================="
    log "批量解析完成"
    log "成功: $success_count"
    log "失败: $fail_count"
    log "跳过: $skip_count"
    log "=========================================="
}

# 执行主函数
main "$@"
#!/bin/bash
# 政治学书籍批量解析脚本
# 使用 BookGraph Agent 解析未处理书籍
# 每完成一本书后 sleep 200-500 秒

BOOKS_DIR="$HOME/Documents/书/1.哲学/1-1.政治学"
OUTPUT_DIR="$HOME/Documents/知识体系/📚 知识图谱/政治学/书籍图谱"
SLEEP_MIN=200
SLEEP_MAX=500

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# 获取未解析书籍列表
get_unprocessed() {
    cd "$BOOKS_DIR"
    for f in *.epub *.pdf *.mobi; do
        [ -f "$f" ] || continue
        # 提取书名（去掉扩展名）
        book_name=$(basename "$f" | sed 's/\.[epub|pdf|mobi]$//' | sed 's/\.[^.]*$//')
        # 检查是否已解析
        if [ ! -f "$OUTPUT_DIR/${book_name}.md" ]; then
            echo "$f"
        fi
    done
}

# 随机 sleep
random_sleep() {
    sleep_time=$((RANDOM % (SLEEP_MAX - SLEEP_MIN + 1) + SLEEP_MIN))
    log_info "等待 ${sleep_time} 秒..."
    sleep $sleep_time
}

# 解析单本书
process_book() {
    book_file="$1"
    book_path="$BOOKS_DIR/$book_file"

    log_info "开始解析: $book_file"

    # 调用 BookGraph Agent
    python3 main.py --input "$book_path" --discipline 政治学

    if [ $? -eq 0 ]; then
        log_info "✅ 完成: $book_file"
        return 0
    else
        log_error "❌ 失败: $book_file"
        return 1
    fi
}

# 主循环
main() {
    log_info "══════════════════════════════════════════════════════"
    log_info "政治学书籍批量解析"
    log_info "══════════════════════════════════════════════════════"
    log_info "书籍目录: $BOOKS_DIR"
    log_info "输出目录: $OUTPUT_DIR"

    # 获取未解析书籍
    unprocessed=$(get_unprocessed)
    total=$(echo "$unprocessed" | wc -l)

    log_info "待解析书籍: $total 本"
    log_info ""

    if [ -z "$unprocessed" ]; then
        log_info "✅ 所有书籍已解析完成！"
        exit 0
    fi

    # 统计
    success=0
    failed=0
    count=0

    # 遍历解析
    for book in $unprocessed; do
        count=$((count + 1))
        log_info "[${count}/${total}] 处理: $book"

        if process_book "$book"; then
            success=$((success + 1))
            # 随机等待（最后一本不等待）
            if [ $count -lt $total ]; then
                random_sleep
            fi
        else
            failed=$((failed + 1))
            log_warn "跳过继续下一本..."
            sleep 30  # 失败后短等待
        fi
    done

    # 输出报告
    log_info ""
    log_info "══════════════════════════════════════════════════════"
    log_info "批量处理完成"
    log_info "══════════════════════════════════════════════════════"
    log_info "总书籍: $total"
    log_info "✅ 成功: $success"
    log_info "❌ 失败: $failed"
    log_info "══════════════════════════════════════════════════════"
}

main "$@"
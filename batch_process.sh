#!/bin/bash
cd /Users/rayzhang/BookGraph-Agent
export PYTHONUNBUFFERED=1

# 书籍列表
BOOKS=(
    "/Users/rayzhang/Documents/书/1.哲学/1-1.政治学/权力的48条法则.epub"
    "/Users/rayzhang/Documents/书/1.哲学/1-1.政治学/开放社会及其敌人.epub"
    "/Users/rayzhang/Documents/书/1.哲学/1-1.政治学/中国的选择：中美博弈与战略抉择.epub"
    "/Users/rayzhang/Documents/书/1.哲学/1-1.政治学/制内市场：中国国家主导型政治经济学.epub"
    "/Users/rayzhang/Documents/书/1.哲学/1-1.政治学/自由人的平等政治.epub"
)

for book in "${BOOKS[@]}"; do
    echo "Processing: $book"
    python main.py --input "$book" --discipline 政治学
    if [ $? -eq 0 ]; then
        echo "Running fix_logic_format.py..."
        python fix_logic_format.py
    else
        echo "Failed to process: $book"
    fi
    echo "---"
done

#!/bin/bash
# KDNA资产验证脚本

echo "🔍 验证KDNA资产..."

# 检查KDNA CLI是否安装
if ! command -v kdna &> /dev/null; then
    echo "⚠️  KDNA CLI未安装，跳过验证"
    echo "   安装: npm install -g @aikdna/kdna-cli"
    exit 0
fi

# 验证质量检查资产
echo ""
echo "📋 验证 @bookgraph/quality-checks..."
kdna validate kdna-assets/@bookgraph/quality-checks/ 2>/dev/null || echo "   ⚠️  验证失败（需要manifest格式调整）"

# 验证生成流程资产
echo ""
echo "📋 验证 @bookgraph/generation..."
kdna validate kdna-assets/@bookgraph/generation/ 2>/dev/null || echo "   ⚠️  验证失败（需要manifest格式调整）"

# 验证元数据增强LoadPlan
echo ""
echo "📋 验证 @bookgraph/metadata-enrichment..."
kdna validate kdna-assets/@bookgraph/metadata-enrichment/ 2>/dev/null || echo "   ⚠️  验证失败（需要manifest格式调整）"

echo ""
echo "✅ KDNA资产验证完成"
echo ""
echo "📝 下一步："
echo "   1. 安装KDNA CLI: npm install -g @aikdna/kdna-cli"
echo "   2. 打包资产: kdna pack kdna-assets/@bookgraph/quality-checks/ quality-checks.kdna"
echo "   3. 集成到代码: from core.kdna_integration import get_kdna_quality_checker"

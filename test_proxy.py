"""Test proxy with real chunk content."""
import requests, json, re, os

api_key = "freellmapi-2148be2025c27b01d9096ffb1690241b2ce4e4c6625b244a"

chunk_text = """尼采的哲学思想在《瞧，这个人》中达到了最集中的表达。他宣称"重估一切价值"
（Umwertung aller Werte）是哲学的最高任务，认为基督教道德体系是弱者的怨恨（Ressentiment）
产物，真正的道德应当是主人道德——强者的自我肯定，是其生命力的自然表达。他提出"超人"
（Ubermensch）概念，并非生物进化论意义上的物种提升，而是在精神领域通过永恒回归的考验、
自我克服而达到的最高存在形态，是能够为大地赋予新意义、创造新价值的人。权力意志
（Wille zur Macht）作为理解宇宙万物的终极原则被提出——不是叔本华式的消极生存意志，
而是积极的、自我超越的创造性力量。"""

resp = requests.post(
    'http://localhost:3001/v1/chat/completions',
    json={
        'model': 'auto',
        'messages': [
            {'role': 'system', 'content': '你必须以纯JSON格式输出，不可包含任何markdown代码块标记。字段: core_concepts(数组,每个元素有name和definition), key_insights(数组,每个有insight和explanation), golden_quotes(数组,每个有quote和interpretation)'},
            {'role': 'user', 'content': '分析这段哲学文本：' + chunk_text}
        ],
        'max_tokens': 4096,
        'temperature': 0.3,
    },
    headers={'Authorization': f'Bearer {api_key}'},
    timeout=120
)

print(f'Status: {resp.status_code}')
data = resp.json()

if 'choices' not in data:
    print(f'No choices in response: {json.dumps(data, ensure_ascii=False)[:500]}')
else:
    content = data['choices'][0]['message']['content']
    model_used = data.get('model', 'unknown')
    print(f'Model: {model_used}')
    print(f'Content ({len(content)} chars)')
    print('---FIRST 400---')
    print(content[:400])
    print('---LAST 200---')
    print(content[-200:])

    # Validate JSON
    cleaned = content.strip()
    cleaned = re.sub(r'^```json\s*', '', cleaned)
    cleaned = re.sub(r'^```\s*', '', cleaned)
    cleaned = re.sub(r'\s*```$', '', cleaned)
    try:
        parsed = json.loads(cleaned)
        print(f'VALID JSON! Keys: {list(parsed.keys())}')
    except Exception as e:
        print(f'JSON parse failed: {e}')
        # Show raw cleaned content
        print('---CLEANED---')
        print(cleaned[:500])
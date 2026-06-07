#!/usr/bin/env python3
"""Direct book processing script that bypasses LLM client complexity."""
import sys, os, json, re, time, requests
from pathlib import Path

# ============ CONFIG ============
PROXY_URL = "http://localhost:3001/v1/chat/completions"
API_KEY = "freellmapi-2148be2025c27b01d9096ffb1690241b2ce4e4c6625b244a"
MODEL = "auto"
CHUNK_SIZE = 3000  # small chunks for fast processing
MAX_RETRIES = 5
TIMEOUT = 600  # 10 min timeout for first slow request

# ============ PARSE EPUB ============
def parse_book(filepath):
    """Parse EPUB and return text."""
    import ebooklib
    from ebooklib import epub
    from bs4 import BeautifulSoup

    book = epub.read_epub(filepath)
    text_parts = []
    for item in book.get_items():
        if item.get_type() == ebooklib.ITEM_DOCUMENT:
            soup = BeautifulSoup(item.content, 'html.parser')
            text_parts.append(soup.get_text(separator='\n', strip=True))
    return '\n\n'.join(text_parts)

# ============ CHUNK ============
def chunk_text(text, size=CHUNK_SIZE):
    """Split text into chunks."""
    words = list(text)
    return [''.join(words[i:i+size]) for i in range(0, len(words), size)]

# ============ CALL LLM ============
def call_llm(prompt_content, system="Extract structured info as JSON. Fields: core_concepts(array), key_insights(array), key_quotes(array)"):
    """Call proxy API and extract JSON from response."""
    resp = requests.post(
        PROXY_URL,
        json={
            "model": MODEL,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt_content}
            ],
            "max_tokens": 2048,
            "temperature": 0.3,
        },
        headers={"Authorization": f"Bearer {API_KEY}"},
        timeout=TIMEOUT
    )
    data = resp.json()
    if "choices" not in data:
        return None, f"API error: {data.get('error', {}).get('message', str(data)[:200])}"

    content = data["choices"][0]["message"]["content"]
    model_used = data.get("model", "?")

    # Clean and extract JSON
    cleaned = content.strip()
    cleaned = re.sub(r'^```(json)?\s*', '', cleaned)
    cleaned = re.sub(r'\s*```$', '', cleaned)

    try:
        return json.loads(cleaned), f"OK(model={model_used})"
    except json.JSONDecodeError:
        # Try to find JSON object in response
        start = cleaned.find('{')
        if start >= 0:
            depth, end = 0, start
            for i, c in enumerate(cleaned[start:], start):
                if c == '{': depth += 1
                elif c == '}': depth -= 1
                if depth == 0: end = i + 1; break
            try:
                return json.loads(cleaned[start:end]), f"EXTRACTED(model={model_used})"
            except:
                pass
        return None, f"NO_JSON(model={model_used}, len={len(content)})"

# ============ MAIN ============
if __name__ == "__main__":
    book_path = sys.argv[1] if len(sys.argv) > 1 else "/Users/rayzhang/Documents/书/1.哲学/1-5.西方哲学/瞧，这个人.epub"
    book_name = Path(book_path).stem

    print(f"📖 Processing: {book_name}")

    # Parse
    print("   Parsing...", end=" ", flush=True)
    text = parse_book(book_path)
    print(f"✅ {len(text)} chars")

    # Chunk
    chunks = chunk_text(text)
    print(f"   🧩 {len(chunks)} chunks (each ~{CHUNK_SIZE} chars)")

    # Process each chunk
    results = []
    for i, chunk in enumerate(chunks):
        print(f"   ▶️ Chunk {i+1}/{len(chunks)}...", end=" ", flush=True)

        result = None
        for attempt in range(MAX_RETRIES):
            t0 = time.time()
            result, status = call_llm(chunk[:CHUNK_SIZE])
            elapsed = time.time() - t0

            if result is not None:
                print(f"✅ ({elapsed:.0f}s, {status})")
                results.append(result)
                break
            else:
                print(f"⚠️ ({elapsed:.0f}s, {status}, retry {attempt+1}/{MAX_RETRIES})", end=" ", flush=True)
                time.sleep(15 * (attempt + 1))  # increasing delay
        else:
            print(f"❌ Failed after {MAX_RETRIES} retries")

    # Summary
    print(f"\n📊 Results: {len(results)}/{len(chunks)} chunks successful")

    # Save
    output_dir = Path("/tmp/bookgraph_output")
    output_dir.mkdir(exist_ok=True)
    output_file = output_dir / f"{book_name}_results.json"
    with open(output_file, 'w') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"💾 Saved to {output_file}")
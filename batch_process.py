#!/usr/bin/env python3
"""Batch process all books in the philosophy directory."""
import sys, os, json, re, time, requests, ebooklib, logging
from pathlib import Path
from bs4 import BeautifulSoup
from ebooklib import epub
import concurrent.futures

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(message)s', datefmt='%H:%M:%S')
log = logging.getLogger('batch')

# ============ CONFIG ============
PROXY_URL = "http://localhost:3001/v1/chat/completions"
API_KEY = "freellmapi-2148be2025c27b01d9096ffb1690241b2ce4e4c6625b244a"
MODEL = "auto"
CHUNK_SIZE = 2000
MAX_RETRIES = 5
TIMEOUT = 600
MAX_WORKERS = 4
BOOKS_DIR = Path("/Users/rayzhang/Documents/书/1.哲学/1-5.西方哲学")
OUTPUT_DIR = Path("/tmp/bookgraph_batch")
SKIP_EXISTING = True  # Skip books already processed

SUPPORTED = {'.epub'}
ALREADY_DONE = {"思辨的张力—黑格尔辩证法新探", "沉思录"}  # already in Obsidian vault

def parse_epub(filepath):
    book = epub.read_epub(filepath)
    text_parts = []
    for item in book.get_items():
        if item.get_type() == ebooklib.ITEM_DOCUMENT:
            soup = BeautifulSoup(item.content, 'html.parser')
            text_parts.append(soup.get_text(separator='\n', strip=True))
    return '\n\n'.join(text_parts)

def chunk_text(text, size=CHUNK_SIZE):
    chars = list(text)
    return [''.join(chars[i:i+size]) for i in range(0, len(chars), size)]

def call_llm(content):
    resp = requests.post(
        PROXY_URL,
        json={
            "model": MODEL,
            "messages": [
                {"role": "system", "content": "Extract structured data as JSON only. Fields: core_concepts(array), key_insights(array), key_quotes(array)"},
                {"role": "user", "content": content}
            ],
            "max_tokens": 2048,
            "temperature": 0.3,
        },
        headers={"Authorization": f"Bearer {API_KEY}"},
        timeout=TIMEOUT
    )
    data = resp.json()
    if "choices" not in data:
        return None
    content = data["choices"][0]["message"]["content"]
    cleaned = content.strip()
    cleaned = re.sub(r'^```(json)?\s*', '', cleaned)
    cleaned = re.sub(r'\s*```$', '', cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find('{')
        if start >= 0:
            depth, end = 0, start
            for i, c in enumerate(cleaned[start:], start):
                if c == '{': depth += 1
                elif c == '}': depth -= 1
                if depth == 0: end = i + 1; break
            try:
                return json.loads(cleaned[start:end])
            except:
                pass
    return None

def process_book(book_path):
    book_name = Path(book_path).stem
    for suffix in [' (邓晓芒)', ' (阿尔贝•加缪)', '（阿尔贝·加缪）', ' ']:
        book_name = book_name.replace(suffix, '')

    output_file = OUTPUT_DIR / book_name / "chunks.json"
    if SKIP_EXISTING and output_file.exists():
        return f"⏭️ {book_name}"
    if output_file.exists():
        return f"⏭️ {book_name}"

    try:
        text = parse_epub(book_path)
        chunks = chunk_text(text)
    except Exception as e:
        return f"❌ {book_name}: parse fail - {e}"

    t_start = time.time()
    results = [None] * len(chunks)

    def process_idx(i):
        c = chunks[i]
        for attempt in range(MAX_RETRIES):
            t0 = time.time()
            r = call_llm(c[:CHUNK_SIZE])
            if r is not None:
                return i, r
            if attempt < MAX_RETRIES - 1:
                time.sleep(15 * (attempt + 1))
        return i, None

    # Track progress
    done_count = [0]

    def on_result(future):
        i, r = future.result()
        results[i] = r
        done_count[0] += 1
        mark = "." if r is not None else "x"
        print(mark, end="", flush=True)

    print(f"📖 {book_name} ({len(chunks)} chunks)", end=" ", flush=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = [ex.submit(process_idx, i) for i in range(len(chunks))]
        for f in futures:
            on_result(f)

    elapsed = time.time() - t_start
    results = [r for r in results if r is not None]

    output_dir = OUTPUT_DIR / book_name
    output_dir.mkdir(parents=True, exist_ok=True)
    with open(output_file, 'w') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    pct = len(results) / max(len(chunks), 1) * 100
    print(f" {len(results)}/{len(chunks)} ({elapsed:.0f}s)")
    return f"✅ {book_name}: {len(results)}/{len(chunks)}"

def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Find all books
    book_files = []
    for ext in SUPPORTED:
        book_files.extend(BOOKS_DIR.glob(f"*{ext}"))

    # Filter out already done
    to_process = []
    for bf in sorted(book_files):
        name = Path(bf).stem
        if name not in ALREADY_DONE:
            to_process.append(bf)

    print(f"🎯 {len(to_process)} books to process out of {len(book_files)} total")
    print(f"   Output: {OUTPUT_DIR}")
    print()

    # Process books sequentially, chunks within each book concurrently
    for i, book_path in enumerate(to_process):
        result = process_book(book_path)
        print(f"[{i+1}/{len(to_process)}] {result}")

    print(f"\n📊 Done! Results in {OUTPUT_DIR}")

if __name__ == "__main__":
    main()
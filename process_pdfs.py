import os
import sys
import json
import re
import time
import contextlib
import argparse
import glob
from statistics import mean, stdev
from collections import defaultdict
from langdetect import detect
from concurrent.futures import ThreadPoolExecutor
import pdfplumber

REPEATED_CHARS_REGEX = re.compile(r"(.)\1{2,}", re.IGNORECASE)
HEADING_DIGIT_ONLY_RE = re.compile(r"^\s*(\d+[.)-]?\s*)+$")
SERIAL_LINE_PATTERN = re.compile(r"^(S\.?\s?No\.?)((\s+\d+\.*)+)$", re.IGNORECASE)

def reverse_if_rtl(text, lang):
    return text[::-1] if lang in ["ar", "he", "fa", "ur"] else text

def clean_text(text):
    if not isinstance(text, str):
        return ""
    if REPEATED_CHARS_REGEX.fullmatch(text.replace(" ", "")):
        return ""
    text = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", text)
    return re.sub(r"\s+", " ", text).strip()

def get_table_bbox(page):
    return [t.bbox for t in page.find_tables() if t.bbox]

def is_inside_table(y, x0, x1, table_bboxes):
    overlap_margin = 3
    return any(
        y0t <= y <= y1t and not (x1 < x0t - overlap_margin or x0 > x1t + overlap_margin)
        for x0t, y0t, x1t, y1t in table_bboxes
    )

def is_heading_dynamic(text, fontname, size, size_stats, y_pos, page_height, lang="en", threshold_factor=1.0, top_margin=0.10, bottom_margin=0.95):
    ts = text.strip()
    if y_pos < page_height * top_margin or y_pos > page_height * bottom_margin:
        return False
    if lang == "en":
        if (not ts or len(ts) < 3 or re.fullmatch(r"\W+", ts) or ts.isdigit() or
            re.search(r"(?i)(https?://\S+|www\.\S+|\S+\.com\b)", ts) or
            HEADING_DIGIT_ONLY_RE.match(ts)):
            return False
    else:
        if len(ts) > 200 or len(ts) < 2:
            return False

    is_bold = 'bold' in fontname.lower() or 'black' in fontname.lower()
    is_outlier_size = size_stats['stdev'] > 0 and size > size_stats['mean'] + threshold_factor * size_stats['stdev']
    return is_bold or is_outlier_size

def get_level_by_rank(size, unique_sizes):
    sorted_sizes = sorted(unique_sizes, reverse=True)
    try:
        index = sorted_sizes.index(size)
        return f"H{index + 1}"
    except ValueError:
        return "H4"

def group_letters_into_words(words, max_gap):
    if not words:
        return []
    words_sorted = sorted(words, key=lambda w: w["x0"])
    grouped, curr_word = [], [words_sorted[0]]
    for w in words_sorted[1:]:
        last = curr_word[-1]
        space = w["x0"] - last["x1"]
        if (space < 0.5 * last["size"]):
            grouped.append({
                "text": " ".join(c["text"] for c in curr_word),
                "fontname": curr_word[0]["fontname"],
                "size": curr_word[0]["size"],
                "x0": curr_word[0]["x0"],
                "x1": curr_word[-1]["x1"]
            })
            curr_word = [w]
        elif (space < max_gap and w["fontname"] == last["fontname"] and abs(w["size"] - last["size"]) < 0.5):
            curr_word.append(w)
        else:
            grouped.append({
                "text": " ".join(c["text"] for c in curr_word),
                "fontname": curr_word[0]["fontname"],
                "size": curr_word[0]["size"],
                "x0": curr_word[0]["x0"],
                "x1": curr_word[-1]["x1"]
            })
            curr_word = [w]
    grouped.append({
        "text": " ".join(c["text"] for c in curr_word),
        "fontname": curr_word[0]["fontname"],
        "size": curr_word[0]["size"],
        "x0": curr_word[0]["x0"],
        "x1": curr_word[-1]["x1"]
    })
    return grouped

def merge_heading_lines(processed_lines, size_mean):
    y_threshold = size_mean * 4
    merged, buffer = [], []
    last_y = last_font = last_size = None
    for y, words in processed_lines:
        if not words:
            continue
        fn = words[0]["fontname"]
        sz = words[0]["size"]
        line_txt = clean_text(" ".join(w["text"] for w in words))
        if not line_txt or re.fullmatch(r"[.\- ]{3,}", line_txt):
            continue
        if buffer and abs(y - last_y) <= y_threshold and fn == last_font and abs(sz - last_size) < 0.5:
            buffer.append((line_txt, fn, sz, y))
        else:
            if buffer:
                merged.append((" ".join(b[0] for b in buffer), buffer[0][1], buffer[0][2], buffer[0][3]))
            buffer = [(line_txt, fn, sz, y)]
        last_y, last_font, last_size = y, fn, sz
    if buffer:
        merged.append((" ".join(b[0] for b in buffer), buffer[0][1], buffer[0][2], buffer[0][3]))
    return merged

def extract_headings(pdf_path, threshold_factor=1.0, title_pages=2, top_margin=0.10, bottom_margin=0.95):
    output = {"title": "", "outline": []}
    largest_area = 0
    largest_text = ""

    try:
        with contextlib.redirect_stderr(open(os.devnull, 'w')):
            with pdfplumber.open(pdf_path) as pdf:
                lang = "en"
                for page in pdf.pages:
                    try:
                        words = page.extract_words()
                        if words:
                            lang = detect(words[0]['text'])
                            break
                    except:
                        continue

                all_sizes = []
                for page in pdf.pages:
                    words = page.extract_words(extra_attrs=["fontname", "size"])
                    all_sizes.extend([w['size'] for w in words])
                size_stats = {
                    'mean': mean(all_sizes),
                    'stdev': stdev(all_sizes) if len(all_sizes) > 1 else 0
                }
                unique_sizes = set(all_sizes)

                for page_num, page in enumerate(pdf.pages, 1):
                    ph, pw = page.height, page.width
                    words = page.extract_words(extra_attrs=["fontname", "size", "top", "x0", "x1"])
                    table_bboxes = get_table_bbox(page)
                    if not words:
                        continue
                    avg_size = mean(w['size'] for w in words)
                    max_gap = avg_size * 0.6

                    lines = defaultdict(list)
                    for w in words:
                        lines[round(w["top"], 1)].append(w)
                    processed = [(y, group_letters_into_words(ws, max_gap)) for y, ws in sorted(lines.items())]
                    merged = merge_heading_lines(processed, avg_size)

                    for txt, fn, sz, y in merged:
                        cleaned = clean_text(txt)
                        if not cleaned:
                            continue
                        for yline, line_words in processed:
                            joined = clean_text(" ".join(w["text"] for w in line_words))
                            if joined == cleaned:
                                x0 = min(w["x0"] for w in line_words)
                                x1 = max(w["x1"] for w in line_words)
                                break
                        else:
                            x0 = 0
                            x1 = 0

                        if is_inside_table(y, x0, x1, table_bboxes):
                            continue
                        if re.match(r"^\d{1,2}$", cleaned):
                            continue
                        if SERIAL_LINE_PATTERN.match(cleaned):
                            continue
                        if re.match(r"^(\d{1,2}(?:\.|\)|-))+\s*$", cleaned):
                            continue
                        if sum(1 for token in cleaned.split() if token.strip('.').isdigit()) >= 3:
                            continue
                        if is_heading_dynamic(txt, fn, sz, size_stats, y, ph, lang, threshold_factor, top_margin, bottom_margin):
                            output["outline"].append({
                                "level": get_level_by_rank(sz, unique_sizes),
                                "text": reverse_if_rtl(txt, lang),
                                "page": page_num
                            })
                        area = sz * pw
                        if page_num <= title_pages and not re.search(r"\d", txt):
                            if area > largest_area:
                                largest_area = area
                                largest_text = txt

        output["title"] = reverse_if_rtl(largest_text.strip(), lang)
    except Exception as e:
        print(f"[ERROR] Failed to process {pdf_path}: {e}")
    return output

def main():
    parser = argparse.ArgumentParser(description="PDF Heading Extractor (Dynamic)")
    parser.add_argument("--input", required=True, help="Input PDF folder")
    parser.add_argument("--output", required=True, help="Output JSON folder")
    parser.add_argument("--threshold", type=float, default=1.0, help="Outlier threshold multiplier for heading detection")
    parser.add_argument("--title_pages", type=int, default=2, help="Number of pages to search for title")
    parser.add_argument("--top_margin", type=float, default=0.10, help="Top Y-margin ratio to exclude headings")
    parser.add_argument("--bottom_margin", type=float, default=0.95, help="Bottom Y-margin ratio to exclude headings")
    args = parser.parse_args()

    input_dir = args.input
    output_dir = args.output
    os.makedirs(output_dir, exist_ok=True)
    pdf_paths = glob.glob(os.path.join(input_dir, "*.pdf"))

    start = time.time()
    with ThreadPoolExecutor() as executor:
        results = list(executor.map(lambda p: extract_headings(p, args.threshold, args.title_pages, args.top_margin, args.bottom_margin), pdf_paths))

    for pdf_path, out in zip(pdf_paths, results):
        fname = os.path.splitext(os.path.basename(pdf_path))[0] + ".json"
        json_path = os.path.join(output_dir, fname)
        if out["outline"]:
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(out, f, indent=4, ensure_ascii=False)
            print(f"[SAVED] {fname}")
        else:
            print(f"[SKIPPED] {fname} — no headings found")

    print(f"\n Completed in {time.time() - start:.2f} seconds")

if _name_ == "_main_":
    main()

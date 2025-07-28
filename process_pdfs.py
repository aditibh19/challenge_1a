import os 
import sys
import json
import re
import glob
import time
import contextlib
from statistics import mean
from collections import defaultdict, Counter
from langdetect import detect
from concurrent.futures import ThreadPoolExecutor
import pdfplumber

REPEATED_CHARS_REGEX = re.compile(r"(.)\1{2,}", re.IGNORECASE)
HEADING_DIGIT_ONLY_RE = re.compile(r"^\s*(\d+[.)-]?\s*)+$")

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
    tables = page.find_tables()
    return [table.bbox for table in tables if table.bbox]

def is_inside_table(y, x0, x1, table_bboxes):
    overlap_margin = 3
    return any(
        y0t <= y <= y1t and not (x1 < x0t - overlap_margin or x0 > x1t + overlap_margin)
        for x0t, y0t, x1t, y1t in table_bboxes
    )

def is_heading_fixed(text, fontname, size, avg_size, y_pos, page_height, page_number, width=None, page_width=None, height=None, lang="en"):
    ts = text.strip()

    if y_pos < page_height * 0.10 or y_pos > page_height * 0.95:
        return False

    if lang == "en":
        if (not ts or len(ts) < 3 or re.fullmatch(r"\W+", ts) or ts.isdigit() or
            re.fullmatch(r"\d{4}", ts) or
            re.search(r"\d{1,2} (January|February|March|April|May|June|July|August|September|October|November|December)", ts) or
            (len(ts.split()) <= 1 and ts[0].islower()) or
            re.search(r"(?i)(https?://\S+|www\.\S+|\S+\.com\b)", ts) or
            HEADING_DIGIT_ONLY_RE.match(ts)):
            return False
    else:
        if len(ts) > 200 or len(ts) < 2:
            return False

    is_bold = 'bold' in fontname.lower() or 'black' in fontname.lower()
    is_large = size >= avg_size * 1.2

    return is_bold or is_large

def get_level(size, avg_size):
    r = size / avg_size
    if r > 1.8:
        return "H1"
    if r > 1.5:
        return "H2"
    if r > 1.2:
        return "H3"
    return "H4"

def group_letters_into_words(words, max_gap):
    if not words:
        return []
    words_sorted = sorted(words, key=lambda w: w["x0"])
    grouped = []
    curr_word = [words_sorted[0]]
    for w in words_sorted[1:]:
        last = curr_word[-1]
        if (w["x0"] - last["x1"]) < max_gap and w["fontname"] == last["fontname"] and abs(w["size"] - last["size"]) < 0.5:
            curr_word.append(w)
        else:
            grouped.append({
                "text": "".join(c["text"] for c in curr_word),
                "fontname": curr_word[0]["fontname"],
                "size": curr_word[0]["size"]
            })
            curr_word = [w]
    grouped.append({
        "text": "".join(c["text"] for c in curr_word),
        "fontname": curr_word[0]["fontname"],
        "size": curr_word[0]["size"]
    })
    return grouped

def merge_heading_lines(processed_lines, avg_size, y_threshold=None):
    if y_threshold is None:
        y_threshold = avg_size * 4
    merged = []
    buffer = []
    last_y = last_font = last_size = None
    for y, words in processed_lines:
        if not words:
            continue
        fn = words[0]["fontname"]
        sz = words[0]["size"]
        line_txt = clean_text(" ".join(w["text"] for w in words))
        if not line_txt or re.fullmatch(r"[.\- ]{3,}", line_txt) or re.search(r"\.{3,}\s*\d+$", line_txt):
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

def extract_headings(pdf_path):
    output = {"title": "", "outline": []}
    largest_area = 0
    largest_text = ""
    largest_size = 0

    with contextlib.redirect_stderr(open(os.devnull, 'w')):
        with pdfplumber.open(pdf_path) as pdf:
            detected_lang = None
            for i in range(min(3, len(pdf.pages))):
                words = pdf.pages[i].extract_words()
                if words:
                    try:
                        detected_lang = detect(words[0]['text'])
                        break
                    except:
                        pass
            lang = detected_lang or "en"

            footer_lines = Counter()
            for page in pdf.pages:
                bottom_texts = [
                    clean_text(w['text']) for w in page.extract_words()
                    if w['top'] > page.height * 0.9
                ]
                for line in bottom_texts:
                    normalized = re.sub(r"\s+", " ", line.strip())
                    footer_lines[normalized] += 1

            footer_candidates = {line for line, count in footer_lines.items() if count >= len(pdf.pages) * 0.7}

            for i, page in enumerate(pdf.pages):
                page_num = i + 1
                allow_title_update = page_num <= 2
                ph, pw = page.height, page.width
                words = page.extract_words(extra_attrs=["fontname", "size", "top", "x0", "x1", "bottom"])
                if not words:
                    continue

                table_bboxes = get_table_bbox(page)
                avg_size = mean(w["size"] for w in words)
                max_gap = avg_size * 0.6

                lines = defaultdict(list)
                for w in words:
                    y = round(w["top"], 1)
                    lines[y].append(w)

                processed = [(y, group_letters_into_words(ws, max_gap)) for y, ws in sorted(lines.items())]
                merged = merge_heading_lines(processed, avg_size)

                for txt, fn, sz, y in merged:
                    cleaned = clean_text(txt)
                    normalized = re.sub(r"\s+", " ", cleaned).strip()
                    if normalized in footer_candidates:
                        continue
                    if REPEATED_CHARS_REGEX.search(txt.replace(" ", "")):
                        continue
                    if len(txt) > 200 or (len(txt) > 80 and txt.count(" ") < 3):
                        continue
                    if ' ' not in txt and re.search(r"[a-z][A-Z]", txt):
                        continue
                    if re.fullmatch(r"[A-Za-z,\-]{80,}", txt):
                        continue
                    if re.fullmatch(r"^\s*[\d]+([.)-])?\s*$", cleaned):
                        continue
                    if re.match(r"^\s*\d+([.)-])?\s+\d{1,2}\s*$", cleaned):
                        continue
                    parts = cleaned.strip().split()
                    if len(parts) <= 2 and parts and re.fullmatch(r"\d+([.)-])?", parts[0]):
                        continue
                    if re.search(r"S\.?No\b", cleaned, re.IGNORECASE) and sum(1 for part in cleaned.split() if part.strip('.').isdigit()) >= 3:
                        continue
                    if sum(1 for w in cleaned.strip().split() if re.fullmatch(r"\d+[.)]?", w)) >= 3:
                        continue

                    x0 = min(w["x0"] for w in words if w["text"] in txt)
                    x1 = max(w["x1"] for w in words if w["text"] in txt)
                    if is_inside_table(y, x0, x1, table_bboxes):
                        continue

                    width = pw
                    area = sz * width

                    if allow_title_update and not re.search(r"\d", txt):
                        if area > largest_area or (area == largest_area and sz > largest_size):
                            largest_area = area
                            largest_text = txt
                            largest_size = sz

                    if is_heading_fixed(txt, fn, sz, avg_size, y, ph, page_num, width, pw, lang=lang):
                        output["outline"].append({
                            "level": get_level(sz, avg_size),
                            "text": reverse_if_rtl(txt, lang),
                            "page": page_num
                        })

    output["title"] = reverse_if_rtl(largest_text.strip(), lang)
    return output

if __name__ == "__main__":
    start = time.time()
    input_dir = os.path.join("sample_dataset", "pdfs")
    output_dir = os.path.join("sample_dataset", "outputs")
    os.makedirs(output_dir, exist_ok=True)

    pdf_paths = glob.glob(os.path.join(input_dir, "*.pdf"))
    with ThreadPoolExecutor() as executor:
        results = list(executor.map(extract_headings, pdf_paths))

    for pdf_path, out in zip(pdf_paths, results):
        fname = os.path.splitext(os.path.basename(pdf_path))[0] + ".json"
        json_path = os.path.join(output_dir, fname)
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=4, ensure_ascii=False)
        print(f"{fname} saved.")

    print(f" Completed in {time.time() - start:.2f} seconds")

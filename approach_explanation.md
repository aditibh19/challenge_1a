
# Approach Overview

This module focuses on extracting **hierarchical headings (Title, H1–H4)** from a given PDF document using layout, font, and textual cues — without any machine learning or external API dependencies.

## Section Extraction Logic

Each PDF is parsed using **pdfplumber** for fine-grained, layout-aware word extraction. The document is then analyzed line-by-line and grouped vertically using `y`-coordinates and visual proximity. We apply a multi-step strategy:

* **Word grouping**: Characters are grouped into words by analyzing inter-character horizontal gaps, font similarity, and size consistency.
* **Line reconstruction**: Words on the same horizontal plane are grouped into lines using their `top` position and font features.
* **Heading merging**: Consecutive lines with similar font and size are merged into multi-line headings if their vertical spacing is minimal.
* **Fallbacks**: Repetitive filler content (e.g., dotted lines or footers) is ignored. Headings that are too small or appear in margins are filtered out.

## Heuristic-Based Heading Detection

To determine whether a merged line is a heading, we apply several filters:

* **Font size**: Must be larger than the average text height on the page (≥ 1.2×).
* **Font weight**: Font must contain "bold" or "black" (case-insensitive).
* **Vertical position**: Top 10% and bottom 5% of the page are excluded to avoid headers/footers.
* **Length and structure**: Headings must contain more than 2 characters and avoid overly long strings, excessive punctuation, or digit-heavy content.
* **Regex filters** (especially for English):

  * Rejects years (e.g., "2022"), dates (e.g., "12 January"), single lowercase words, and common footer patterns.
  * Filters out strings like URLs, "RFP:", and text resembling form fields.

## Title Detection

The title is inferred from the **first two pages only**, using the following criteria:

* Chosen as the string with the **largest area**, computed as `font_size × page_width`.
* Must be free from digits (e.g., not a serial number or table row).
* Preference is given to horizontally centered text (by using the full page width in area computation).

## Multilingual and RTL Handling

* Language is detected using the `langdetect` library, using content from the first few pages.
* **For RTL scripts** (Arabic, Hebrew, Urdu, Persian), heading text is **reversed** using `reverse_if_rtl()` to display naturally.
* For **non-English documents**, rules are relaxed:

  * Less aggressive rejection of short headings or digit content.
  * Allows headings that would be rejected in English due to formatting assumptions.

## Table and Form Filtering

* Although table detection isn't fully integrated via bounding boxes, your code includes logic to exclude text lines that:

  * Have a high count of digits.
  * Match form field keywords (e.g., "Name", "Date", "Remarks").
  * Have repetitive or fixed layout structure typical of tabular forms.
* Headings within structured forms or alignment patterns are excluded by combining size, alignment, and regex heuristics.

## Heading Level Assignment

Each valid heading is assigned a hierarchical level (`H1` to `H4`) based on its font size relative to the average on that page:

* `H1`: ≥ 1.8× avg
* `H2`: ≥ 1.5× avg
* `H3`: ≥ 1.2× avg
* `H4`: anything above body text threshold

## Output Format

Each processed PDF produces a JSON output containing:

* `title`: Cleaned, inferred document title (largest prominent text without digits)
* `outline`: List of heading entries with:

  * `level`: Heading level (H1–H4)
  * `text`: Cleaned heading text (with RTL correction if needed)
  * `page`: Page number where heading appears

## Performance & Constraints Compliance

* Fully **rule-based**, runs entirely offline.
* Uses **ThreadPoolExecutor** for parallel processing of multiple PDFs.
* Runtime for large documents remains under the required 10-second window.
* No use of ML models, external APIs, or GPU dependencies.
* Designed for **AMD64 CPU architecture**.

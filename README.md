# Adobe India Hackathon - Round 1 Solution
**"Connecting the Dots" Challenge - Complete Round 1 Solution**

## PDF Heading Extractor — Challenge-1A

This repository provides a lightweight, layout-aware utility to extract **titles and section headings from PDFs** using only visual cues like font size, weight, and positioning — optimized for local, CPU-only environments.

The tool is built to support **offline, dockerized batch processing of PDFs**, and outputs a structured JSON outline per file.

---

## Approach Overview

### Heading Extraction

- Uses **pdfplumber** to extract words and layout metadata from each page.
- Dynamically detects document language (English, Arabic, Japanese, etc.).
- Reverses RTL (right-to-left) text such as Arabic or Hebrew when necessary.
- Groups characters into lines and merges lines into blocks using:
  - Font size  
  - Font weight (bold/black)  
  - Vertical spacing
- Applies heuristics to ignore:
  - Common form fields (e.g. “Date”, “Signature”, “Goals”)  
  - Footers, page numbers, repetitive junk, etc.  
  - Links and repetitive characters
- Detects headings by comparing size/weight to page average.  
- Assigns levels `H1`–`H4` based on relative font size.

### Title Detection

- The largest visual block based on `font_size × text_width` in the first two pages is marked as the document **title**.
- RTL titles are automatically reversed based on language.
- Digit or junk-only lines are ignored.
- No hardcoded rules or filename-based overrides are used.

---

## Features

| Capability                       | Status |
| -------------------------------- | ------ |
| Offline processing (no internet) | Yes    |
| Handles noisy layouts            | Yes    |
| Auto title detection             | Yes    |
| Filters footers and form fields  | Yes    |
| Outputs per-document JSON        | Yes    |
| Multilingual + RTL support       | Yes    |
| Docker-ready                     | Yes    |
| Threaded execution               | Yes    |

---

## Tech Stack

- Python 3.10  
- pdfplumber for PDF parsing  
- langdetect for language detection  
- Docker (optional for portability)  
- Input: `*.pdf` in `input/` folder  
- Output: `*.json` with structured outline in `output/`

---

## How to Run

### Step 1: Build the Docker Image

```bash
docker build -t adobe1a .
````

### Step 2: Run on All PDFs

```bash
docker run --rm -v "$PWD/sample_dataset:/app/sample_dataset" adobe1a 2>$null
```

This command:

* Reads all `*.pdf` files in `input/`
* Produces a corresponding `*.json` file in `output/`

---

## Project Structure

```
 pdf_outline_extractor/
├── input/
├── output/
├── main.py              # Main heading extractor
├── requirements.txt     # pip dependencies
├── Dockerfile
├── .dockerignore
└── README.md
```

---

## Sample Output Format

```json
{
  "title": "Digital Learning Strategy",
  "outline": [
    {
      "level": "H1",
      "text": "Executive Summary",
      "page": 1
    },
    {
      "level": "H2",
      "text": "Implementation Plan",
      "page": 3
    }
  ]
}
```

---

## Credits

**Team:** C0d3Hers

**Developed by:** Aditi Bhalla and Kashvi Rathore

**GitHub:** [https://github.com/aditibh19/challenge\_1a](https://github.com/aditibh19/challenge_1a)

```

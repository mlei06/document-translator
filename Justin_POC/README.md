# PPT Translator

A set of Python scripts for translating text inside PowerPoint (`.pptx`) presentations. Three scripts are provided:

- **`pyTranslator.py`** — Translates using a **local HuggingFace M2M100 / SMALL-100 model** loaded from disk. No network or external API required at runtime.
- **`PyTranslatorOllama.py`** — Translates using a **local Ollama API** (e.g., Gemma) running on `localhost:11434`.
- **`pyTestTranslator.py`** — A standalone test script that loads the local SMALL-100 model and translates a single hardcoded string. Useful for verifying that the model and tokenizer are correctly set up before running the full presentation translator.

Both `pyTranslator.py` and `pyTestTranslator.py` depend on `tokenization_small100.py`, a custom tokenizer module that must be present in the project root.

---

## Directory Structure

```
PPT_Translator/
├── pyTranslator.py          # Local HuggingFace model translator (PowerPoint)
├── pyTestTranslator.py      # Standalone test script for the local model
├── PyTranslatorOllama.py    # Ollama API translator (PowerPoint)
├── tokenization_small100.py # Custom SMALL-100 tokenizer (required by pyTranslator.py and pyTestTranslator.py)
├── README.md                # This file
└── small100/                # Local model files (config, weights, tokenizer data)
```

---

## Prerequisites

- **Python 3.8+** (tested on Python 3.12)
- **pip** (Python package installer)
- **Windows, macOS, or Linux** (paths in the scripts are resolved relative to the script's location, so they work on any OS)

---

## Installation of Dependencies

### For `pyTranslator.py` (HuggingFace local model)

```bash
pip install python-pptx transformers torch
```

> **Note:** The `transformers` library is used for the M2M100 model architecture. The `tokenization_small100.py` file in the project root provides the custom SMALL-100 tokenizer and must be present alongside the scripts. The model files must be downloaded separately and placed in the `small100/` subdirectory (see [Model Setup](#model-setup-for-pytranslatorpy) below).

### For `PyTranslatorOllama.py` (Ollama API)

```bash
pip install python-pptx requests
```

> **Note:** This script does **not** require `transformers` or `torch`. It communicates with a running Ollama server via HTTP.

---

## Model Setup for `pyTranslator.py` and `pyTestTranslator.py`

Both scripts load a SMALL-100 model from the `small100/` subdirectory. You must download the model files beforehand:

1. Download the SMALL-100 model from HuggingFace:
   ```bash
   git lfs install
   git clone https://huggingface.co/alirezamika/small-100
   ```
2. Copy the model files (`config.json`, `model.safetensors`, `pytorch_model.bin`, `sentencepiece.bpe.model`, `special_tokens_map.json`, `tokenizer_config.json`, `vocab.json`) into the `small100/` subdirectory of this project.
3. The `MODEL_DIR` variable in both scripts is set automatically to the `small100/` subdirectory relative to the script's location — no manual path configuration needed.
4. Adjust `SOURCE_LANGUAGE` and `TARGET_LANGUAGE` as needed (e.g., `"zh"` for Chinese, `"en"` for English).

---

## How to Run

### `pyTranslator.py` — Local HuggingFace Model

Translates a PowerPoint presentation using a locally loaded M2M100/SMALL-100 model.

```bash
python pyTranslator.py input.pptx output.pptx
```

**Example:**

```bash
python pyTranslator.py presentation_chinese.pptx presentation_english.pptx
```

**Arguments:**

| Argument  | Description                          |
|-----------|--------------------------------------|
| `input`   | Path to the input `.pptx` file       |
| `output`  | Path for the translated `.pptx` file |

**Optional flags:**

| Flag | Description |
|------|-------------|
| `-v`, `--verbose` | Enable detailed per-text translation output (prints every source/target pair) |
| `-b`, `--batch-size` | Batch size for model inference (default: 128). Larger values reduce per-call overhead but use more memory. |
| `-p`, `--profile` | Enable timing/profiling output for each phase (collection, translation, mapping, saving) |

**What it does:**
- Loads the SMALL-100 tokenizer and model from `MODEL_DIR` at startup.
- **Phase 1 (Collection):** Iterates over every slide, collecting all text runs from text boxes, placeholders, tables, and grouped shapes.
- **Phase 2 (Translation):** Batch translates all collected texts in large batches (default 128 per batch) using a translation cache to skip duplicate strings.
- **Phase 3 (Mapping):** Maps translated texts back to the original run objects, preserving per-run formatting (colors, fonts, etc.).
- Saves the translated presentation to the output path.

**Performance:**
- The two-phase collect-then-translate approach minimizes model inference calls by batching all texts together, rather than translating per-text-frame.
- A translation cache deduplicates identical strings across the presentation, avoiding redundant model calls.
- On CPU, PyTorch thread count is automatically set to the number of available CPU cores.
- Use `--profile` to see timing breakdown per phase.

---

### `pyTestTranslator.py` — Local Model Test

A standalone test script that loads the SMALL-100 model and tokenizer from the `small100/` directory and translates a single hardcoded string. This is useful for verifying that the model files and tokenizer are correctly set up before running the full presentation translator.

```bash
python pyTestTranslator.py
```

**What it does:**
- Loads the SMALL-100 tokenizer and model from the `small100/` subdirectory.
- Translates a hardcoded English string to Spanish (configurable via `SOURCE_LANGUAGE` and `TARGET_LANGUAGE` variables).
- Prints the original and translated text to the console.

**Configuration variables (edit at the top of the script):**

| Variable           | Default | Description                          |
|--------------------|---------|--------------------------------------|
| `MODEL_DIR`        | `small100/` (relative to script) | Path to the local model folder |
| `SOURCE_LANGUAGE`  | `"en"`  | Source language code                 |
| `TARGET_LANGUAGE`  | `"es"`  | Target language code                 |

---

### `PyTranslatorOllama.py` — Ollama API

Translates a PowerPoint presentation by sending text to a local Ollama server.

**Before running:**

1. Install and start [Ollama](https://ollama.com/download).
2. Pull the model referenced in the script (default: `gemma4:e2b`):
   ```bash
   ollama pull gemma4:e2b
   ```
3. Ensure the Ollama server is running (it starts automatically with the Ollama app).

```bash
python PyTranslatorOllama.py input.pptx output.pptx
```

**Example:**

```bash
python PyTranslatorOllama.py presentation_english.pptx presentation_spanish.pptx
```

**Arguments:**

| Argument  | Description                          |
|-----------|--------------------------------------|
| `input`   | Path to the input `.pptx` file       |
| `output`  | Path for the translated `.pptx` file |

**What it does:**
- Sends each text frame's content to the Ollama API at `http://localhost:11434/api/generate`.
- Uses a structured prompt to translate English to Spanish (modify the `prompt` in `translate_text()` to change languages).
- Translates text frame-by-frame and table cell-by-cell.
- Saves the translated presentation to the output path.

**Configuration variables (edit at the top of the script):**

| Variable     | Default                          | Description                          |
|--------------|----------------------------------|--------------------------------------|
| `OLLAMA_URL` | `http://localhost:11434/api/generate` | Ollama API endpoint               |
| `MODEL`      | `gemma4:e2b`                     | Ollama model name to use             |

---

## Notes on the Translation Approaches

### Local HuggingFace Model (`pyTranslator.py`)

| Aspect              | Details                                                                 |
|---------------------|-------------------------------------------------------------------------|
| **Dependencies**    | `python-pptx`, `transformers`, `torch`                                  |
| **Model**           | SMALL-100 (M2M100 architecture), loaded from a local directory           |
| **Network required**| No — once the model is downloaded, everything runs offline               |
| **Speed**           | Fast per-call (no network latency); global batching and caching minimize inference calls |
| **Quality**         | Good for common language pairs; limited by the SMALL-100 model capacity  |
| **Formatting**      | Translates run-by-run, preserving individual text run formatting       |
| **Languages**       | Configurable via `SOURCE_LANGUAGE` and `TARGET_LANGUAGE` variables       |

### Ollama API (`PyTranslatorOllama.py`)

| Aspect              | Details                                                                 |
|---------------------|-------------------------------------------------------------------------|
| **Dependencies**    | `python-pptx`, `requests`                                               |
| **Model**           | Any model served by Ollama (default: `gemma4:e2b`)                      |
| **Network required**| No external internet — communicates with local Ollama server only      |
| **Speed**           | Depends on model size and hardware; each call has HTTP overhead         |
| **Quality**         | Generally higher quality; can use larger models (Gemma, Llama, etc.)    |
| **Formatting**      | Translates text frame-by-frame; may lose per-run formatting             |
| **Languages**       | Controlled by the prompt in `translate_text()` (currently EN → ES)      |
| **Flexibility**     | Easy to switch models or change the prompt for different language pairs |

### Choosing Between Them

- Use **`pyTranslator.py`** when you need **offline operation** with **no external services** and want to **preserve per-run text formatting**.
- Use **`PyTranslatorOllama.py`** when you want **higher translation quality** and are willing to run a local Ollama server. This approach is more flexible for changing language pairs and models.

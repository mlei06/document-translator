#!/usr/bin/env python3

import argparse
import os
import time

import torch

from docx import Document
from pptx import Presentation

from transformers import M2M100ForConditionalGeneration
from tokenization_small100 import SMALL100Tokenizer

# Define configuration
# Resolve the model directory relative to this script's location so the
# script works regardless of the current working directory.
MODEL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "small100")  # Path to local model folder
SOURCE_LANGUAGE = "zh"               # Source language code
TARGET_LANGUAGE = "en"               # Target language code

# Default batch size for model inference; larger batches reduce per-call overhead
DEFAULT_BATCH_SIZE = 128

# Translation cache: maps source text -> translated text to avoid redundant
# model calls for identical strings across the presentation
_translation_cache: dict[str, str] = {}

# Verbose flag: when True, prints every source/target pair; when False,
# only prints progress per slide
_verbose: bool = False

# Profile flag: when True, prints timing for each phase
_profile: bool = False


def _time_phase(label: str, start: float) -> float:
    """Print elapsed time for a phase if profiling is enabled. Returns current time."""
    if _profile:
        elapsed = time.time() - start
        print(f"  [TIMING] {label}: {elapsed:.2f}s")
    return time.time()


print("Loading model and tokenizer from local folder...")
# Load tokenizer and model from local path
tokenizer = SMALL100Tokenizer.from_pretrained(MODEL_DIR)
model = M2M100ForConditionalGeneration.from_pretrained(MODEL_DIR)

# Device detection and model placement
device = "cuda" if torch.cuda.is_available() else "cpu"
model.to(device)
print(f"Using device: {device}")

# Optimize CPU thread usage for inference
if device == "cpu":
    num_threads = os.cpu_count() or 1
    torch.set_num_threads(num_threads)
    print(f"CPU threads: {num_threads}")

# Configure source and target languages
tokenizer.src_lang = SOURCE_LANGUAGE
tokenizer.tgt_lang = TARGET_LANGUAGE

print(f"Translating from '{SOURCE_LANGUAGE}' to '{TARGET_LANGUAGE}'...")


def translate_texts(texts: list[str]) -> list[str]:
    """
    Translate a batch of texts from SOURCE_LANG to TARGET_LANG using a local M2M100/SMALL-100 model.
    Returns list of translated texts in same order as input.

    Uses a translation cache to skip texts that have already been translated,
    reducing redundant model calls for repeated strings.
    """
    if not texts:
        return []

    original_texts = texts
    texts = [t.strip() for t in texts]

    # Check cache for each text; collect only uncached texts for translation
    results = list(original_texts)
    uncached_indices = []
    uncached_texts = []
    for i, t in enumerate(texts):
        if t and t in _translation_cache:
            results[i] = _translation_cache[t]
        elif t:
            uncached_indices.append(i)
            uncached_texts.append(t)

    if not uncached_texts:
        return results

    try:
        # Batch tokenize with padding and truncation
        encoded_inputs = tokenizer.batch_encode_plus(
            uncached_texts,
            return_tensors="pt",
            padding=True,
            truncation=True,
            max_length=512
        )

        # Move to device
        encoded_inputs = {k: v.to(device) for k, v in encoded_inputs.items()}

        # Generate translations with optimized settings
        with torch.inference_mode():
            generated_tokens = model.generate(
                **encoded_inputs,
                use_cache=True,
                num_beams=1,
                do_sample=False,
                max_new_tokens=100
            )

        # Decode tokens back into readable strings
        translated_texts = tokenizer.batch_decode(generated_tokens, skip_special_tokens=True)

        # Map translations back to original positions and populate cache
        for idx, translated in zip(uncached_indices, translated_texts):
            results[idx] = translated
            _translation_cache[texts[idx]] = translated

        # Batch progress logging (safe for Windows console)
        if _verbose:
            print("-" * 60)
            for src, tgt in zip(uncached_texts, translated_texts):
                # Encode to ASCII with replacement for console safety
                src_safe = src.encode('ascii', 'replace').decode('ascii')
                tgt_safe = tgt.encode('ascii', 'replace').decode('ascii')
                print(f"SRC: {src_safe}")
                print(f"TGT: {tgt_safe}")

        return results

    except Exception as ex:
        print(f"Batch translation failed: {ex}")
        return original_texts


def collect_runs_from_text_frame(text_frame) -> list:
    """
    Collect all runs with non-empty text from a text frame.
    Returns list of run objects.
    """
    runs = []
    for paragraph in text_frame.paragraphs:
        for run in paragraph.runs:
            if run.text.strip():
                runs.append(run)
    return runs


def collect_runs_from_shape(shape) -> list:
    """
    Recursively collect all translatable runs from a shape (text box,
    placeholder, table cell, or group shape).
    Returns list of run objects.
    """
    runs = []

    # Text boxes and placeholders
    if hasattr(shape, "text_frame") and shape.has_text_frame:
        runs.extend(collect_runs_from_text_frame(shape.text_frame))

    # Tables
    if getattr(shape, "has_table", False):
        table = shape.table
        for row in table.rows:
            for cell in row.cells:
                if cell.text_frame:
                    runs.extend(collect_runs_from_text_frame(cell.text_frame))

    # Grouped shapes
    if shape.shape_type == 6:  # MSO_SHAPE_TYPE.GROUP
        for subshape in shape.shapes:
            runs.extend(collect_runs_from_shape(subshape))

    return runs


def collect_runs_from_presentation(prs) -> list:
    """
    Collect all translatable runs from all slides in the presentation.
    Returns list of run objects in slide order.
    """
    all_runs = []
    for slide in prs.slides:
        for shape in slide.shapes:
            all_runs.extend(collect_runs_from_shape(shape))
    return all_runs


def translate_presentation(input_file, output_file, batch_size: int = DEFAULT_BATCH_SIZE):
    """
    Load a PPTX presentation, collect all translatable text runs across all
    slides, batch translate them in large batches, and save the translated
    presentation.

    This two-phase approach (collect-then-translate) minimizes the number of
    model inference calls by batching all unique texts together, rather than
    translating per-text-frame as in the original implementation.
    """
    t_start = time.time()

    prs = Presentation(input_file)
    slide_count = len(prs.slides)
    print(f"Loaded presentation: {slide_count} slides")

    # Phase 1: Collect all runs across all slides
    t_collect = time.time()
    all_runs = collect_runs_from_presentation(prs)
    print(f"Collected {len(all_runs)} text runs across {slide_count} slides")
    t_start = _time_phase("Text collection", t_collect)

    if not all_runs:
        print("No text runs found to translate.")
        prs.save(output_file)
        print(f"Saved: {output_file}")
        return

    # Phase 2: Extract texts and batch translate
    # Extract all texts preserving original whitespace
    texts = [run.text for run in all_runs]

    # Translate in large batches to minimize per-call overhead
    t_translate = time.time()
    all_translations = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        batch_translations = translate_texts(batch)
        all_translations.extend(batch_translations)
    t_start = _time_phase("Translation", t_translate)

    # Phase 3: Map translations back to runs
    t_map = time.time()
    for run, translated in zip(all_runs, all_translations):
        run.text = translated
    t_start = _time_phase("Mapping results", t_map)

    # Phase 4: Save
    t_save = time.time()
    prs.save(output_file)
    t_start = _time_phase("Saving presentation", t_save)

    total_time = time.time() - t_start
    print(f"\nTranslation complete in {total_time:.2f}s.")
    print(f"Cache hits: {len(_translation_cache)} unique translations cached")
    print(f"Saved: {output_file}")


def process_shape(shape):
    """
    Process textbox, table, placeholder, and group shapes while preserving formatting.
    """
    # Text boxes and placeholders
    if hasattr(shape, "text_frame") and shape.has_text_frame:
        process_text_frame(shape.text_frame)

    # Tables
    if getattr(shape, "has_table", False):
        table = shape.table
        for row in table.rows:
            for cell in row.cells:
                if cell.text_frame:
                    process_text_frame(cell.text_frame)

    # Grouped shapes
    if shape.shape_type == 6:  # MSO_SHAPE_TYPE.GROUP
        for subshape in shape.shapes:
            process_shape(subshape)


def process_text_frame(text_frame):
    """
    Translates text inside a text frame run-by-run to keep colors and formatting.
    Collects all runs first, batch translates, then maps results back.
    """
    # Collect all runs with text
    runs_to_translate = []
    for paragraph in text_frame.paragraphs:
        for run in paragraph.runs:
            if run.text.strip():
                runs_to_translate.append(run)

    if not runs_to_translate:
        return

    # Extract texts preserving original whitespace
    texts = [run.text for run in runs_to_translate]

    # Batch translate
    translations = translate_texts(texts)

    # Map translations back to runs
    for run, translated in zip(runs_to_translate, translations):
        run.text = translated


def process_paragraph(paragraph):
    """
    Translates text inside a docx paragraph run-by-run to preserve formatting.
    Collects all runs with text, batch translates, then maps results back.
    """
    # Collect all runs with text
    runs_to_translate = []
    for run in paragraph.runs:
        if run.text.strip():
            runs_to_translate.append(run)

    if not runs_to_translate:
        return

    # Extract texts preserving original whitespace
    texts = [run.text for run in runs_to_translate]

    # Batch translate
    translations = translate_texts(texts)

    # Map translations back to runs
    for run, translated in zip(runs_to_translate, translations):
        run.text = translated


def translate_document(input_file, output_file):
    """
    Load a DOCX document, translate all paragraphs and table cells,
    and save the translated document.
    """
    doc = Document(input_file)

    # Process all paragraphs in the document body
    for paragraph in doc.paragraphs:
        process_paragraph(paragraph)

    # Process all tables
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for paragraph in cell.paragraphs:
                    process_paragraph(paragraph)

    doc.save(output_file)

    print("\nTranslation complete.")
    print(f"Saved: {output_file}")


def main():
    global _verbose, _profile

    parser = argparse.ArgumentParser(
        description="Translate text in PPTX/DOCX files using a local M2M100/SMALL-100 model"
    )

    parser.add_argument(
        "input",
        help="Input file (.pptx or .docx)"
    )

    parser.add_argument(
        "output",
        help="Output translated file (.pptx or .docx)"
    )

    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable detailed per-text translation output"
    )

    parser.add_argument(
        "-b", "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=f"Batch size for model inference (default: {DEFAULT_BATCH_SIZE})"
    )

    parser.add_argument(
        "-p", "--profile",
        action="store_true",
        help="Enable timing/profiling output for each phase"
    )

    args = parser.parse_args()

    _verbose = args.verbose
    _profile = args.profile

    # Determine file type by extension
    input_ext = os.path.splitext(args.input)[1].lower()
    output_ext = os.path.splitext(args.output)[1].lower()

    if input_ext != output_ext:
        print(f"Error: Input and output file extensions must match (got {input_ext} and {output_ext})")
        return

    if input_ext == ".pptx":
        translate_presentation(args.input, args.output, batch_size=args.batch_size)
    elif input_ext == ".docx":
        translate_document(args.input, args.output)
    else:
        print(f"Error: Unsupported file extension '{input_ext}'. Supported: .pptx, .docx")
        return


if __name__ == "__main__":
    main()

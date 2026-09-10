#!/usr/bin/env python3

import argparse
import os

from pptx import Presentation

from transformers import M2M100ForConditionalGeneration
from tokenization_small100 import SMALL100Tokenizer

# Define configuration
# Resolve the model directory relative to this script's location so the
# script works regardless of the current working directory.
MODEL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "small100")  # Path to local model folder
SOURCE_LANGUAGE = "zh"               # Source language code
TARGET_LANGUAGE = "en"               # Target language code

print("Loading model and tokenizer from local folder...")
# Load tokenizer and model from local path
tokenizer = SMALL100Tokenizer.from_pretrained(MODEL_DIR)
model = M2M100ForConditionalGeneration.from_pretrained(MODEL_DIR)

# Configure source and target languages
tokenizer.tgt_lang = TARGET_LANGUAGE

print(f"Translating from '{SOURCE_LANGUAGE}' to '{TARGET_LANGUAGE}'...")

def translate_text(text: str) -> str:
    """
    Translate text from SOURCE_LANG to TARGET_LANG using a local M2M100/SMALL-100 model.
    """

    original_text = text
    text = text.strip()

    if not text:
        return original_text

    try:
        
        # Tokenize input string
        encoded_inputs = tokenizer(text, return_tensors="pt")

        # Generate translation tokens
        generated_tokens = model.generate(**encoded_inputs)

        # Decode tokens back into a readable string
        translated_text = tokenizer.batch_decode(generated_tokens, skip_special_tokens=True)[0]

        print("-" * 60)
        print("EN:", text)
        print("ES:", translated_text)

        return translated_text

    except Exception as ex:
        print(f"Translation failed: {ex}")
        return original_text

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
    """
    for paragraph in text_frame.paragraphs:
        for run in paragraph.runs:
            if run.text.strip():
                # Translate only the text inside this specific run
                run.text = translate_text(run.text)

def translate_presentation(input_file, output_file):

    prs = Presentation(input_file)

    slide_count = len(prs.slides)

    for slide_num, slide in enumerate(prs.slides, start=1):

        print(f"\nProcessing slide {slide_num}/{slide_count}")

        for shape in slide.shapes:
            process_shape(shape)

    prs.save(output_file)

    print("\nTranslation complete.")
    print(f"Saved: {output_file}")


def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "input",
        help="Input PowerPoint (.pptx)"
    )

    parser.add_argument(
        "output",
        help="Output translated PowerPoint (.pptx)"
    )

    args = parser.parse_args()

    translate_presentation(
        args.input,
        args.output
    )

if __name__ == "__main__":
    main()
import os

from transformers import M2M100ForConditionalGeneration
from tokenization_small100 import SMALL100Tokenizer

# Define configuration
# Resolve the model directory relative to this script's location so the
# script works regardless of the current working directory.
MODEL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "small100")  # Path to local model folder
SOURCE_LANGUAGE = "en"               # Source language code
TARGET_LANGUAGE = "es"               # Target language code

# Input text to translate
text_to_translate = "Hello world! This is a test translation using the local model."

print("Loading model and tokenizer from local folder...")
# Load tokenizer and model from local path
tokenizer = SMALL100Tokenizer.from_pretrained(MODEL_DIR)
model = M2M100ForConditionalGeneration.from_pretrained(MODEL_DIR)

# Configure source and target languages
tokenizer.tgt_lang = TARGET_LANGUAGE

print(f"Translating from '{SOURCE_LANGUAGE}' to '{TARGET_LANGUAGE}'...")
# Tokenize input string
encoded_inputs = tokenizer(text_to_translate, return_tensors="pt")

# Generate translation tokens
generated_tokens = model.generate(**encoded_inputs)

# Decode tokens back into a readable string
translated_text = tokenizer.batch_decode(generated_tokens, skip_special_tokens=True)[0]

# Display results
print("\n--- Results ---")
print(f"Original Text: {text_to_translate}")
print(f"Translated Text: {translated_text}")

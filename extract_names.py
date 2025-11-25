#!/usr/bin/env python3
"""Extract card names from GPK images using OCR."""

import os
import json
try:
    import pytesseract
    from PIL import Image
except ImportError:
    print("Please install: pip3 install pytesseract Pillow")
    print("Also install tesseract: apt-get install tesseract-ocr")
    exit(1)

IMAGES_PATH = '/Users/brainphreak/garbagedex'
OUTPUT_FILE = '/Users/brainphreak/garbagedex/gpkdex/card_names.json'

def extract_name_from_image(image_path):
    """Extract the card name from the bottom of a GPK card image."""
    try:
        img = Image.open(image_path)
        width, height = img.size

        # Crop to bottom portion where name is (roughly bottom 15%)
        bottom_crop = img.crop((0, int(height * 0.85), width, height))

        # Use tesseract to extract text
        text = pytesseract.image_to_string(bottom_crop, config='--psm 7')

        # Clean up the text
        name = text.strip().replace('\n', ' ').replace('  ', ' ')

        # Remove common OCR artifacts
        name = name.replace('|', 'I').replace('0', 'O')

        return name if name else None
    except Exception as e:
        print(f"Error processing {image_path}: {e}")
        return None

def main():
    card_names = {}

    for series_num in range(1, 4):  # os1, os2, os3
        series = f"os{series_num}"
        folder = f"{series}_images"
        folder_path = os.path.join(IMAGES_PATH, folder)

        if not os.path.exists(folder_path):
            print(f"Folder not found: {folder_path}")
            continue

        print(f"\nProcessing {series}...")

        for filename in sorted(os.listdir(folder_path)):
            if not filename.endswith('.jpg'):
                continue

            # Only process 'a' variants (they have same name as 'b')
            if 'b.jpg' in filename:
                continue

            image_path = os.path.join(folder_path, filename)
            name = extract_name_from_image(image_path)

            # Extract card key (e.g., "os1_1" from "os1_1a.jpg")
            card_key = filename.replace('a.jpg', '').replace('b.jpg', '')

            if name:
                card_names[card_key] = name
                print(f"  {card_key}: {name}")
            else:
                print(f"  {card_key}: [FAILED TO EXTRACT]")

    # Save to JSON
    with open(OUTPUT_FILE, 'w') as f:
        json.dump(card_names, f, indent=2)

    print(f"\nSaved {len(card_names)} card names to {OUTPUT_FILE}")

if __name__ == '__main__':
    main()

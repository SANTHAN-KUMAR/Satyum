import sys
import os
import logging

# Add backend to path so we can import app
sys.path.insert(0, "/run/media/santhankumar/New Volume/Satyum/backend")

from app.config import settings
from forensics.extraction.factory import build_default_extractor
from forensics.extraction.interface import PageImage

logging.basicConfig(level=logging.INFO)

print(f"Configured Provider: {settings.vlm_provider}")
print(f"Configured Model: {settings.vlm_model}")

extractor = build_default_extractor(settings)

if not extractor:
    print("Extractor failed to build")
    sys.exit(1)

with open("/run/media/santhankumar/New Volume/Satyum/Real_life_docs/dad_PAN.jpeg", "rb") as f:
    img_bytes = f.read()

page = PageImage(png_bytes=img_bytes, width=1024, height=768)

print("\nSending request to local Qwen2.5-VL...")
try:
    result = extractor.extract(page, doc_type_hint="PAN_CARD")
    print("\n--- EXTRACTION SUCCESS ---")
    print(f"Model ID: {result.model_id}")
    print(f"Extraction Output:\n{result.model_dump_json(indent=2)}")
except Exception as e:
    print(f"\n--- EXTRACTION FAILED ---")
    import traceback
    traceback.print_exc()

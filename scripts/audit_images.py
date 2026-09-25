#!/usr/bin/env python3
"""
Audits image integrity and prompt heuristics for dishes.json.
"""
import argparse
import json
import os
import sys
from pathlib import Path
from PIL import Image

DATA_DIR = Path("data")

def check_image(dish_id, dish, images_dir):
    image_name = dish.get("image")
    if not image_name:
        return []
        
    errors = []
    
    # 1. Missing or corrupt image
    img_path = images_dir / image_name
    if not img_path.exists():
        errors.append(f"Image {image_name} missing")
    else:
        try:
            with Image.open(img_path) as img:
                if img.format != "WEBP":
                    errors.append(f"Image {image_name} is {img.format}, not WEBP")
                if img.size != (1024, 576):
                    errors.append(f"Image {image_name} has invalid size {img.size}, expected 1024x576")
        except Exception as e:
            errors.append(f"Image {image_name} corrupt or unreadable: {e}")
            
    # 2. VLM score check
    if dish.get("model") == "web-search":
        score = dish.get("vlm_score")
        if score is None:
            errors.append("web-search model missing vlm_score")
        elif not isinstance(score, (int, float)) or score < 7:
            errors.append(f"web-search model has low vlm_score: {score}")
            
    # 3. Heuristics
    name = (dish.get("name") or "").lower()
    prompt = (dish.get("prompt") or "").lower()
    negative = (dish.get("negative") or "").lower()
    
    if "rice" in name:
        if "cooked" not in prompt:
            errors.append("Rice dish missing 'cooked' in prompt")
        if "raw" not in negative:
            errors.append("Rice dish missing 'raw' exclusions in negative prompt")
            
    if "curry" in name:
        if "curry" not in prompt:
            errors.append("Curry dish missing 'curry' in prompt")
            
    if "grilled" in name:
        is_vegan = dish.get("category", "") == "vegan"
        is_fruit = "fruit" in name or "pineapple" in name or "peach" in name
        if is_vegan or is_fruit:
            if "meat" not in negative:
                errors.append("Grilled vegan/fruit dish missing 'meat' in negative prompt")
                
    return errors

def main():
    parser = argparse.ArgumentParser(description="Audit dish images and prompts.")
    parser.add_argument("--strict", action="store_true", help="Exit 1 on any warning/error.")
    parser.add_argument("--fix", action="store_true", help="Clear unverified or anomalous image references.")
    parser.add_argument("--dish-id", help="Audit a specific dish ID.")
    args = parser.parse_args()
    
    dishes_path = DATA_DIR / "dishes.json"
    images_dir = DATA_DIR / "images"
    
    if not dishes_path.exists():
        print(f"{dishes_path} not found.")
        sys.exit(1)
        
    with open(dishes_path, "r", encoding="utf-8") as f:
        dishes = json.load(f)
        
    total_errors = 0
    fixed_count = 0
    
    for dish_id, dish in dishes.items():
        if args.dish_id and dish_id != args.dish_id:
            continue
            
        if not dish.get("image"):
            continue
            
        errors = check_image(dish_id, dish, images_dir)
        if errors:
            total_errors += len(errors)
            print(f"Dish {dish_id} ('{dish.get('name')}'):")
            for err in errors:
                print(f"  - {err}")
                
            if args.fix:
                dish["image"] = None
                dish["needs_image"] = True
                dish.pop("model", None)
                dish.pop("generated_at", None)
                dish.pop("vlm_score", None)
                dish.pop("vlm_reason", None)
                fixed_count += 1
                
    if args.fix and fixed_count > 0:
        with open(dishes_path, "w", encoding="utf-8") as f:
            json.dump(dishes, f, indent=1, ensure_ascii=False, sort_keys=True)
            # Add trailing newline like the original file might have
            f.write("\n")
        print(f"Fixed {fixed_count} dishes by clearing image references.")
        
    if args.strict and total_errors > 0:
        sys.exit(1)

if __name__ == "__main__":
    main()

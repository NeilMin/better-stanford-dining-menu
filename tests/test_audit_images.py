import json
import pytest
import os
from pathlib import Path
from unittest.mock import patch, MagicMock

@pytest.fixture
def mock_data_dir(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    images_dir = data_dir / "images"
    images_dir.mkdir()
    
    # We will mock pathlib.Path in the script to use this tmp_path
    return data_dir

def run_auditor(data_dir, args=None):
    from scripts.audit_images import main
    if args is None:
        args = []
    
    # Patch the paths in the script
    with patch("scripts.audit_images.DATA_DIR", data_dir):
        with patch("sys.argv", ["audit_images.py"] + args):
            try:
                return main()
            except SystemExit as e:
                return e.code

def test_audit_web_search_vlm_score(mock_data_dir):
    dishes = {
        "1": {
            "name": "Test",
            "image": "1.webp",
            "model": "web-search",
            "vlm_score": 6,
            "prompt": "Test",
            "negative": "Test"
        },
        "2": {
            "name": "Test",
            "image": "2.webp",
            "model": "web-search",
            # missing vlm_score
            "prompt": "Test",
            "negative": "Test"
        },
        "3": {
            "name": "Test",
            "image": "3.webp",
            "model": "web-search",
            "vlm_score": 7, # should pass
            "prompt": "Test",
            "negative": "Test"
        }
    }
    
    with open(mock_data_dir / "dishes.json", "w") as f:
        json.dump(dishes, f)
        
    for k in dishes:
        img_path = mock_data_dir / "images" / f"{k}.webp"
        from PIL import Image
        img = Image.new("RGB", (1024, 576))
        img.save(img_path, "WEBP")
        
    code = run_auditor(mock_data_dir, ["--strict"])
    assert code == 1
    
    # Run with --fix
    run_auditor(mock_data_dir, ["--fix"])
    
    with open(mock_data_dir / "dishes.json", "r") as f:
        fixed = json.load(f)
        
    assert fixed["1"].get("image") is None
    assert fixed["1"].get("needs_image") is True
    assert "model" not in fixed["1"]
    assert "vlm_score" not in fixed["1"]
    
    assert fixed["2"].get("image") is None
    assert fixed["2"].get("needs_image") is True
    assert "model" not in fixed["2"]
    
    assert fixed["3"].get("image") == "3.webp"

def test_audit_rice_dish_heuristics(mock_data_dir):
    dishes = {
        "1": {
            "name": "White Rice",
            "image": "1.webp",
            "model": "sdxl",
            "prompt": "bowl of white rice", # missing cooked
            "negative": "raw"
        },
        "2": {
            "name": "Brown Rice",
            "image": "2.webp",
            "model": "sdxl",
            "prompt": "cooked brown rice",
            "negative": "blurry" # missing raw
        },
        "3": {
            "name": "Fried Rice",
            "image": "3.webp",
            "model": "sdxl",
            "prompt": "cooked fried rice",
            "negative": "raw grain" # valid
        }
    }
    
    with open(mock_data_dir / "dishes.json", "w") as f:
        json.dump(dishes, f)
        
    for k in dishes:
        img_path = mock_data_dir / "images" / f"{k}.webp"
        from PIL import Image
        img = Image.new("RGB", (1024, 576))
        img.save(img_path, "WEBP")
        
    code = run_auditor(mock_data_dir, ["--strict"])
    assert code == 1
    
    run_auditor(mock_data_dir, ["--fix"])
    
    with open(mock_data_dir / "dishes.json", "r") as f:
        fixed = json.load(f)
        
    assert fixed["1"].get("image") is None
    assert fixed["2"].get("image") is None
    assert fixed["3"].get("image") == "3.webp"

def test_audit_curry_dish_heuristics(mock_data_dir):
    dishes = {
        "1": {
            "name": "Chicken Curry",
            "image": "1.webp",
            "model": "sdxl",
            "prompt": "chicken pieces", # missing curry
            "negative": "raw"
        },
        "2": {
            "name": "Beef Curry",
            "image": "2.webp",
            "model": "sdxl",
            "prompt": "beef pieces in curry sauce", # valid
            "negative": "raw"
        }
    }
    
    with open(mock_data_dir / "dishes.json", "w") as f:
        json.dump(dishes, f)
        
    for k in dishes:
        img_path = mock_data_dir / "images" / f"{k}.webp"
        from PIL import Image
        img = Image.new("RGB", (1024, 576))
        img.save(img_path, "WEBP")
        
    run_auditor(mock_data_dir, ["--fix"])
    
    with open(mock_data_dir / "dishes.json", "r") as f:
        fixed = json.load(f)
        
    assert fixed["1"].get("image") is None
    assert fixed["2"].get("image") == "2.webp"

def test_audit_grilled_vegan_heuristics(mock_data_dir):
    dishes = {
        "1": {
            "name": "Grilled Pineapple",
            "image": "1.webp",
            "model": "sdxl",
            "category": "vegan",
            "prompt": "grilled pineapple slices",
            "negative": "blurry" # missing meat exclusion
        },
        "2": {
            "name": "Grilled Peaches",
            "image": "2.webp",
            "model": "sdxl",
            "category": "vegan",
            "prompt": "grilled peaches",
            "negative": "meat, pork, beef" # valid
        }
    }
    
    with open(mock_data_dir / "dishes.json", "w") as f:
        json.dump(dishes, f)
        
    for k in dishes:
        img_path = mock_data_dir / "images" / f"{k}.webp"
        from PIL import Image
        img = Image.new("RGB", (1024, 576))
        img.save(img_path, "WEBP")
        
    run_auditor(mock_data_dir, ["--fix"])
    
    with open(mock_data_dir / "dishes.json", "r") as f:
        fixed = json.load(f)
        
    assert fixed["1"].get("image") is None
    assert fixed["2"].get("image") == "2.webp"

def test_audit_missing_or_corrupt_image(mock_data_dir):
    dishes = {
        "1": {
            "name": "Test1",
            "image": "1.webp", # missing
            "model": "sdxl",
            "prompt": "test", "negative": "test"
        },
        "2": {
            "name": "Test2",
            "image": "2.webp", # wrong aspect ratio
            "model": "sdxl",
            "prompt": "test", "negative": "test"
        }
    }
    
    with open(mock_data_dir / "dishes.json", "w") as f:
        json.dump(dishes, f)
        
    # Create invalid image
    img_path = mock_data_dir / "images" / "2.webp"
    from PIL import Image
    img = Image.new("RGB", (1024, 1024))
    img.save(img_path, "WEBP")
    
    code = run_auditor(mock_data_dir, ["--strict"])
    assert code == 1
    
    run_auditor(mock_data_dir, ["--fix"])
    
    with open(mock_data_dir / "dishes.json", "r") as f:
        fixed = json.load(f)
        
    assert fixed["1"].get("image") is None
    assert fixed["2"].get("image") is None

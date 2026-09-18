"""Talking to a local ComfyUI, and what comes back off it.

Nothing here touches the server: it is a shared install this project may not
start or stop, and 8188 belongs to another project entirely. What is worth
pinning is the workflow that gets sent and the picture that gets written.
"""

from __future__ import annotations

import io

import pytest
from PIL import Image

from bsdm import comfy as comfylib


class TestWorkflow:
    def test_the_prompt_and_the_seed_reach_the_sampler(self):
        flow = comfylib.build_workflow("sdxl", "a plate of rice", "no meat", seed=12345)
        assert flow["2"]["inputs"]["text"] == "a plate of rice"
        assert flow["3"]["inputs"]["text"] == "no meat"
        assert flow["5"]["inputs"]["seed"] == 12345

    def test_it_renders_through_preview_not_save(self):
        """A bulk run must leave nothing behind in a ComfyUI install shared
        with other projects."""
        for model in comfylib.MODELS:
            classes = {node["class_type"] for node in
                       comfylib.build_workflow(model, "p", "n", 1).values()}
            assert "PreviewImage" in classes and "SaveImage" not in classes

    def test_flux_is_given_no_negative_prompt(self):
        """It runs CFG 1.0, so it has no use for one."""
        flow = comfylib.build_workflow("flux", "a plate of rice", "no meat", seed=1)
        assert flow["6"]["inputs"]["text"] == ""

    def test_the_default_size_is_the_models_training_bucket(self):
        flow = comfylib.build_workflow("sdxl", "p", "n", 1)
        assert (flow["4"]["inputs"]["width"], flow["4"]["inputs"]["height"]) == (1344, 768)

    def test_size_and_steps_can_be_overridden(self):
        flow = comfylib.build_workflow("sdxl", "p", "n", 1, size=(512, 512), steps=4)
        assert flow["4"]["inputs"]["width"] == 512
        assert flow["5"]["inputs"]["steps"] == 4

    def test_an_unknown_model_fails_before_anything_is_submitted(self):
        with pytest.raises(KeyError):
            comfylib.build_workflow("dall-e", "p", "n", 1)


class TestToWebp:
    def read(self, blob):
        return Image.open(io.BytesIO(blob))

    def test_the_card_gets_a_sixteen_by_nine_picture(self):
        got = self.read(comfylib.to_webp(Image.new("RGB", (1344, 768), (10, 20, 30))))
        assert got.size == (1024, 576) and got.format == "WEBP"

    def test_a_square_render_is_trimmed_top_and_bottom(self):
        """Centred, so the plate stays on the plate."""
        image = Image.new("RGB", (800, 800), (0, 0, 0))
        image.paste(Image.new("RGB", (800, 100), (255, 0, 0)), (0, 0))      # a band on top
        got = self.read(comfylib.to_webp(image))
        assert got.size == (1024, 576)
        assert got.getpixel((512, 5)) != (255, 0, 0), "the top band was cropped away"

    def test_a_panorama_is_trimmed_at_the_sides(self):
        image = Image.new("RGB", (2000, 500), (0, 0, 0))
        image.paste(Image.new("RGB", (200, 500), (255, 0, 0)), (0, 0))
        got = self.read(comfylib.to_webp(image))
        assert got.size == (1024, 576)
        assert got.getpixel((5, 288)) != (255, 0, 0)

    def test_an_image_already_the_right_shape_is_only_resized(self):
        got = self.read(comfylib.to_webp(Image.new("RGB", (1920, 1080), (10, 20, 30))))
        assert got.size == (1024, 576)

    def test_what_it_writes_is_what_gen_images_calls_current(self):
        """The two rules are a pair: one crops, the other decides whether an
        older file still matches the card."""
        from conftest import load_script

        gen_images = load_script("gen_images")
        blob = comfylib.to_webp(Image.new("RGB", (1344, 768), (10, 20, 30)))
        image = self.read(blob)
        assert abs(image.width / image.height - gen_images.CARD_RATIO) < 0.02

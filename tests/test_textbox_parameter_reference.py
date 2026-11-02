"""Tableau leaves parameter references in text runs as "<[Parameters].[X]>".

They must resolve to the parameter's caption; otherwise Power BI renders the
raw angle-bracket token in the textbox.
"""
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from powerbi_import.pbip_generator import PowerBIProjectGenerator


def _generator():
    return PowerBIProjectGenerator(output_dir=tempfile.mkdtemp())


def _textbox_runs(tmp, converted_objects):
    obj = {
        "type": "text",
        "text_runs": [
            {"text": "Comparing Defaults As Of "},
            {"text": "<[Parameters].[Parameter 2]>", "bold": True},
            {"text": " vs "},
            {"text": "<[Parameters].[Parameter 1]>", "bold": True},
        ],
        "position": {"x": 0, "y": 0, "w": 500, "h": 100},
    }
    _generator()._create_visual_textbox(
        tmp, obj, 1.0, 1.0, 0, converted_objects)
    visual_dir = next(p for p in os.listdir(tmp))
    with open(os.path.join(tmp, visual_dir, "visual.json"), encoding="utf-8") as f:
        return json.load(f)


def _text(document):
    props = document["visual"]["objects"]["general"][0]["properties"]
    return "".join(
        run.get("value", "")
        for para in props["paragraphs"]
        for run in para.get("textRuns", [])
    )


PARAMS = {"parameters": [
    {"name": "[Parameter 1]", "caption": "Previous Period"},
    {"name": "[Parameter 2]", "caption": "Current Period"},
]}


class TestTextboxParameterReference(unittest.TestCase):

    def test_parameter_tokens_resolve_to_captions(self):
        document = _textbox_runs(tempfile.mkdtemp(), PARAMS)
        self.assertEqual(
            _text(document),
            "Comparing Defaults As Of Current Period vs Previous Period",
        )

    def test_no_raw_parameter_token_survives(self):
        document = _textbox_runs(tempfile.mkdtemp(), PARAMS)
        self.assertNotIn("[Parameters]", _text(document))

    def test_without_context_the_text_is_left_alone(self):
        # Callers that pass no converted_objects (e.g. annotations) keep the
        # original behaviour rather than crashing.
        document = _textbox_runs(tempfile.mkdtemp(), None)
        self.assertIn("[Parameters]", _text(document))


if __name__ == "__main__":
    unittest.main()

from podcast_processor.model_output import (
    AdSegmentPredictionList,
    _merge_duplicate_ad_segments,
    clean_and_parse_model_output,
)


class TestMergeDuplicateAdSegments:
    def test_single_key_unchanged(self):
        text = '{"ad_segments": [{"segment_offset": 30.0, "confidence": 0.95}]}'
        assert _merge_duplicate_ad_segments(text) == text

    def test_no_ad_segments_unchanged(self):
        text = '{"other_key": "value"}'
        assert _merge_duplicate_ad_segments(text) == text

    def test_two_duplicate_keys_merged(self):
        text = (
            '{"ad_segments": [{"segment_offset": 30.0, "confidence": 0.95}], '
            '"ad_segments": [{"segment_offset": 165.4, "confidence": 0.9}]}'
        )
        result = _merge_duplicate_ad_segments(text)
        import json

        parsed = json.loads(result)
        assert len(parsed["ad_segments"]) == 2
        assert parsed["ad_segments"][0]["segment_offset"] == 30.0
        assert parsed["ad_segments"][1]["segment_offset"] == 165.4

    def test_three_duplicate_keys_merged(self):
        text = (
            '{"ad_segments": [{"segment_offset": 10.0, "confidence": 0.9}], '
            '"ad_segments": [{"segment_offset": 50.0, "confidence": 0.8}], '
            '"ad_segments": [{"segment_offset": 90.0, "confidence": 0.7}]}'
        )
        result = _merge_duplicate_ad_segments(text)
        import json

        parsed = json.loads(result)
        assert len(parsed["ad_segments"]) == 3

    def test_empty_arrays_handled(self):
        text = '{"ad_segments": [], "ad_segments": [{"segment_offset": 5.0, "confidence": 0.9}]}'
        result = _merge_duplicate_ad_segments(text)
        import json

        parsed = json.loads(result)
        assert len(parsed["ad_segments"]) == 1

    def test_malformed_json_returned_unchanged(self):
        text = '{"ad_segments": [broken, "ad_segments": [also broken}'
        assert _merge_duplicate_ad_segments(text) == text

    def test_preserves_other_fields(self):
        text = (
            '{"ad_segments": [{"segment_offset": 10.0, "confidence": 0.9}], '
            '"confidence": 0.85, '
            '"ad_segments": [{"segment_offset": 50.0, "confidence": 0.8}]}'
        )
        result = _merge_duplicate_ad_segments(text)
        import json

        parsed = json.loads(result)
        assert len(parsed["ad_segments"]) == 2
        assert parsed["confidence"] == 0.85


class TestCleanAndParseModelOutput:
    def test_valid_json(self):
        text = '{"ad_segments": [{"segment_offset": 30.0, "confidence": 0.95}]}'
        result = clean_and_parse_model_output(text)
        assert isinstance(result, AdSegmentPredictionList)
        assert len(result.ad_segments) == 1
        assert result.ad_segments[0].segment_offset == 30.0

    def test_duplicate_keys_parsed(self):
        text = (
            '{"ad_segments": [{"segment_offset": 30.0, "confidence": 0.95}], '
            '"ad_segments": [{"segment_offset": 165.4, "confidence": 0.9}]}'
        )
        result = clean_and_parse_model_output(text)
        assert isinstance(result, AdSegmentPredictionList)
        assert len(result.ad_segments) == 2

    def test_with_markdown_fences(self):
        text = '```json\n{"ad_segments": [{"segment_offset": 10.0, "confidence": 0.9}]}\n```'
        result = clean_and_parse_model_output(text)
        assert len(result.ad_segments) == 1

    def test_empty_ad_segments(self):
        text = '{"ad_segments": []}'
        result = clean_and_parse_model_output(text)
        assert len(result.ad_segments) == 0

    def test_trailing_garbage_after_root_close_is_discarded(self):
        """Regression: when the LLM appends junk after the root ``}`` (we've
        seen e.g. ``…"confidence":0.98}98}0.98}``) the parser must trim back
        to the *first* balanced close, not the rightmost ``}``. The old
        rindex-based heuristic returned the whole malformed tail and every
        ad in the batch was lost — observed on Endless Thread's
        "Manifesting an online rom-com existence" episode where it produced
        zero ad windows despite ~490 transcribed segments."""
        text = (
            '{"ad_segments": ['
            '{"segment_offset": 30.0, "confidence": 0.95},'
            '{"segment_offset": 120.0, "confidence": 0.98}'
            "]}98}0.98}"
        )
        result = clean_and_parse_model_output(text)
        assert isinstance(result, AdSegmentPredictionList)
        assert len(result.ad_segments) == 2
        assert result.ad_segments[1].segment_offset == 120.0

    def test_brace_inside_string_value_does_not_confuse_truncator(self):
        """A ``}`` inside a JSON string must not be treated as a close."""
        text = (
            '{"ad_segments": [{"segment_offset": 5.0, "confidence": 0.9,'
            ' "label": "spurious } in label"}]}'
        )
        result = clean_and_parse_model_output(text)
        assert len(result.ad_segments) == 1

    def test_trailing_whitespace_and_text_after_root_is_discarded(self):
        text = (
            '{"ad_segments": [{"segment_offset": 1.0, "confidence": 0.9}]}'
            "\n\n```\nsome chatter the model tacked on"
        )
        result = clean_and_parse_model_output(text)
        assert len(result.ad_segments) == 1

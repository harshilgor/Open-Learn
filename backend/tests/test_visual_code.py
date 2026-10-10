import pytest
from backend.app.visual_code import normalize_json_literals,validate_visual_code


def test_literal_json_linebreaks_are_normalized_without_execution():
    source="const data=JSON.parse('[{\n\"mass\":5\n}]');"
    result=validate_visual_code({'jsFunctions':source,'jsExpressions':['console.log(data)']})
    assert 'JSON.parse' not in result['jsFunctions']
    assert normalize_json_literals("JSON.parse('bad\njson')")=="JSON.parse('bad\njson')"


def test_invalid_code_is_rejected_and_valid_code_is_not_executed():
    with pytest.raises(ValueError,match='visual_invalid_javascript'):
        validate_visual_code({'jsFunctions':'const x = ;'})
    validate_visual_code({'jsFunctions':'throw new Error("must not execute");'})


def test_missing_dom_targets_only_repair_exact_unique_class():
    result=validate_visual_code({'html':['<div class="map-container"></div>'],'jsFunctions':"function setup(){L.map('map-container')}"})
    assert 'id="map-container"' in result['html'][0]
    with pytest.raises(ValueError,match='visual_missing_dom_target'):
        validate_visual_code({'html':['<div></div>'],'jsFunctions':"document.getElementById('absent').value=5"})

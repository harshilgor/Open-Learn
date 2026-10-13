from backend.app.usage.transport import has_multimodal_input


def test_textual_image_metadata_is_not_multimodal():
    assert not has_multimodal_input({'messages':[{'role':'tool','content':'{"image_url":"https://example.com/photo.jpg"}'},
        {'role':'user','content':'Explain input_image and data: URLs'}]})
    assert not has_multimodal_input({'messages':[{'role':'user','content':[{'type':'text','text':'image_url'}]}]})


def test_real_media_blocks_still_require_bounded_tariff():
    assert has_multimodal_input({'messages':[{'role':'user','content':[{'type':'image_url','image_url':{'url':'https://example.com/photo.jpg'}}]}]})
    assert has_multimodal_input({'input':[{'role':'user','content':[{'type':'input_image','image_url':'data:image/png;base64,AAAA'}]}]})

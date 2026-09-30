from backend.app.content_titles import generate_content_title, looks_like_prompt


def test_titles_share_provider_validation_and_offline_fallback():
    class Provider:
        def complete_json(self, prompt, cap):
            assert 'specific concept' in prompt
            return {'title': 'Neural Network Fundamentals'}
    assert generate_content_title('can you teach me neural networks', [], Provider()) == 'Neural Network Fundamentals'
    assert generate_content_title('can you please teach me neural networks', []) == 'neural networks'
    assert generate_content_title('please explain this', [{'heading': 'Linear Algebra Foundations'}]) == 'Linear Algebra Foundations'
    assert looks_like_prompt('can you teach me this?')
    assert not looks_like_prompt('Neural networks')

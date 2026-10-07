from backend.app.streaming_lesson import ProgressiveLessonParser, semantic_blocks


def test_semantic_blocks_preserve_plain_markdown_without_generic_heading():
    blocks = semantic_blocks("A direct explanation.", "Probability")
    assert [(block.kind, block.heading) for block in blocks] == [("explanation", "")]


def test_semantic_blocks_normalize_ordinary_markdown_sections():
    blocks = semantic_blocks("## Explanation\nMeaning.\n\n## Example\nA coin toss.\n\n## Check\nWhat changes?", "Probability")
    assert [(block.kind, block.heading) for block in blocks] == [("explanation", ""), ("example", "Example"), ("check", "Check")]


def test_progressive_parser_emits_semantic_block_boundaries_across_chunks():
    parser = ProgressiveLessonParser("g1", "Topic")
    operations = parser.feed("## Expla") + parser.feed("nation\nFirst idea.\n## Example\nA coin") + parser.finish()
    assert [(item.action, item.kind, item.heading) for item in operations if item.action == "start"] == [
        ("start", "explanation", ""), ("start", "example", "Example")]
    assert any(item.action == "delta" and "First idea" in item.text for item in operations)
    assert [item.action for item in operations].count("complete") == 2

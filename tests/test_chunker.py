from metrotrance.services.chunker import chunk_text


def test_chunker_keeps_content_and_limits_size():
    text = "Первое предложение. Второе предложение. " * 80
    chunks = chunk_text(text, max_chars=220)
    assert len(chunks) > 3
    assert all(len(item) <= 310 for item in chunks)
    assert "Первое предложение" in " ".join(chunks)


def test_chunker_empty():
    assert chunk_text("   ") == []


def test_explicit_pause_markers_are_not_spoken():
    from metrotrance.services.chunker import segment_text

    segments = segment_text("Первая фраза. [пауза 8] Вторая фраза.", max_chars=80, min_chars=10)
    assert len(segments) == 2
    assert segments[0].pause_after == 8.0
    assert "пауза" not in " ".join(item.text for item in segments).lower()


def test_paragraph_pause_is_longer_than_sentence_pause():
    from metrotrance.services.chunker import segment_text

    segments = segment_text("Первая фраза. Вторая фраза.\n\nНовый абзац.", max_chars=18, min_chars=1)
    assert any(item.pause_kind == "paragraph" for item in segments[:-1])


def test_studio_pause_markers_have_distinct_depths():
    from metrotrance.services.chunker import segment_text

    text = (
        "Первая фраза. [короткая пауза] Вторая фраза. "
        "[глубокая пауза] Третья фраза. [интеграционная пауза] Финал."
    )
    segments = segment_text(text, max_chars=80, min_chars=5)
    pauses = [item.pause_after for item in segments[:-1]]
    assert pauses[0] < pauses[1] < pauses[2]
    assert pauses[2] >= 8.0

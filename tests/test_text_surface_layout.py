from worker.text_surface_layout import layout_text_for_surface


def test_layout_text_for_surface_shrinks_and_scrolls_long_reports():
    block = {
        "surface_size": {"x": 220, "y": 120},
        "font_size": 0.8,
        "font": "Debug",
        "text_padding": 2,
        "alignment": "LEFT",
        "content_type": "TEXT_AND_IMAGE",
    }
    text = "\n".join(f"Line {index:02d} value value value" for index in range(20))

    first = layout_text_for_surface(text, block, sequence=1)
    later = layout_text_for_surface(text, block, sequence=6)

    assert first["font_size"] < 0.8
    assert first["layout"]["scrolling"] is True
    assert first["text"] != later["text"]
    assert len(first["text"].splitlines()) <= first["layout"]["visible_lines"]
    assert first["font"] == "Debug"
    assert first["alignment"] == "LEFT"
    assert first["content_type"] == "TEXT_AND_IMAGE"


def test_layout_text_for_surface_keeps_short_reports_stable():
    block = {"surface_size": {"x": 512, "y": 512}, "font_size": 0.6}

    laid_out = layout_text_for_surface("A\nB\n", block, sequence=99)

    assert laid_out["text"] == "A\nB\n"
    assert laid_out["font_size"] == 0.6
    assert laid_out["layout"]["scrolling"] is False

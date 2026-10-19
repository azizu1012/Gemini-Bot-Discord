"""Test logic picker model thuần (offline, không cần kết nối Discord)."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.handlers.discord.ui import (
    MODELS_PER_PAGE,
    ModelPickerView,
    filter_models,
    normalize_models,
    paginate_models,
    total_model_pages,
)


def make_models(n):
    return [{"id": f"model-{i:03d}", "name": f"Model {i}"} for i in range(n)]


def test_normalize_models_dedupes_sorts_and_skips_blank():
    raw = [
        {"id": "b", "name": "Bee"},
        {"id": "a"},
        {"id": "b", "name": "Bee dup"},
        {"id": "  ", "name": "blank"},
        {},
    ]
    result = normalize_models(raw)
    assert [m["id"] for m in result] == ["a", "b"]
    assert result[1]["name"] == "Bee"
    assert result[0]["name"] == "a"  # thiếu name -> fallback về id


def test_total_pages_for_100_plus_models():
    assert total_model_pages(0) == 1
    assert total_model_pages(1) == 1
    assert total_model_pages(MODELS_PER_PAGE) == 1
    assert total_model_pages(MODELS_PER_PAGE + 1) == 2
    assert total_model_pages(137) == 6


def test_paginate_covers_all_models_without_loss():
    models = make_models(137)
    seen = []
    for page in range(total_model_pages(len(models))):
        seen.extend(paginate_models(models, page))
    assert [m["id"] for m in seen] == [m["id"] for m in models]


def test_filter_models_matches_id_and_name_case_insensitive():
    models = [
        {"id": "gemini-2.5-flash", "name": "Gemini Flash"},
        {"id": "gpt-4o", "name": "GPT-4o"},
    ]
    assert [m["id"] for m in filter_models(models, "FLASH")] == ["gemini-2.5-flash"]
    assert [m["id"] for m in filter_models(models, "gpt")] == ["gpt-4o"]
    assert len(filter_models(models, "")) == 2
    assert filter_models(models, "khong-co-gi") == []


def test_picker_view_pagination_and_search():
    # discord.ui.View cần event loop đang chạy khi khởi tạo (discord.py >= 2.x).
    async def _run():
        view = ModelPickerView(models=make_models(137), slot="reasoning")
        assert view.total_pages == 6
        assert len(view.page_models) == MODELS_PER_PAGE
        view.page = 5
        assert len(view.page_models) == 12
        view.apply_query("model-00")
        assert view.page == 0
        assert all("model-00" in m["id"] for m in view.filtered)
        assert view.total_pages == 1
        view.stop()
    asyncio.run(_run())


if __name__ == "__main__":
    test_normalize_models_dedupes_sorts_and_skips_blank()
    test_total_pages_for_100_plus_models()
    test_paginate_covers_all_models_without_loss()
    test_filter_models_matches_id_and_name_case_insensitive()
    test_picker_view_pagination_and_search()
    print("ALL PASS")

"""Test backward-compatibility facade modules."""
import sys
sys.path.insert(0, ".")

def test_facades_importable():
    from src.services.search_subtask_worker import SearchSubtaskWorker
    from src.tools.calculator_service import CalculatorService
    from src.tools.search_engine import (
        SearchEngine,
        SearchCache,
        QueryPlanner,
        SearchReranker,
        SearchRecord,
    )
    from src.tools.weather_service import WeatherService

    assert SearchSubtaskWorker is not None
    assert CalculatorService is not None
    assert SearchEngine is not None
    assert SearchCache is not None
    assert QueryPlanner is not None
    assert SearchReranker is not None
    assert SearchRecord is not None
    assert WeatherService is not None

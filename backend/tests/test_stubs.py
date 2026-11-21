"""Stubs import cleanly and fail loudly until their owners implement them."""
import pytest

from app.controls import duplicates, engine, routing, validate


@pytest.mark.parametrize("fn", [validate.validate, duplicates.find_duplicates, routing.route, engine.run_controls])
def test_controls_stubs_raise(fn):
    with pytest.raises(NotImplementedError):
        fn(None, None)

import pytest
from typing import Annotated

from pydantic_construct import ConstructModel, OmitInMode
from construct import Int32ul


class SimpleModel(ConstructModel):
    a: Annotated[int, Int32ul]
    b: Annotated[int, Int32ul, OmitInMode("json")]
    c: Annotated[int, Int32ul, OmitInMode("python")]
    d: Annotated[int, Int32ul, OmitInMode({"json", "python"})]
    e: Annotated[int, Int32ul, OmitInMode("binary")]
    f: Annotated[int, Int32ul]


@pytest.fixture
def model() -> SimpleModel:
    return SimpleModel(a=1, b=2, c=3, d=4, e=5, f=6)


def test_model_dump_python_mode(model: SimpleModel):
    result = model.model_dump(mode="python")

    assert result == {
        "a": 1,
        "b": 2,          # excluded only in json
        # "c" excluded
        # "d" excluded
        "e": 5,          # excluded only in binary
        "f": 6,
    }
    assert "c" not in result
    assert "d" not in result


def test_model_dump_json_mode(model: SimpleModel):
    result = model.model_dump(mode="json")

    assert result == {
        "a": 1,
        # "b" excluded
        "c": 3,
        # "d" excluded
        "e": 5,
        "f": 6,
    }
    assert "b" not in result
    assert "d" not in result


def test_model_dump_json_string(model: SimpleModel):
    # ensure model_dump_json also respects it
    result = model.model_dump_json()

    # simple containment checks instead of full parsing
    assert '"a":1' in result
    assert '"c":3' in result
    assert '"e":5' in result
    assert '"f":6' in result

    assert '"b":2' not in result
    assert '"d":4' not in result


def test_model_dump_binary_mode(model: SimpleModel):
    result = model.model_dump_bytes()
    assert result == b"\x01\x00\x00\x00\x02\x00\x00\x00\x03\x00\x00\x00\x04\x00\x00\x00\x06\x00\x00\x00"


def test_multiple_metadata_entries():
    class MultiMetaModel(ConstructModel):
        x: Annotated[int, Int32ul, OmitInMode("json"), OmitInMode("python")]

    m = MultiMetaModel(x=1)

    assert m.model_dump_json() == "{}"
    assert m.model_dump() == {}
    assert m.model_dump_bytes() == b"\x01\x00\x00\x00"


def test_no_metadata_field():
    class PlainModel(ConstructModel):
        x: Annotated[int, Int32ul]

    m = PlainModel(x=1)

    assert m.model_dump_json() == '{"x":1}'
    assert m.model_dump() == {"x": 1}
    assert m.model_dump_bytes() == b"\x01\x00\x00\x00"

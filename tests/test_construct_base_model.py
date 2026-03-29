from typing import Annotated

import pytest
from hypothesis import given, strategies as st
from pydantic import BeforeValidator, Field, ValidationError

from pydantic_construct import ConstructModel, OmitInMode
from construct import Int32ul, Int64ul, Struct


class FreeMemoryModel(ConstructModel):
    pid: Annotated[int, Int32ul]
    address: Annotated[int, Int64ul]
    length: Annotated[int, Int32ul]


class SetBreakpointModel(ConstructModel):
    index: Annotated[int, Int32ul]
    enabled: Annotated[bool, Int32ul]
    address: Annotated[int, Int64ul]


class SimpleModel(ConstructModel):
    x: Annotated[int, Int32ul]
    y: Annotated[int, Int32ul]


class SubModel(ConstructModel):
    value: Annotated[int, Int32ul]


class ParentModel(ConstructModel):
    a: Annotated[int, Int32ul]
    b: SubModel


@given(
    x=st.integers(min_value=0, max_value=2**32 - 1),
    y=st.integers(min_value=0, max_value=2**32 - 1),
)
def test_round_trip_property(x, y):
    obj = SimpleModel(x=x, y=y)
    data = obj.model_dump_bytes()
    parsed = SimpleModel.model_validate_bytes(data)

    assert parsed == obj


@given(st.binary(min_size=8, max_size=8))  # 2x Int32ul
def test_bytes_stability(data):
    model = SimpleModel.model_validate_bytes(data)
    rebuilt = model.model_dump_bytes()

    assert rebuilt == data


@given(
    a=st.integers(min_value=0, max_value=2**32 - 1),
    b=st.integers(min_value=0, max_value=2**32 - 1),
)
def test_nested_round_trip(a, b):
    obj = ParentModel(a=a, b=SubModel(value=b))
    data = obj.model_dump_bytes()
    parsed = ParentModel.model_validate_bytes(data)

    assert parsed.a == a
    assert parsed.b.value == b


def test_free_memory_parse_build():
    original = FreeMemoryModel(pid=42, address=0x12345678abcdef00, length=256)
    data = original.model_dump_bytes()
    parsed = FreeMemoryModel.model_validate_bytes(data)
    assert parsed.pid == 42
    assert parsed.address == 0x12345678abcdef00
    assert parsed.length == 256


def test_set_breakpoint_parse_build():
    bp = SetBreakpointModel(index=1, enabled=True, address=0xdeadbeefcafebabe)
    data = bp.model_dump_bytes()
    parsed = SetBreakpointModel.model_validate_bytes(data)
    assert parsed.index == 1
    assert parsed.enabled
    assert parsed.address == 0xdeadbeefcafebabe


def test_raise_multi_inheritance():
    with pytest.raises(TypeError):
        class DebugModel(FreeMemoryModel, SetBreakpointModel):
            pass


def test_diamond_inheritance():
    class A(ConstructModel): ...
    class B(A): ...
    class C(A): ...
    class D(B, C): ...


def test_empty_model():
    class Dummy(ConstructModel):
        pass

    dummy = Dummy()
    data = dummy.model_dump_bytes()
    parsed = Dummy.model_validate_bytes(data)

    assert data == b""
    assert parsed is not None


def test_missing_annotation_raises():
    with pytest.raises(TypeError):
        class Dummy(ConstructModel):
            number: int = 15

        Dummy().model_dump_bytes()


def test_default_and_validator():
    class ModelWithDefault(ConstructModel):
        val: Annotated[int, Field(validate_default=True), BeforeValidator(lambda v: v + 1), Int32ul] = 10

    # Default applies and validator runs
    obj = ModelWithDefault()
    assert obj.val == 11

    # Parsing applies validator
    data = obj.model_dump_bytes()
    parsed = ModelWithDefault.model_validate_bytes(data)
    assert parsed.val == 12


def test_illegal_field():
    with pytest.raises(TypeError):
        class BadModel(ConstructModel):
            field: int  # Not Annotated or ConstructModel


def test_padding_fields_filtered():
    from construct import Padding

    class ModelWithPadding(ConstructModel):
        x: Annotated[int, Int32ul]
        pad: Annotated[bytes | None, Padding(4), OmitInMode({"json", "python"})] = None

    obj = ModelWithPadding(x=123)
    data = obj.model_dump_bytes()
    parsed = ModelWithPadding.model_validate_bytes(data)

    assert data == b"\x7B\x00\x00\x00\x00\x00\x00\x00"
    assert parsed.x == 123


@given(st.integers(min_value=1, max_value=2**32 - 1))
def test_nested_annotation(n):
    construct_int = Annotated[int, Int32ul]

    class Dummy(ConstructModel):
        positive: Annotated[construct_int, Field(gt=0)]

    with pytest.raises(ValidationError):
        Dummy(positive=0)

    obj = Dummy(positive=n)
    data = obj.model_dump_bytes()
    parsed = Dummy.model_validate_bytes(data)

    assert obj.positive == n
    assert data == Int32ul.build(n)
    assert parsed.positive == n


def test_inline_nested():
    class TestModel(ConstructModel):
        inline: Annotated[dict, Struct(
            "a" / Int32ul,
            "b" / Struct(
                "c" / Int32ul[2],
            )
        )]

    obj = TestModel(inline={
        "a": 3,
        "b": {
            "c": [1, 2],
        },
    })

    data = obj.model_dump_bytes()
    parsed = TestModel.model_validate_bytes(data)

    assert parsed.inline["a"] == 3
    assert parsed.inline["b"]["c"] == [1, 2]


def test_list():
    class TestModel(ConstructModel):
        numbers: Annotated[list[int], Int32ul[3]]

    obj = TestModel(numbers=[1, 2, 3])

    data = obj.model_dump_bytes()
    parsed = TestModel.model_validate_bytes(data)

    assert isinstance(parsed.numbers, list)
    assert parsed.numbers == [1, 2, 3]


def test_enum_round_trip():
    from enum import IntEnum

    class TestModes(IntEnum):
        json = 0
        xml = 1
        yaml = 2
        toml = 3
        ini = 4
        binary = 5

    class TestModel(ConstructModel):
        mode: Annotated[TestModes, Int32ul] = TestModes.toml

    obj = TestModel(mode=TestModes.xml)
    data = obj.model_dump_bytes()
    parsed = TestModel.model_validate_bytes(data)

    assert parsed.mode == TestModes.xml


def test_enum_bytes():
    from enum import IntEnum

    class TestModes(IntEnum):
        json = 0
        xml = 1
        yaml = 2
        toml = 3
        ini = 4
        binary = 5

    class TestModel(ConstructModel):
        mode: Annotated[TestModes, Int32ul] = TestModes.toml

    obj = TestModel()
    data = obj.model_dump_bytes()

    assert data == b"\x03\x00\x00\x00"

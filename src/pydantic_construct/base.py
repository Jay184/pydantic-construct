from typing import ClassVar, Any, Self, Literal, Callable, Iterable
from typing import Annotated, get_origin, get_args
from typing_extensions import Buffer
from functools import lru_cache
from asyncio import StreamReader

import dataclasses

from pydantic import BaseModel, model_serializer, main
from construct import Construct, Container, Struct
from pydantic_core.core_schema import SerializerFunctionWrapHandler, SerializationInfo


def extract_construct(annotation):
    """Extract Construct instance from Annotated[...]"""
    if get_origin(annotation) is Annotated:
        base_type, *metadata = get_args(annotation)

        for meta in metadata:
            if isinstance(meta, Construct):
                return meta

    return None


def binary_after(field_name: str):
    def decorator(func):
        setattr(func, "__binary_after__", field_name)
        return func
    return decorator


def binary_before(field_name: str):
    def decorator(func):
        setattr(func, "__binary_before__", field_name)
        return func
    return decorator


Mode = Literal["python", "json", "binary"]


@dataclasses.dataclass
class OmitInMode:
    modes: set[Mode] = dataclasses.field(default_factory=lambda: {"json"})

    def __init__(self, modes: Mode | Iterable[Mode] = "json"):
        if isinstance(modes, str):
            self.modes = {modes}
        else:
            self.modes = set(modes)

    def matches(self, current_mode: str) -> bool:
        return current_mode in self.modes


class ConstructModel(BaseModel):
    # Dynamically generated struct
    struct: ClassVar[Struct]
    _computed_subcons: ClassVar[dict[str, Construct]]

    # Cached order for computed fields
    _binary_final_order: ClassVar[list[str]]
    _binary_ordered_struct: ClassVar[Struct]

    @model_serializer(mode="wrap")
    def exclude_omissions(
        self,
        handler: SerializerFunctionWrapHandler,
        info: SerializationInfo,
    ) -> dict[str, object]:
        serialized = handler(self)
        cls = type(self)

        return {
            name: value
            for name, value in serialized.items()
            if not cls._is_omitted_in_mode(name, info.mode)
        }

    @classmethod
    def __pydantic_init_subclass__(cls, **kwargs):
        """Hook for Pydantic subclass initialization."""
        super().__pydantic_init_subclass__(**kwargs)

        roots = cls._get_construct_roots()

        if len(roots) > 1:
            raise TypeError(
                f"{cls.__name__} has multiple ConstructModel roots: "
                f"{[r.__name__ for r in roots]}. "
                "This leads to ambiguous binary layout. Use composition instead."
            )

        subcons = {}
        computed_subcons = {}

        for name, field in cls.model_fields.items():
            if cls._is_omitted_in_mode(name, mode="binary"):
                continue

            construct_type = None

            if isinstance(field.annotation, type) and issubclass(field.annotation, ConstructModel):
                construct_type = field.annotation.struct
            else:
                for meta in field.metadata:
                    if isinstance(meta, Construct):
                        construct_type = meta
                        break

            if construct_type is None:
                raise TypeError(
                    f"Field '{name}' must be Annotated with a Construct type"
                )

            subcons[name] = construct_type

        for name, field in cls.model_computed_fields.items():
            if cls._is_omitted_in_mode(name, mode="binary"):
                continue

            construct_type = extract_construct(field.return_type)

            if construct_type is None:
                raise TypeError(
                    f"Computed field '{name}' must return Annotated[..., Construct]"
                )

            computed_subcons[name] = construct_type

        cls.struct = Struct(**subcons)
        cls._computed_subcons = computed_subcons

        base_order = list(subcons.keys())
        final_order = base_order.copy()

        for name, cons in computed_subcons.items():
            func = getattr(cls, name).fget
            after = getattr(func, "__binary_after__", None)
            before = getattr(func, "__binary_before__", None)

            if after and before:
                raise TypeError(f"{name} cannot have both before and after")
            if after:
                idx = final_order.index(after) + 1
            elif before:
                idx = final_order.index(before)
            else:
                idx = len(final_order)
            final_order.insert(idx, name)

        cls._binary_final_order = final_order

        # Build a cached Struct for serialization
        ordered_subcons = []
        for name in final_order:
            if name in subcons:
                ordered_subcons.append(name / subcons[name])
            elif name in computed_subcons:
                ordered_subcons.append(name / computed_subcons[name])

        cls._binary_ordered_struct = Struct(*ordered_subcons)

    @classmethod
    def _get_construct_roots(cls: type):
        roots = set()

        for base in cls.__mro__:
            if (
                isinstance(base, type)
                and issubclass(base, ConstructModel)
                and base is not ConstructModel
            ):
                # Check if this base has a ConstructModel parent (excluding base class)
                has_construct_parent = any(
                    issubclass(parent, ConstructModel)
                    and parent is not ConstructModel
                    for parent in base.__bases__
                )

                if not has_construct_parent:
                    roots.add(base)

        return roots

    @classmethod
    def _is_omitted_in_mode(cls, name: str, mode: Mode | str) -> bool:
        return any(
            isinstance(meta, OmitInMode) and meta.matches(mode)
            for meta in cls._get_field_metadata(name)
        )

    @classmethod
    @lru_cache
    def _get_field_metadata(cls, name: str):
        # Regular field
        if name in cls.model_fields:
            return cls.model_fields[name].metadata

        # Computed field
        if name in cls.model_computed_fields:
            annotation = cls.model_computed_fields[name].return_type
            if get_origin(annotation) is Annotated:
                return get_args(annotation)[1:]
            return ()

        # Unknown field
        return ()

    @classmethod
    def model_validate_bytes(
        cls,
        obj: bytes | bytearray | Buffer,
        *,
        strict: bool | None = None,
        extra: main.ExtraValues | None = None,
        from_attributes: bool | None = None,
        context: Any | None = None,
        by_alias: bool | None = None,
        by_name: bool | None = None,
    ) -> Self:
        parsed: Container = cls.struct.parse(obj)

        filtered = {
            k: v for k, v in dict(parsed).items()
            if not k.startswith("_")
        }

        return cls.model_validate(
            filtered,
            strict=strict,
            extra=extra,
            from_attributes=from_attributes,
            context=context,
            by_alias=by_alias,
            by_name=by_name,
        )

    def model_dump_bytes(
        self,
        *,
        mode: Literal["json", "python", "binary"] | str = "binary",
        include: main.IncEx | None = None,
        exclude: main.IncEx | None = None,
        context: Any | None = None,
        by_alias: bool | None = None,
        exclude_unset: bool = False,
        exclude_defaults: bool = False,
        exclude_none: bool = False,
        exclude_computed_fields: bool = False,
        round_trip: bool = False,
        warnings: bool | Literal["none", "warn", "error"] = True,
        fallback: Callable[[Any], Any] | None = None,
        serialize_as_any: bool = False,
    ) -> bytes:
        data = self.model_dump(
            mode=mode,
            include=include,
            exclude=exclude,
            context=context,
            by_alias=by_alias,
            exclude_unset=exclude_unset,
            exclude_defaults=exclude_defaults,
            exclude_none=exclude_none,
            exclude_computed_fields=exclude_computed_fields,
            round_trip=round_trip,
            warnings=warnings,
            fallback=fallback,
            serialize_as_any=serialize_as_any,
        )

        # Only include fields that exist in struct
        # noinspection PyProtectedMember
        values = {
            k: v for k, v in data.items()
            if k in self.struct._subcons or k in self._computed_subcons
        }

        return self._binary_ordered_struct.build(values)

    @classmethod
    async def model_validate_reader(
        cls,
        obj: StreamReader,
        *,
        strict: bool | None = None,
        extra: main.ExtraValues | None = None,
        from_attributes: bool | None = None,
        context: Any | None = None,
        by_alias: bool | None = None,
        by_name: bool | None = None,
    ) -> Self:
        data = await obj.readexactly(cls.struct.sizeof())
        return cls.model_validate_bytes(
            data,
            strict=strict,
            extra=extra,
            from_attributes=from_attributes,
            context=context,
            by_alias=by_alias,
            by_name=by_name,
        )

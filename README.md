# Pydantic-Construct

**Pydantic-Construct** integrates Pydantic with `construct` to provide **typed binary serialization and parsing** using standard Pydantic models.

Define binary layouts declaratively with type annotations, while keeping Pydantic’s validation and serialization.

---

## Features

* Declarative binary schemas via `Annotated`
* `model_dump_bytes()` / `model_validate_bytes()`
* Nested models
* Computed fields with ordering control
* Mode-aware field omission (`json`, `python`, `binary`)
* Async parsing from streams

---

## Installation

```bash
pip install pydantic-construct
```

---

## Quick Start

Minimal example:

```python
from typing import Annotated
from construct import Int32ul
from pydantic_construct import ConstructModel

class Model(ConstructModel):
    x: Annotated[int, Int32ul]

m = Model(x=123)

data = m.model_dump_bytes()
parsed = Model.model_validate_bytes(data)

assert data == b"\x7B\x00\x00\x00"
assert parsed.x == 123
```

With padding (ignored outside binary mode):

```python
from typing import Annotated
from pydantic_construct import ConstructModel, OmitInMode
from construct import Padding, Int32ul

class Model(ConstructModel):
    x: Annotated[int, Int32ul]
    pad: Annotated[bytes | None, Padding(4), OmitInMode({"json", "python"})] = None
```

---

## Core Concepts

### Binary Fields

Each field must define a `construct` type via `Annotated`:

```python
x: Annotated[int, Int32ul]
```

---

### Mode-Based Omission

Exclude fields depending on serialization mode:

```python
from typing import Annotated
from pydantic_construct import OmitInMode
from construct import Padding

pad: Annotated[
    bytes | None,
    Padding(4),
    OmitInMode({"json", "python"})
]
```

Modes:

* `"python"`
* `"json"`
* `"binary"`

---

### Nested Models

```python
from typing import Annotated
from pydantic_construct import ConstructModel
from construct import Int32ul

class Header(ConstructModel):
    length: Annotated[int, Int32ul]

class Packet(ConstructModel):
    header: Header
```

---

### Computed Fields (Binary)

Computed fields can participate in binary serialization if they return `Annotated[..., Construct]`.

```python
from typing import Annotated
from pydantic_construct import ConstructModel, binary_after
from pydantic import computed_field
from construct import Int32ul

class Example(ConstructModel):
    x: Annotated[int, Int32ul]

    @computed_field
    @property
    @binary_after("x")
    def checksum(self) -> Annotated[int, Int32ul]:
        return self.x ^ 0xFFFFFFFF
```

Positioning:

* `@binary_after("field")`
* `@binary_before("field")`

---

## API Overview

### Serialize to Binary

```python
data = model.model_dump_bytes()
```

---

### Parse from Binary

```python
model = Model.model_validate_bytes(data)
```

---

### Async Stream Parsing

```python
model = await Model.model_validate_reader(reader)
```

---

## Design Notes

* A `construct.Struct` is generated at class creation time
* Field order is deterministic and includes computed fields
* Multiple `ConstructModel` roots in inheritance are disallowed

---

## Constraints

* Every field must define a `construct` type
* Computed fields must return `Annotated[..., Construct]`
* Binary layout must be deterministic

---

## License

0BSD

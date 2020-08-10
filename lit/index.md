# Overview
The script looks as follows

``` {.python file=check-deps.py}
from __future__ import annotations

import sys
import io
import configparser
import asyncio
import re

<<imports>>
<<async-cache>>
<<types>>
<<parsers>>
<<helper-functions>>

async def main():
    <<main>>

asyncio.run(main())
```

We start by declaring some types and methods on those types, then implement some parsers that we need to parse version numbers and version constraints. After that we can fill in the `main` function.

# Types
This script is heavy on type hints and data classes, as I think every modern Python script should.

``` {.python #imports}
from dataclasses import dataclass, field
from typing import Optional, List, Mapping, Tuple, Callable, TypeVar
```

We have two custom exceptions that may occur: `ConfigError` for errors in the config file and `ParserError` for errors in parsing version numbers.

``` {.python #types}
class ConfigError(Exception):
    pass

class ParserError(Exception):
    pass
```

## Versions
Versions usually come as a set of integers separated by points, and may contain a non-numerical suffix.

``` {.python #types}
@dataclass
class Version:
    number: Tuple[int, ...]
    extra: Optional[str]

    <<version-methods>>
```

To perform comparisons we look at major version first and than move down to minor versions.

``` {.python #version-methods}
def _less_than(self, other, when_equal):
    for n, m in zip(self.number, other.number):
        if n < m:
            return True
        elif n > m:
            return False
    return when_equal
```

Using the `_less_than` helper method we can define the four inequality operators:

``` {.python #version-methods}
def __lt__(self, other):
    return self._less_than(other, when_equal=False)

def __gt__(self, other):
    return other._less_than(self, when_equal=False)

def __le__(self, other):
    return self._less_than(other, when_equal=True)

def __ge__(self, other):
    return other._less_than(self, when_equal=True)
```

Remains equality and inequalty:

``` {.python #version-methods}
def __eq__(self, other):
    for n, m in zip(self.number, other.number):
        if n != m:
            return False
        return True

def __ne__(self, other):
    return not self == other
```

And conversion to string:

``` {.python #version-methods}
def __str__(self):
    return ".".join(map(str, self.number)) + (self.extra or "")
```

## Relation
The `Relation` type encodes the requested ordinal relation with a given version number. This is an `Enum` containing the `LT`, `GT`, `LE`, `GE`, `EQ` and `NE` values, each corresponding to their repsective magic method counterparts (i.e. `LT` with `__lt__`, and so on).

``` {.python #imports}
from enum import Enum
```

``` {.python #types}
class Relation(Enum):
    GE = 1
    LE = 2
    LT = 3
    GT = 4
    EQ = 5
    NE = 6

    def __str__(self):
        return {"GE": ">=", "LE": "<=", "LT": "<",
                "GT": ">", "EQ": "==", "NE": "!="}[self.name]
```

## Version constraint
A version constraint is a relation with a version. It is a callable object that will perform the comparison with the found version.

``` {.python #types}
@dataclass
class VersionConstraint:
    version: Version
    relation: Relation

    def __call__(self, other: Version) -> bool:
        method = f"__{self.relation.name}__".lower()
        return getattr(other, method)(self.version)

    def __str__(self):
        return f"{self.relation}{self.version}"
```

## VersionTest
The `VersionTest` class contains all information from each section in the configuration file. We'll go through this line by line. The `run` method will be treated in the section on the `main` function, since it is integral to the control flow of the script.

``` {.python #types}
@dataclass
class VersionTest:
    <<version-test-fields>>
    <<version-test-run>>
```

The main three fields are `name`, `require` and `get_version`. The `name` field is filled with the section title in the init file, the `require` field contains the version constraint and `get_version` is a piece of shell script that should give the version number.

``` {.python #version-test-fields}
name: str
require: VersionConstraint
get_version: str
```

In many cases you will want to run an additional regular expression on top of the shell one-liner to get the version. Many programs output way too much information, when all we want is the version (try `bash --version` for instance). To prevent `sed` commands on every turn, there is an optional field `pattern` that should contain a regular expression that has the version number as the first sub-group.

``` {.python #version-test-fields}
pattern: Optional[str] = None
```

If the version check fails it is nice to give the user some info on how to upgrade to a more recent version. We have one field for human-readable suggestions and one field for possible script lines.

``` {.python #version-test-fields}
suggestion_text: Optional[str] = None
suggestion: Optional[str] = None
```

Some programs depend on other programs to even be able to check the version. For instance if the executable is part of a Python package that can be installed with `pip`, we need `pip` to check for the package version. You can enter a (comma-separated) list of names to give dependencies.

``` {.python #version-test-fields}
depends: List[str] = field(default_factory=list)
```

For the same use-case it is nice to have a template for `pip` or `npm` packages.

``` {.python #version-test-fields}
template: Optional[str] = None
```

## Result
When a program has been tested for its version, we need to store a result.

``` {.python #types}
@dataclass
class Result:
    test: VersionTest
    success: bool
    failure_text: Optional[str] = None
    found_version: Optional[Version] = None
```

# Parsers
Writing a parser becomes a lot easier if you remember this poem (from Graham Hutton):

> A parser for things  
> Is a function from strings  
> To lists of pairs  
> Of things and strings

Since Python is not Haskell, we can get away with a parser returning a tuple of a thing and a string. The case where a parser fails, we throw an exception. The idea is that you give a function a string, then the function consumes part of this string, producing an object and returns the result together with the remainder of the input string.

In this universe, one of the primive parsers is `split_at`, which will split a string at the first occurence of any of the given characters.

``` {.python #parsers}
def split_at(split_chars: str, x: str) -> Tuple[str, str]:
    a = x.split(split_chars, maxsplit=1)
    if len(a) == 2:
        return a[0], a[1]
    else:
        return a[0], ""
```

One step up, we can try to convert the first element returned by `split_at` with a function to some other type.
We need a generic type variable to properly annotate this function.

``` {.python #types}
T = TypeVar("T")
```

``` {.python #parsers}
def parse_split_f(split_chars: str, f: Callable[[str], T], x: str) \
        -> Tuple[T, str]:
    item, x = split_at(split_chars, x)
    val = f(item)
    return val, x
```

Now we can parse a version string.

``` {.python #parsers}
def parse_version(x: str) -> Tuple[Version, str]:
    _x = x
    number = []
    extra = None

    while True:
        try:
            n, _x = parse_split_f(".", int, _x)
            number.append(n)
        except ValueError:
            if len(x) > 0:
                m = re.match("([0-9]*)(.*)", _x)
                if lastn := m and m.group(1):
                    number.append(int(lastn))
                if suff := m and m.group(2):
                    extra = suff or None
                else:
                    extra = _x
            break

    if not number:
        raise ParserError(f"A version needs a numeric component, got: {x}")

    return Version(tuple(number), extra), _x
```

To parse a relation, we look-up the enum from a symbol table.

``` {.python #parsers}
def parse_relation(x: str) -> Tuple[Relation, str]:
    op_map = {
        "<=": Relation.LE,
        ">=": Relation.GE,
        "<": Relation.LT,
        ">": Relation.GT,
        "==": Relation.EQ,
        "!=": Relation.NE}
    for sym, op in op_map.items():
        if x.startswith(sym):
            return (op, x[len(sym):])
    raise ParserError(f"Not a comparison operator: {x}")
```

We can now chain together the different parsers to parse a version constraint:

``` {.python #parsers}
def parse_version_constraint(x: str) -> Tuple[VersionConstraint, str]:
    relation, x = parse_relation(x)
    version, x = parse_version(x)
    return VersionConstraint(version, relation), x
```

# Main

## A note on Python's AsyncIO
The version tests are run asynchronously and with caching. This is a slightly non-trivial recipe. There will be simultaneous requests for the same result, so we need an `asyncio.Lock` to handle write-permission while the task is running. The problem with Python's `asyncio` library (and why I have had a lot of trouble understanding its behaviour) is that it suffers from a leaky abstraction. The `async`/`await` keywords were put there to mimick Javascript syntax. Javascript is deeply asynchronous down to the core. The Javascript run-time doesn't need a loop-manager because it **is** a loop manager. In Python however, we need to start a loop-manager before anything asynchronous can happen. The `asyncio.Lock` object talks directly to the loop-manager. This is why the loop-manager needs to be instantiated before any of the other `async` routines are. It feels very awkward to have features that are supported with **syntax** no less, to need an extra run-time element. Under the hood, the `async` keyword does nothing but change the syntax rules for the inner function body, and `await` is identical to `yield from`. Generators and (old style) coroutines I do understand. Using this knowledge, we can set a rule:

> Always instantiate `asyncio` related objects from within an `async` coroutine. The best way to achieve this is by writing a `main` function and instantiate objects within `main`.
>
> ~~~ {.python}
> async def main():
>     # do everything here
>
> asyncio.run(main())
> ~~~

Let's have a counter example: given a `mountain` of work that needs to pass through the `compute` coroutine. Suppose some of these computations overlap, and we need a `Lock` to synchronize. One might do

``` {.python}
@dataclass
class Work:
    args: Any
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    result: Any = None

all_my_work = [compute(Work(w)) for w in mountain]
asyncio.run(asyncio.gather(*all_my_work))
```

This will result in an error, even though the code looks fine on the surface. The problem is that `asyncio.run` initiates a new loop-manager. Meanwhile the `Lock` objects have been initialized without knowledge of the loop-manager, and they have no way to hook in. To fix this, write:

``` {.python}
async def main():
    all_my_work = [compute(Work(w)) for w in mountain]
    await asyncio.gather(*all_my_work)

asyncio.run(main())
```

These kind of quirks are not so well documented.

## Caching a test
We won't be too generic in implementing this. We assume the following decorator is used on a single method in a class that has the `_lock` and `_done` fields defined. This decorator then makes sure that the method is only ever executed once.

``` {.python #async-cache}
def async_cache(f):
    async def g(self, *args, **kwargs):
        async with self._lock:
            if self._done:
                return self._result
            self._result = await f(self, *args, **kwargs)
            self._done = True
            return self._result
    return g
```

Now we can apply the decorator to the `run` method in `VersionTest`.

``` {.python #version-test-run}
_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
_done: bool = False

@async_cache
async def run(self, recurse):
    for dep in self.depends:
        if not await recurse(dep):
            return Result(self, False,
                          failure_text=f"Failed dependency: {dep}")

    col1 = f"{self.name} {self.require}"
    proc = await asyncio.create_subprocess_shell(
        self.get_version,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE)
    (stdout, stderr) = await proc.communicate()
    if proc.returncode != 0:
        print(f"{col1:25}: not found")
        return Result(
            self,
            success=False,
            failure_text=f"{stderr.decode().strip()}")
    try:
        if self.pattern is not None:
            m = re.match(self.pattern, stdout.decode())
            out, _ = parse_version(m.group(1).strip())
        else:
            out, _ = parse_version(stdout.decode().strip())
    except ConfigError as e:
        return Result(self, False, failure_text=str(e))

    if self.require(out):
        print(f"{col1:25}: {str(out):10} Ok")
        return Result(self, True)
    else:
        print(f"{col1:25}: {str(out):10} Fail")
        return Result(self, False, failure_text="Too old.",
                      found_version=out)
```

## Reading the configuration

``` {.python #helper-functions}
def read_config(name: str, config: Mapping[str, str], templates):
    if "template" in config:
        _config = {}
        for k, v in templates[config["template"]].items():
            if isinstance(v, str):
                _config[k] = v.format(name=name)
            else:
                _config[k] = v
        _config.update(config)
    else:
        _config = dict(config)

    _deps = map(str.strip, _config.get("depends", "").split(","))
    deps = list(filter(lambda x: x != "", _deps))

    assert "require" in _config, "Every item needs a `require` field"
    assert "get_version" in _config, "Every item needs a `get_version` field"

    require, _ = parse_version_constraint(_config["require"])

    return VersionTest(
        name=name,
        require=require,
        get_version=_config["get_version"],
        # platform=_config.get("platform", None),
        pattern=_config.get("pattern", None),
        suggestion_text=_config.get("suggestion_text", None),
        suggestion=_config.get("suggestion", None),
        depends=deps,
        template=_config.get("template", None))
```

## Indenting output
To indent output in a context manager.

``` {.python #imports}
from contextlib import contextmanager, redirect_stdout
import textwrap
```

``` {.python #helper-functions}
@contextmanager
def indent(prefix: str):
    f = io.StringIO()
    with redirect_stdout(f):
        yield
    output = f.getvalue()
    print(textwrap.indent(output, prefix), end="")
```

## Main internal

``` {.python #main}
config = configparser.ConfigParser()
config.read("dependencies.ini")

templates = {
    name[9:]: config[name]
    for name in config if name.startswith("template:")
}

try:
    tests = {
        name: read_config(name, config[name], templates)
        for name in config if ":" not in name and name != "DEFAULT"
    }
except (AssertionError, ConfigError) as e:
    print("Configuration error:", e)
    sys.exit(1)

async def test_version(name: str):
    assert name in tests, f"unknown dependency {name}"
    x = await tests[name].run(test_version)
    return x

result = await asyncio.gather(*(test_version(k) for k in tests))
if all(r.success for r in result):
    print("Success")
    sys.exit(0)
else:
    print("Failure")
    with indent("  |  "):
        for r in (r for r in result if not r.success):
            if r.failure_text:
                print(f"{r.test.name}: {r.failure_text}")
            if r.found_version:
                print(f"    found version {r.found_version}")
    sys.exit(1)
```


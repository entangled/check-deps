# ~\~ language=Python filename=check-deps.py
# ~\~ begin <<lit/index.md|check-deps.py>>[0]
from __future__ import annotations

import sys
import io
import configparser
import asyncio
import re

# ~\~ begin <<lit/index.md|imports>>[0]
from dataclasses import dataclass, field
from typing import Optional, List, Mapping, Tuple, Callable, TypeVar
# ~\~ end
# ~\~ begin <<lit/index.md|imports>>[1]
from enum import Enum
# ~\~ end
# ~\~ begin <<lit/index.md|imports>>[2]
from contextlib import contextmanager, redirect_stdout
import textwrap
# ~\~ end
# ~\~ begin <<lit/index.md|async-cache>>[0]
def async_cache(f):
    async def g(self, *args, **kwargs):
        async with self._lock:
            if self._done:
                return self._result
            self._result = await f(self, *args, **kwargs)
            self._done = True
            return self._result
    return g
# ~\~ end
# ~\~ begin <<lit/index.md|types>>[0]
class ConfigError(Exception):
    pass

class ParserError(Exception):
    pass
# ~\~ end
# ~\~ begin <<lit/index.md|types>>[1]
@dataclass
class Version:
    number: Tuple[int, ...]
    extra: Optional[str]

    # ~\~ begin <<lit/index.md|version-methods>>[0]
    def _less_than(self, other, when_equal):
        for n, m in zip(self.number, other.number):
            if n < m:
                return True
            elif n > m:
                return False
        return when_equal
    # ~\~ end
    # ~\~ begin <<lit/index.md|version-methods>>[1]
    def __lt__(self, other):
        return self._less_than(other, when_equal=False)

    def __gt__(self, other):
        return other._less_than(self, when_equal=False)

    def __le__(self, other):
        return self._less_than(other, when_equal=True)

    def __ge__(self, other):
        return other._less_than(self, when_equal=True)
    # ~\~ end
    # ~\~ begin <<lit/index.md|version-methods>>[2]
    def __eq__(self, other):
        for n, m in zip(self.number, other.number):
            if n != m:
                return False
            return True

    def __ne__(self, other):
        return not self == other
    # ~\~ end
    # ~\~ begin <<lit/index.md|version-methods>>[3]
    def __str__(self):
        return ".".join(map(str, self.number)) + (self.extra or "")
    # ~\~ end
# ~\~ end
# ~\~ begin <<lit/index.md|types>>[2]
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
# ~\~ end
# ~\~ begin <<lit/index.md|types>>[3]
@dataclass
class VersionConstraint:
    version: Version
    relation: Relation

    def __call__(self, other: Version) -> bool:
        method = f"__{self.relation.name}__".lower()
        return getattr(other, method)(self.version)

    def __str__(self):
        return f"{self.relation}{self.version}"
# ~\~ end
# ~\~ begin <<lit/index.md|types>>[4]
@dataclass
class VersionTest:
    # ~\~ begin <<lit/index.md|version-test-fields>>[0]
    name: str
    require: VersionConstraint
    get_version: str
    # ~\~ end
    # ~\~ begin <<lit/index.md|version-test-fields>>[1]
    pattern: Optional[str] = None
    # ~\~ end
    # ~\~ begin <<lit/index.md|version-test-fields>>[2]
    suggestion_text: Optional[str] = None
    suggestion: Optional[str] = None
    # ~\~ end
    # ~\~ begin <<lit/index.md|version-test-fields>>[3]
    depends: List[str] = field(default_factory=list)
    # ~\~ end
    # ~\~ begin <<lit/index.md|version-test-fields>>[4]
    template: Optional[str] = None
    # ~\~ end
    # ~\~ begin <<lit/index.md|version-test-run>>[0]
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
    # ~\~ end
# ~\~ end
# ~\~ begin <<lit/index.md|types>>[5]
@dataclass
class Result:
    test: VersionTest
    success: bool
    failure_text: Optional[str] = None
    found_version: Optional[Version] = None
# ~\~ end
# ~\~ begin <<lit/index.md|types>>[6]
T = TypeVar("T")
# ~\~ end
# ~\~ begin <<lit/index.md|parsers>>[0]
def split_at(split_chars: str, x: str) -> Tuple[str, str]:
    a = x.split(split_chars, maxsplit=1)
    if len(a) == 2:
        return a[0], a[1]
    else:
        return a[0], ""
# ~\~ end
# ~\~ begin <<lit/index.md|parsers>>[1]
def parse_split_f(split_chars: str, f: Callable[[str], T], x: str) \
        -> Tuple[T, str]:
    item, x = split_at(split_chars, x)
    val = f(item)
    return val, x
# ~\~ end
# ~\~ begin <<lit/index.md|parsers>>[2]
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
# ~\~ end
# ~\~ begin <<lit/index.md|parsers>>[3]
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
# ~\~ end
# ~\~ begin <<lit/index.md|parsers>>[4]
def parse_version_constraint(x: str) -> Tuple[VersionConstraint, str]:
    relation, x = parse_relation(x)
    version, x = parse_version(x)
    return VersionConstraint(version, relation), x
# ~\~ end
# ~\~ begin <<lit/index.md|helper-functions>>[0]
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
# ~\~ end
# ~\~ begin <<lit/index.md|helper-functions>>[1]
@contextmanager
def indent(prefix: str):
    f = io.StringIO()
    with redirect_stdout(f):
        yield
    output = f.getvalue()
    print(textwrap.indent(output, prefix), end="")
# ~\~ end

async def main():
    # ~\~ begin <<lit/index.md|main>>[0]
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
    # ~\~ end

asyncio.run(main())
# ~\~ end

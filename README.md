---
title: Dependecy checker in Python
subtitle: adventures with asyncio
author: Johan Hidding
---

[![Entangled badge](https://img.shields.io/badge/entangled-Use%20the%20source!-%2300aeff)](https://entangled.github.io/)

This is a literate program. The complete source code to this program is contained in the text of this document. You can view a web-friendly version at [entangled.github.io/check-deps](https://entangled.github.io/check-deps).

It struck me that, to get an [Entangled/Bootstrap project](https://entangled.github.io/tutorial.html) to work, you need quite a few things installed. I wanted to have a script that checks all the dependencies and then reports back to the user. This script should follow these guidelines:

- require very little to run: It is beyond my Bash skills to implement this in pure Bash, so instead I settled on vanilla **Python**.
- be configurable: Python has a builtin parser for `ini` files.
- run efficiently: This is my chance to get my hands dirty with `asyncio`.

# Configuration
The idea is to have a `dependencies.ini` file with entries that look as follows:

``` {.ini file=dependencies.ini}
[python]
require = >=3.8
get_version = python3 --version
pattern = Python (.*)
```

The script will then run `python3 --version` and match the output to the regular expression `Python (.*)`, from which a version number is extracted. This version is then compared to the requirement `>=3.8`.

Some version constraints may depend on other software to be present.

``` {.ini file=dependencies.ini}
[pip]
require = >=19
get_version = pip --version
pattern = pip ([0-9.]*)
depends = python
```

If we have many Python packages to check for, it may be easier to do so through a template

``` {.ini file=dependencies.ini}
[template:pip]
get_version = pip show {name} | grep "Version:"
pattern = Version: (.*)
suggestion_text = This is a Python package that can be installed through pip.
suggestion = pip install {name}
depends = python,pip
```

For instance, if we want to check the version of Numpy:

``` {.ini file=dependencies.ini}
[numpy]
template = pip
require = >=1.0
```

When any dependency is missing, the script should print a friendly message informing the user how to proceed.

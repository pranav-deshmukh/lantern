"""Sample module with intentional style issues for the reviewer demo."""

import os
import sys


def load_config(path):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read()
    except:
        return ""


def process(values, cache=[]):
    total = 0
    for value in values:
        cache.append(value)
        total += value
    unused = total
    return sum(cache)


if __name__ == "__main__":
    data = process([1, 2, 3])
    print(data)

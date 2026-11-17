import pytest

from render.texture_stream import (
    required_mip,
    merge_io_requests,
    select_evictions,
    total_budget,
    fallback_mip
)


def test_mip_1024_to_512():
    assert required_mip(1024, 512) == 1

def test_mip_1024_to_256():
    assert required_mip(1024, 256) == 2

def test_mip_1024_to_1():
    assert required_mip(1024, 1) == 10

def test_mip_target_larger():
    assert required_mip(256, 1024) == 0

def test_merge_contiguous_mips():
    assert merge_io_requests([{'texture': 'a', 'mip': 0}, {'texture': 'a', 'mip': 1}]) == [{'texture': 'a', 'mips': (0, 1), 'priority': 0}]

def test_merge_non_contiguous():
    assert merge_io_requests([{'texture': 'a', 'mip': 0}, {'texture': 'a', 'mip': 2}]) == [{'texture': 'a', 'mips': (0, 0), 'priority': 0}, {'texture': 'a', 'mips': (2, 2), 'priority': 0}]

def test_merge_different_textures():
    assert merge_io_requests([{'texture': 'a', 'mip': 0}, {'texture': 'b', 'mip': 0}]) == [{'texture': 'a', 'mips': (0, 0), 'priority': 0}, {'texture': 'b', 'mips': (0, 0), 'priority': 0}]

def test_merge_priority_order():
    assert merge_io_requests([{'texture': 'a', 'mip': 0, 'priority': 1}, {'texture': 'b', 'mip': 0, 'priority': 5}])[0]['texture'] == 'b'

def test_evict_unreferenced():
    assert select_evictions(['a', 'b'], {'a': 0, 'b': 0}, 100, {'a': 60, 'b': 60}) == ['a']

def test_protect_referenced():
    assert select_evictions(['a', 'b'], {'a': 1, 'b': 0}, 60, {'a': 100, 'b': 60}) == ['b']

def test_no_eviction_under_budget():
    assert select_evictions(['a', 'b'], {'a': 1, 'b': 1}, 200, {'a': 60, 'b': 60}) == []

def test_budget_with_overhead():
    assert total_budget(100, 20, 10) == 130

def test_fallback_exact():
    assert fallback_mip(2, [0, 1, 2, 3]) == 2

def test_fallback_lower():
    assert fallback_mip(5, [0, 1, 2]) == 2

def test_fallback_empty():
    assert fallback_mip(5, []) == 0

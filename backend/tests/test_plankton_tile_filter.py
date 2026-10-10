# SPDX-License-Identifier: AGPL-3.0-or-later
# Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com
"""Tile filters: fixed vocabulary, one canonical cache key per combination (no DB)."""
import itertools

import pytest

from schema.plankton import GROUPS
from services import plankton_tiles as tiles


def test_no_filter_and_the_full_vocabulary_share_one_short_key():
    assert tiles.parse_filter().key == "all"
    full = tiles.parse_filter(g="dinoflagellates,coccolithophores,diatoms,euphausiacea,copepoda",
                              d="2020,2010,2000,1990,1980,1970,1960,1950,1940,-1", b="3,2,1,0", e="1")
    assert full == tiles.DEFAULT_FILTER and full.key == "all"
    assert tiles.parse_filter(g="", d="", b="", e="").key == "all"


def test_order_spaces_and_duplicates_do_not_change_the_key():
    a = tiles.parse_filter(g="diatoms,copepoda", d="2010,1990", b="0")
    b = tiles.parse_filter(g=" copepoda ,diatoms,diatoms", d="1990,2010,1990", b="0,0")
    assert a == b and a.key == b.key == "g05-d140-b1-e1"


def test_edna_off_is_part_of_the_key():
    assert tiles.parse_filter(e="0").key == "g1f-d3ff-bf-e0"


@pytest.mark.parametrize("kw", [
    {"g": "jellyfish"}, {"g": "Copepoda"}, {"g": "copepoda,"}, {"d": "1930"}, {"d": "2030"}, {"d": "195O"},
    {"d": "1955"}, {"b": "4"}, {"b": "-1"}, {"b": "x"}, {"e": "2"}, {"e": "true"},
    # int() would accept these and silently alias them to a valid value
    {"d": "1_950"}, {"d": "+1950"}, {"b": "+1"}, {"b": "٣"},
])
def test_a_value_outside_the_vocabulary_is_refused(kw):
    with pytest.raises(ValueError):
        tiles.parse_filter(**kw)


def test_every_key_is_path_safe():
    for pair in itertools.combinations(GROUPS, 2):
        k = tiles.parse_filter(g=",".join(pair), d="-1", b="3", e="0").key
        assert tiles.KEY_RE.fullmatch(k), k


def test_sql_args_follow_the_vocabulary_order():
    assert tiles.parse_filter(g="diatoms,copepoda", d="2010,-1", b="3", e="0").sql_args() == \
        [["copepoda", "diatoms"], [-1, 2010], [3], False]

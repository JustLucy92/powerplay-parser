"""Checks the BGS States cell text built from EDSM faction/station data."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from bgs_states import format_bgs_states


def faction(name, active=(), pending=(), recovering=()):
    return {'name': name,
            'activeStates': [{'state': s} for s in active],
            'pendingStates': [{'state': s} for s in pending],
            'recoveringStates': [{'state': s} for s in recovering]}


def system(controller, *factions):
    return {'controllingFaction': {'name': controller}, 'factions': list(factions)}


def station(faction_name, type_='Coriolis Starport', economy='Industrial', market=True, second=None):
    return {'type': type_, 'economy': economy, 'secondEconomy': second, 'haveMarket': market,
            'controllingFaction': {'name': faction_name}}


def test_first_slot_and_pending():
    data = system('A', faction('A', active=['Boom'], pending=['Expansion'], recovering=['Infrastructure Failure']))
    assert format_bgs_states(data) == 'Boom | Pending: Expansion'


def test_non_first_slot_states_go_under_other():
    data = system('A', faction('A', active=['Election', 'Civil unrest']))
    assert format_bgs_states(data) == 'None | Other: Election, Civil unrest'


def test_civil_liberty_is_first_slot():
    data = system('A', faction('A', active=['Civil liberty', 'Boom', 'Expansion']))
    assert format_bgs_states(data) == 'Civil Liberty, Boom, Expansion'


def test_recovering_states_are_ignored():
    data = system('A', faction('A', recovering=['Public Holiday']))
    assert format_bgs_states(data) == 'None'


def test_secondary_faction_ignored_without_a_good_port():
    data = system('A', faction('A', active=['Expansion']), faction('B', active=['Boom']))
    assert format_bgs_states(data) == 'Expansion'
    assert format_bgs_states(data, [station('B', type_='Outpost')]) == 'Expansion'
    assert format_bgs_states(data, [station('B', economy='Agriculture')]) == 'Expansion'
    assert format_bgs_states(data, [station('B', market=False)]) == 'Expansion'


def test_secondary_faction_shown_when_it_owns_a_good_port():
    data = system('A', faction('A', active=['Expansion']), faction('B', active=['Boom', 'Election']))
    for economy in ('Industrial', 'Refinery', 'High Tech', 'Tourism'):
        assert format_bgs_states(data, [station('B', economy=economy)]) == 'Expansion | 2nd: Boom'
    assert format_bgs_states(data, [station('B', economy='Agriculture', second='Tourism')]) == 'Expansion | 2nd: Boom'


def test_controlling_factions_own_port_is_not_repeated():
    data = system('A', faction('A', active=['Boom']))
    assert format_bgs_states(data, [station('A')]) == 'Boom'


def test_nothing_to_say_returns_none():
    assert format_bgs_states([]) is None
    assert format_bgs_states({}) is None
    assert format_bgs_states({'controllingFaction': {'name': 'A'}, 'factions': []}) is None

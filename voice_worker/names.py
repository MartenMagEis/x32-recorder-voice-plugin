"""Recording-name pattern expansion, for "start" by voice - a port of x32-recorder's
frontend/src/utils/nameWildcards.js (built-ins {Datum} {Uhrzeit} {Wochentag} {Vorlage}, then
global and per-template custom wildcards). Keep the two in sync."""
import datetime

_WEEKDAYS_DE = ['Montag', 'Dienstag', 'Mittwoch', 'Donnerstag', 'Freitag', 'Samstag', 'Sonntag']


def expand_pattern(pattern, template_name='', custom_wildcards=(), global_wildcards=(), now=None):
    if not pattern:
        return ''
    now = now or datetime.datetime.now()
    builtins = {
        'Datum': now.strftime('%y-%m-%d'),
        'Uhrzeit': now.strftime('%H-%M'),
        'Wochentag': _WEEKDAYS_DE[now.weekday()],
        'Vorlage': template_name or '',
    }
    result = pattern
    for token, value in builtins.items():
        result = result.replace('{' + token + '}', value)
    # Same order as the frontend: global wildcards are merged in front of the template's own.
    for wc in list(global_wildcards) + list(custom_wildcards):
        if wc and wc.get('token'):
            result = result.replace('{' + wc['token'] + '}', wc.get('value') or '')
    return result

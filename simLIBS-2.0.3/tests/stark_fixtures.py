"""Synthetic provider responses for equation tests; never production coefficients."""
from pathlib import Path

from simLIBS.nist_self_absorption import parse_atomic_payload


HTML = (Path(__file__).parent / 'fixtures' / 'nist_mg_280_290.html').read_text(encoding='utf-8')
TRANSITIONS = parse_atomic_payload(HTML)['transitions']
PARTIAL_WAVES = {TRANSITIONS[0]['wavelength_nm'], 285.29642}


def provider_response(records, *, supported=None, **kwargs):
    """Replace only the provider boundary, preserving actual NIST line metadata."""
    found, missing = {}, {}
    for index, row in enumerate(records):
        if supported is None or row['wavelength_nm'] in supported:
            found[index] = dict(
                row, stark_width_nm=.002, stark_reference_ne_cm3=1e16,
                stark_source='STARK-B synthetic test response only',
                stark_dataset_id='synthetic-test', stark_method='SCP',
            )
        else:
            missing[index] = dict(row, stark_width_nm=None, stark_missing_reason='no test provider data')
    return found, missing


def partial_provider(records, **kwargs):
    return provider_response(records, supported=PARTIAL_WAVES, **kwargs)


def missing_provider(records, **kwargs):
    return provider_response(records, supported=set(), **kwargs)

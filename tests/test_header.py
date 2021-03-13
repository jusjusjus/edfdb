from os.path import join, exists, dirname

import pytest

from edfdb import EDF
from edfdb.header import ChannelHeader, AnnotChannelHeader

@pytest.fixture
def examples_dir():
    return join(dirname(__file__), '..', 'examples')

@pytest.fixture
def edffile(examples_dir):
    filename = join(examples_dir, 'sample.edf')
    assert exists(filename), 'File %s not existent'%filename
    return EDF.read_file(filename, keep_open=False)

@pytest.fixture
def edfpfile(examples_dir):
    filename = join(examples_dir, 'edfp-sample.edf')
    assert exists(filename), 'File %s not existent'%filename
    return EDF.read_file(filename, keep_open=False)

@pytest.fixture
def channelheader(edffile):
    return edffile.channels[0]

@pytest.fixture
def annotchannelheader(edfpfile):
    return edfpfile.channel_by_label["EDF Annotations"]

@pytest.mark.parametrize("field,expected", [
    ('version',         '0'),
    ('patient_id',      'brux2'),
    ('recording_id',    ''),
    ('startdate',       '04.02.02'),
    ('starttime',       '22.07.23'),
    ('num_header_bytes', 1536),
    ('reserved',        ''),
    ('num_records',     100),
    ('record_duration', 1.0),
    ('num_channels',    5),
])
def test_edfheader(field, expected, edffile):
    """Checks if header values at `field` equal `expected`."""
    val = edffile.__getattribute__(field)
    assert val == expected, "expected `%s` `%s` [%s]"%(field, expected, val)


@pytest.mark.parametrize("field,expected", [
    ('version',         '0'),
    ('patient_id',      'VT-001 X X X'),
    ('recording_id',    'Startdate 27-AUG-2018 X X EGI'),
    ('startdate',       '27.08.18'),
    ('starttime',       '11.25.11'),
    ('num_header_bytes', 1536),
    ('reserved',        'EDF+C'),
    ('num_records',     8192),
    ('record_duration', 0.1),
    ('num_channels',    5),
])
def test_edfpheader(field, expected, edfpfile):
    """Checks if header values at `field` equal `expected`."""
    val = edfpfile.__getattribute__(field)
    assert val == expected, "expected `%s` `%s` [%s]"%(field, expected, val)

@pytest.mark.parametrize("field,expected", [
    ('label',                   'Fp2-F4'),
    ('channel_type',            'EEG Fp2-F4'),
    ('physical_dimension',      'uV'),
    ('physical_minimum',        -62.5),
    ('physical_maximum',        62.5),
    ('digital_minimum',         -2048),
    ('digital_maximum',         2047),
    ('prefiltering',            'LP:30.00Hz HP:0.30Hz NOTCH:50'),
    ('num_samples_per_record',  256),
    ('reserved',                ''),
])
def test_channelheader(field, expected, channelheader):
    """Checks if header values at `field` equal `expected`."""
    val = channelheader.__getattribute__(field)
    assert val == expected, "expected `%s` `%s` [%s]"%(field, expected, val)

@pytest.mark.parametrize("field,expected", [
    ('label',                   'EDF Annotations'),
    ('num_samples_per_record',  23),
    ('record_duration',         0.1),
    ('num_records',             8192),
    ('reserved',                '')
])
def test_annotchannelheader(field, expected, annotchannelheader):
    """Checks if header values at `field` equal `expected`."""
    val = annotchannelheader.__getattribute__(field)
    assert val == expected, "expected `%s` `%s` [%s]"%(field, expected, val)

def test_get_physical_samples(edfpfile):
    t, dt = 0.001, 1.0
    x = edfpfile.get_physical_samples(t, dt)
    assert all(c.label in x for c in edfpfile.channels), "Not all channels read."
    for channel in edfpfile.channels:
        if isinstance(channel, AnnotChannelHeader):
            assert len(x[channel.label]) == 10, channel.label
        elif isinstance(channel, ChannelHeader):
            num_samples = int(dt*channel.sampling_rate)
            assert x[channel.label].size == num_samples, channel.label

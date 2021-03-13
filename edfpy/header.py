
import logging
import numpy as np
from os import SEEK_SET
from struct import Struct
from .notation import Label, convert_units, AnnotationsLabel
from datetime import datetime
from collections import namedtuple


default_dtype = np.float32


class Header:

    logger = logging.getLogger(name='Header')

    _fields = [
        ('version', str, 8),
        ('patient_id', str, 80),
        ('recording_id', str, 80),
        ('startdate', str, 8),
        ('starttime', str, 8),
        ('num_header_bytes', int, 8),
        ('reserved', str, 44),
        ('num_records', int, 8),
        ('record_duration', float, 8),
        ('num_channels', int, 4)
    ]

    # format_str = ''.join(str(size) + 's'
    #                      for _, _, size in fields_rec.bytesize)

    _format_str = '8s80s80s8s8s8s44s8s8s4s'
    # _num_header_bytes = sum(c for _,_,c in _fields)
    _num_header_bytes = 256

    def __init__(self, *args, **kwargs):
        self.datetime_changed = True
        for k, v in kwargs.items():
            try:
                # Accessing `prop.setter` through class property
                getattr(type(self), k).fset(self, v)
            except AttributeError:
                setattr(self, k, v)

    def _build_channel_differences(self):
        channels = list(self.channel_by_label.values())
        for index, left in enumerate(channels):
            for right in channels[index + 1:]:
                try:
                    lr = left-right
                    self.channel_by_label[lr.label] = lr
                    rl = right-left
                    self.channel_by_label[rl.label] = rl
                except (AssertionError, TypeError) as e:
                    self.logger.info(
                        "In Header.build_channel_differences: %s" % e)

    def add_synonym(self, synonym, label):
        """add `synonym` for `label` to address a channel"""
        self.channel_by_label[synonym] = self.channel_by_label[label]
        self.sampling_rate_by_label[synonym] = \
            self.sampling_rate_by_label[label]

    def build_channel_differences(self, depth=1):
        for _ in range(depth):
            self._build_channel_differences()

    @property
    def startdate(self):
        """Local start date of the recording"""
        return self._startdate

    @startdate.setter
    def startdate(self, v):
        self.datetime_changed = True
        self._startdate = self.normalize(str, v)

    @property
    def starttime(self):
        """Local start time of the recording"""
        return self._starttime

    @starttime.setter
    def starttime(self, v):
        self.datetime_changed = True
        self._starttime = self.normalize(str, v)

    @property
    def version(self):
        return self._version

    @version.setter
    def version(self, v):
        self._version = self.normalize(str, v)

    @property
    def patient_id(self):
        return self._patient_id

    @patient_id.setter
    def patient_id(self, v):
        self._patient_id = self.normalize(str, v)

    @property
    def recording_id(self):
        return self._recording_id

    @recording_id.setter
    def recording_id(self, v):
        self._recording_id = self.normalize(str, v)

    @property
    def reserved(self):
        return self._reserved

    @reserved.setter
    def reserved(self, v):
        self._reserved = self.normalize(str, v)

    @staticmethod
    def normalize(typ, v):
        if isinstance(v, str):
            v = v.strip('\x00').strip(' ')
        elif isinstance(v, bytes):
            v = v.strip(b'\x00')
        else:
            AttributeError("Unknown type")
        if typ is str:
            if isinstance(v, bytes):
                try:
                    v = str(v, 'ascii')
                except BaseException:
                    v = str(v, 'latin1')
        else:
            v = typ(v)
        return v

    @property
    def startdatetime(self):
        if self.datetime_changed:
            try:
                self._startdatetime = datetime.strptime(
                    self.startdate + "-" + self.starttime, "%d.%m.%y-%H.%M.%S"
                )
            except BaseException:  # sometimes the day and month are switched
                self.logger.info("Time format seems to be MON.DAY.YEAR")
                self._startdatetime = datetime.strptime(
                    self.startdate + "-" + self.starttime, "%m.%d.%y-%H.%M.%S"
                )
            self.datetime_changed = False
        return self._startdatetime

    def _read_channels(self, fo):
        offset = 256
        nc = self.num_channels
        channels = [ChannelHeader(i) for i in range(nc)]
        for field, typ, size in ChannelHeader._fields:
            num_bytes = size * nc
            _format_str = (str(size) + "s") * nc
            data = fo.read(num_bytes)
            values = Struct(_format_str).unpack(data)
            normalized = (self.normalize(typ, v) for v in values)
            for c, v in zip(channels, normalized):
                try:
                    getattr(type(c), field).fset(c, v)
                except AttributeError:
                    setattr(c, field, v)
            offset += num_bytes
        assert offset == self.num_header_bytes, f" \
            invalid header of size {offset} [{self.num_header_bytes}]"

        self.channels = [c.transform_from_label() for c in channels]

        # Add some redundance for fast access
        for key in ('record_duration', 'num_records'):
            att = getattr(self, key)
            for channel in self.channels:
                setattr(channel, key, att)

        self.samples_by_channel = np.array([
            c.num_samples for c in self.channels
        ])
        self.samples_per_record_by_channel = np.array([
            c.num_samples_per_record for c in self.channels
        ])
        self.sampling_rates = np.array([
            c.sampling_rate for c in self.channels
        ])
        self.sampling_rate_by_label = {
            c.label: c.sampling_rate
            for c in self.channels
        }
        self.channel_by_label = {c.label : c for c in self.channels}

    def set_blob(self, fo):
        pass

    @classmethod
    def read_file(cls, filename, keep_open=True):
        fo = cls.open_if_string(filename, 'rb')
        fo.seek(0, SEEK_SET)

        data = fo.read(256)
        values = Struct(cls._format_str).unpack(data)
        values = {
            name: cls.normalize(typ, value)
            for value, (name, typ, num_bytes) in zip(values, cls._fields)
        }

        instance = cls(**values)
        instance._read_channels(fo)
        if keep_open:
            instance.set_blob(fo)
        else:
            fo.close()
            instance.set_blob(filename)
        return instance

    def as_bytes(self, key, num_bytes=None):
        """Converts `str` representation of `self.key` to `bytes` instance"""
        fstring = "{:<%i}" % num_bytes if num_bytes else "{}"
        return bytes(fstring.format(getattr(self, key)), 'latin1')

    @property
    def num_header_bytes(self):
        return self._num_header_bytes + \
               self.num_channels * ChannelHeader._num_header_bytes

    @num_header_bytes.setter
    def num_header_bytes(self, _):
        pass

    def to_bytes(self, channels=None):
        if channels is not None:
            channels = sorted([self.channel_by_label[c] for c in channels],
                              key=lambda c: c.specifier)
        else:
            channels = self.channels
        # Temporarily change `self.num_channels`
        tmp_num_ch = self.num_channels
        self.num_channels = len(channels)
        # Main header
        ret = [
            self.as_bytes(key, num_bytes)
            for key, _, num_bytes in self._fields
        ]
        # Channel headers
        channel_format_str = ''
        for key, _, size in ChannelHeader._fields:
            channel_format_str += (str(size)+'s')*self.num_channels
            ret += [
                channel.as_bytes(key, num_bytes=size)
                for channel in channels
            ]
        # Change `self.num_channels` back to original
        self.num_channels = tmp_num_ch
        return ret, self._format_str + channel_format_str

    def write_file(self, filename, close=True, channels=None):
        fo = self.open_if_string(filename, 'wb')
        blob, format_str = self.to_bytes(channels=channels)
        packed = Struct(format_str).pack(*blob)
        fo.seek(0, SEEK_SET)
        fo.write(packed)
        if isinstance(filename, str) and close:
            fo.close()
        return fo

    @staticmethod
    def open_if_string(f, mode):
        if isinstance(f, str):
            fo = open(f, mode)
        else:
            fo = f
        for m in ('read', 'seek'):
            assert hasattr(fo, m), "Missing property in \
                    file ['{}', '{}', '{}']".format(m, f, fo)
        return fo

    def to_string_list(self):
        return [
            "{}: {}".format(key, val)
            for key, val in self.__dict__.items()
        ]

    def __str__(self):
        return '\n'.join(self.to_string_list())

    def _repr_html_(self):
        return ''.join(['<p>%s</p>' % s for s in self.to_string_list()])


class ChannelHeader:

    logger = logging.getLogger(name='ChannelHeader')

    _fields = [
        ('label', str, 16),
        ('channel_type', str, 80),
        ('physical_dimension', str, 8),
        ('physical_minimum', float, 8),
        ('physical_maximum', float, 8),
        ('digital_minimum', int, 8),
        ('digital_maximum', int, 8),
        ('prefiltering', str, 80),
        ('num_samples_per_record', int, 8),
        ('reserved', str, 32)
    ]

    # _num_channel_header_bytes = sum(c for _,_,c in _fields)
    _num_header_bytes = 256

    def __init__(self, specifier):
        """
        Arguments:
            specifier (optional) : specifies the channel construction,
            typically the reference index in a data blob.
        """
        self.specifier = specifier
        self.unit_scale = 1.0

    @property
    def label(self):
        return self._label

    @label.setter
    def label(self, v):
        self._label = v if isinstance(v, Label) else Label(v.strip())

    def transform_from_label(self):
        if isinstance(self.label, AnnotationsLabel):
            return AnnotChannelHeader.from_channelheader(self)
        return self

    @property
    def sampling_rate(self):
        try:
            return self._sampling_rate
        except AttributeError:
            self._sampling_rate = self.num_samples_per_record / self.record_duration
            return self._sampling_rate
    
    def digital2physical(self, data, dtype=default_dtype, specifier=None):
        s = self.specifier if specifier is None else specifier
        assert s is not None, "channel index for edf record column missing"
        return dtype(self.unit_scale)*dtype(self.scale)*(data[s].astype(dtype) + dtype(self.offset))

    @property
    def num_samples(self):
        try:
            return self._num_samples
        except AttributeError:
            self._num_samples = self.num_samples_per_record * self.num_records
            return self._num_samples

    @property
    def channel_type(self):
        return self._channel_type

    @channel_type.setter
    def channel_type(self, v):
        self._channel_type = v.strip()

    @property
    def type(self):
        """channel type from label"""
        return self.label.type

    @property
    def physical_dimension(self):
        return self._physical_dimension

    @physical_dimension.setter
    def physical_dimension(self, v):
        self._physical_dimension = v.strip()

    @property
    def output_physical_dimension(self):
        try:
            return self._output_physical_dimension
        except AttributeError:
            return self.physical_dimension

    @output_physical_dimension.setter
    def output_physical_dimension(self, v):
        self._output_physical_dimension = v
        self.unit_scale = convert_units(
            self.physical_dimension, self._output_physical_dimension)

    @property
    def prefiltering(self):
        return self._prefiltering

    @prefiltering.setter
    def prefiltering(self, v):
        self._prefiltering = v.strip()

    @property
    def reserved(self):
        return self._reserved

    @reserved.setter
    def reserved(self, v):
        self._reserved = v.strip()

    @property
    def scale(self):
        try:
            return self._scale
        except AttributeError:
            self._scale  = (self.physical_maximum - self.physical_minimum) / \
                           (self.digital_maximum  - self.digital_minimum)
            return self._scale
    
    @property
    def offset(self):
        try:
            return self._offset
        except AttributeError:
            self._offset = self.physical_maximum / self.scale - self.digital_maximum
            return self._offset

    def digital2physical(self, data, dtype=default_dtype, specifier=None):
        s = self.specifier if specifier is None else specifier
        assert s is not None, "channel index for edf record column missing"
        return dtype(self.unit_scale) * dtype(self.scale) \
            * (data[s].astype(dtype) + dtype(self.offset))

    def as_bytes(self, key, num_bytes=None):
        """Converts `str` representation of self.key to `bytes` instance"""
        fstring = "{:<%i}" % num_bytes if num_bytes else "{}"
        return bytes(fstring.format(getattr(self, key)), 'latin1')

    def to_bytes(self, key, typ=str):
        att = getattr(self, key)
        b = bytes(att, 'latin1') if typ is str else bytes(att)
        return b

    def to_string_list(self):
        return [
            "{}: {}".format(key, val)
            for key, val in self.__dict__.items()
        ]

    def __str__(self):
        return '\n'.join(self.to_string_list())

    def _repr_html_(self):
        return ''.join(['<p>%s</p>' % s for s in self.to_string_list()])

    def check_compatible(self, other):
        for prop in ('sampling_rate', 'output_physical_dimension'):
            assert getattr(self, prop) == getattr(other, prop), \
                "'%s' and '%s' differ in '%s'" % (
                    self.label, other.label, prop)

    def __sub__(self, other):
        return ChannelDifference(self, other)


class ChannelDifference:

    def __init__(self, left, right):
        left.check_compatible(right)
        self.left = left
        self.right = right
        self.label = left.label-right.label

    def check_compatible(self, other):
        """check compatibility of left and right

        note that compatibility is transitive. left vs right already checked in
        `__init__`.
        """
        self.left.check_compatible(other)

    @property
    def type(self):
        return self.label.type

    @property
    def sampling_rate(self):
        return self.left.sampling_rate

    @property
    def physical_dimension(self):
        return self.left.physical_dimension

    def digital2physical(self, *args, **kwargs):
        return self.left.digital2physical(*args, **kwargs) \
            - self.right.digital2physical(*args, **kwargs)

    def __sub__(self, other):
        return ChannelDifference(self, other)

    @property
    def output_physical_dimension(self):
        return self.left.output_physical_dimension

    @output_physical_dimension.setter
    def output_physical_dimension(self, v):
        self.left.output_physical_dimension = v
        self.right.output_physical_dimension = v


_Annotation = namedtuple('Annotation', 't dt label')

class Annotation(_Annotation):
    @classmethod
    def to_pandas(cls, annotations):
        """Given a list of `Annotation` returns a pd.DataFrame of these."""
        import pandas as pd
        if all(isinstance(a, cls) for a in annotations):
            annotations = cls(*zip(*annotations))
        return pd.DataFrame.from_items([
            (p, getattr(annotations, p))
            for p in ('t', 'dt', 'label')
        ])

class AnnotChannelHeader(ChannelHeader):

    logger = logging.getLogger(name='AnnotChannelHeader')

    @classmethod
    def from_channelheader(cls, header):
        ans = cls(header.specifier)
        for field in ('label', 'num_samples_per_record', 'reserved'):
            val = getattr(header, field)
            try:
                getattr(type(ans), field).fset(val)
            except:
                setattr(ans, field, val)
        return ans

    def __init__(self, specifier):
        """
        Arguments:
            specifier (optional) : specifies the channel construction,
            typically the reference index in a data blob.
        """
        self.specifier = specifier
        self.unit_scale = 1.0

    @property
    def label(self):
        return self._label

    @label.setter
    def label(self, v):
        self._label = v if isinstance(v, Label) else Label(v.strip())

    @property
    def sampling_rate(self):
        try:
            return self._sampling_rate
        except AttributeError:
            self._sampling_rate = self.num_samples_per_record / self.record_duration
            return self._sampling_rate

    @property
    def num_samples(self):
        try:
            return self._num_samples
        except AttributeError:
            self._num_samples = self.num_samples_per_record * self.num_records
            return self._num_samples

    @property
    def channel_type(self):
        return self._channel_type
    
    @channel_type.setter
    def channel_type(self, v):
        self._channel_type = v

    @property
    def type(self):
        """channel type from label"""
        return self.label.type

    @property
    def reserved(self):
        return self._reserved

    @reserved.setter
    def reserved(self, v):
        self._reserved = v

    _processor = {
        2: lambda x: None,
        3: lambda x: Annotation(float(x[0]), float(x[1]), x[2].decode('ascii'))
    }

    _dt_annot_sep = b'\x14'
    _t_dt_sep = b'\x15'
    @classmethod
    def _process_annot(cls, x):
        # x = b'+0.0\x14'
        # or
        # x = b'+17.448\x150.001\x14Resting Eyes Open'
        x = x.split(cls._dt_annot_sep)
        x = x[0].split(cls._t_dt_sep) + [x[-1]]
        x = cls._processor[len(x)](x)
        return x

    _annot_sep = b'\x14\x00'
    def digital2physical(self, data, dtype=default_dtype, specifier=None):
        """Convert int16 data stream to list of `Annotation` objects.
        
        (the method name is a bit of a misnomer.)
        """
        s = self.specifier if specifier is None else specifier
        assert s is not None, "channel index for edf record column missing"
        x = data[s].tobytes()
        # x = b'+0.0\x14\x14\x00+17.448\x150.001\x14Resting Eyes Open\x14\x00\x0..'
        x = x.split(self._annot_sep)
        # x = [b'+0.0\x14', b'+17.448\x150.001\x14Resting Eyes Open', b'\x00\x00\x0..', ..]
        return [a for a in map(self._process_annot, x) if a is not None]

    def as_bytes(self, key, num_bytes=None):
        """Converts the `str` representation of value `self.key` to a `bytes` instance."""
        fstring = "{:<%i}"%num_bytes if num_bytes else "{}"
        return bytes(fstring.format(getattr(self, key)), 'latin1')

    def to_bytes(self, key):
        att = getattr(self, key)
        b = bytes(att, 'latin1') if typ is str else bytes(att)
        return b

    def to_string_list(self):
        return [
            "{}: {}".format(key, val)
            for key, val in self.__dict__.items()
        ]

    def __str__(self):
        return '\n'.join(self.to_string_list())

    def _repr_html_(self):
        return ''.join(['<p>%s</p>'%s for s in self.to_string_list()])

    def check_compatible(self, other):
        raise TypeError("Annotations channel not compatible")

    def __sub__(self, other):
        raise NotImplementedError("Cannot subtract annotations channel.")

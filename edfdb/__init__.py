
import logging
import numpy as np
from os import SEEK_SET
from .header import Header, ChannelHeader


class EDF(Header):

    logger = logging.getLogger(name='EDF')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    @property
    def duration(self):
        """Total duration of the recording in seconds."""
        return self.record_duration * self.num_records

    def get_digital_samples(self, t0=0.0, dt=None):
        """Return digital samples from `t0` to `t0+dt`."""
        sr = self.sampling_rate_by_channel
        n = self.samples_per_record_by_channel
        if dt is None:
            dt = self.num_records*self.record_duration
        # start/stop samples per channel
        a = (t0*sr).astype(int)
        b = ((t0+dt)*sr).astype(int)
        # start/stop record enclosing (min(a), max(b))
        A = np.floor(a/n).astype(int).min()
        B = np.ceil(b/n).astype(int).max()
        # relative start/stop of data read
        a1 = a - A*n
        b1 = b - B*n # result is <= 0
        b1 = [None if b1_ == 0 else b1_ for b1_ in b1]
        # Read data and return result
        data = self.blob[A:B]
        return [d[l:r] for d, l, r in zip(data, a1, b1)]

    def get_physical_samples(self, t0=0.0, dt=None, channels=None):
        """Return physical samples from `t0` to `t0+dt`

        Arguments:
            t0 (float) : start time
            dt (float) : time difference to read out
            channels (list of strings, optional) : contains the list of
            channel labels that shall be returned (`None` returns all channels).

        Returns:`
            a dict by channel label of the numpy.arrays with the data.
        """
        if channels is None:
            channels = self.channels
        else:
            channels = [(l, self.channel_by_label[l]) for l in channels]
        data = self.get_digital_samples(t0, dt)
        return {
            l: c.digital2physical(data) for l, c in channels
        }

    def set_blob(self, fo):
        s = list(self.samples_per_record_by_channel)
        channel_locs = np.cumsum([0] + s).astype(int)
        samples_per_record = sum(s)
        self.blob = Blob(
            fo,
            self.num_records,
            samples_per_record,
            channel_locs,
            self.num_header_bytes
        )



class Blob:

    _bytes_per_sample = 2
    
    def __init__(self, file, records, samples_per_record, channel_locs, offset):
        self.file = file
        self.samples_per_record = samples_per_record
        self.records = records
        self.channel_locs = list(zip(channel_locs[:-1], channel_locs[1:]))
        self.offset = offset
        self.dtype = '<i%i'%self._bytes_per_sample

    def __getitem__(self, sl):
        """Return data contained in the records of `sl`.
        
        Returned data is a by-channel list of all datapoints
        contained in the sliced records.  Size may differ for each
        channel depending on the sampling rate.
        """
        assert sl.step is None, "We don't resample like that."
        n = self.samples_per_record
        N = self.records
        b = self._bytes_per_sample
        start = 0 if sl.start is None else sl.start
        stop  = N if sl.stop  is None else sl.stop
        ds = stop-start
        offset = int(b*start*n + self.offset)
        readsize = int(b*ds*n)
        shp = (ds, n)
        self.file.seek(offset, SEEK_SET)
        data = np.fromstring(self.file.read(readsize),
                dtype=self.dtype).reshape(shp)
        return [data[:, u:v].flatten() for u, v in self.channel_locs]

    def __del__(self):
        self.file.close()

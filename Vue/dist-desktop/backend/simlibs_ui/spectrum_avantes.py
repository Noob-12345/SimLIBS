"""Bounded AVS82/84 and documented legacy 60/70 binary layout decoder.

Layout reference: avaread bd8ac82a54e6bc49d6f20e2070b982160ae9e720.
MIT License -- Copyright (c) 2025, Antoine Salden
Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:
The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.
THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

Fixed little-endian widths; no platform ctypes, processing, or dark subtraction.
Legacy layouts independently read from documented byte fields, public lightr
samples used for verification only (GPL implementation not included).
"""
import struct
import numpy as np

MAX_VALUES = 4_000_000


def _array(data, offset, count):
    if count < 2 or count > MAX_VALUES or offset+count*4 > len(data):
        raise ValueError('Avantes数据截断或节点数超限')
    result = np.frombuffer(data, dtype='<f4', count=count, offset=offset).astype(float)
    if not np.isfinite(result).all():
        raise ValueError('Avantes包含NaN/Inf，未修改原值')
    return result


def _axis(x):
    return bool(np.isfinite(x).all() and (np.diff(x) > 0).all() and x.min() > 0)


def decode(data):
    if len(data) > 32_000_000 or len(data) < 8:
        raise ValueError('Avantes文件为空、截断或超过32MB')
    if data[:3] != b'AVS':
        return _legacy(data)
    if data[:5] not in (b'AVS82', b'AVS84'):
        raise ValueError('未知Avantes AVS版本：'+repr(data[:5]))
    channels = data[5]
    if not 1 <= channels <= 64:
        raise ValueError('Avantes通道数非法')
    frames, offset, values = [], 6, 0
    for index in range(channels):
        if offset+322 > len(data):
            raise ValueError('Avantes通道头截断')
        block = struct.unpack_from('<I', data, offset)[0]
        channel, mode = struct.unpack_from('<BB', data, offset+4)
        start, stop, integration, delay, averages = struct.unpack_from('<HHfII', data, offset+83)
        count = stop-start+1
        values += count*4
        end = offset+block+10
        if count < 2 or values > MAX_VALUES or end > len(data) or end < offset+322+count*16:
            raise ValueError('Avantes blockLength/像素数不一致或数据截断')
        serial = data[offset+8:offset+18].split(b'\0')[0].decode('ascii', 'replace')
        arrays = [_array(data, offset+322+part*count*4, count) for part in range(4)]
        calibrated = _axis(arrays[0])
        metadata = dict(channel=channel, serial=serial, measurement_mode=mode, start_pixel=start,
                        stop_pixel=stop, integration_ms=integration, integration_delay=delay,
                        averages=averages, block_length=block, calibrated=calibrated,
                        saved_axis=arrays[0].tolist() if not calibrated else None,
                        corrections='none; scope/dark/reference retained independently',
                        axis_semantics='AVS82/84 stored wavelength float32 vector in nm; AVSInfoBlock per avaread bd8ac82a54e6bc49d6f20e2070b982160ae9e720; monotonic check validates, does not infer units')
        frames.append(dict(id=str(index), label=f'通道 {index+1} · {serial}', unit='nm' if calibrated else 'pixel',
                           x=arrays[0] if calibrated else np.arange(start, stop+1, dtype=float),
                           curves=dict(scope=arrays[1], dark=arrays[2], reference=arrays[3]), metadata=metadata))
        offset = end
    return dict(format=data[:5].decode(), frames=frames, metadata=dict(channels=channels, trailing_bytes=len(data)-offset))


def _legacy(data):
    version = struct.unpack_from('<f', data)[0]
    if version not in (60., 70.):
        raise ValueError('未知Avantes/RAW内容签名；支持AVS82/84及可验证60/70布局')
    coefficient_offset = 296 if version == 70 else 4
    pixel_offset = 316 if version == 70 else 60
    header = 400 if version == 70 else 76
    if len(data) < header+12:
        raise ValueError('Avantes旧RAW头截断')
    coefficients = struct.unpack_from('<5f', data, coefficient_offset)
    first, last, mode = struct.unpack_from('<3f', data, pixel_offset)
    if not first.is_integer() or not last.is_integer() or not 0 <= first < last <= 65535:
        raise ValueError('Avantes旧RAW像素边界非法')
    count = int(last-first+1)
    # Documented legacy scope or interleaved scope/reference/dark, plus trailer.
    parts = (len(data)-header-12)//(count*4)
    if parts not in (1, 3) or len(data) != header+parts*count*4+12:
        raise ValueError('未知Avantes旧RAW数据布局/长度，拒绝猜测偏移')
    raw = _array(data, header, count*parts)
    curves = dict(scope=raw) if parts == 1 else dict(zip(('scope','reference','dark'), raw.reshape(count, 3).T))
    pixels = np.arange(first, last+1, dtype=float)
    axis = np.polynomial.polynomial.polyval(pixels, coefficients)
    calibrated = _axis(axis) and coefficients != (0., 1., 0., 0., 0.)
    integration, averages, extra = struct.unpack_from('<3f', data, header+parts*count*4)
    return dict(format=f'Avantes legacy {int(version)}', frames=[dict(id='0', label='旧RAW通道',
        unit='nm' if calibrated else 'pixel', x=axis if calibrated else pixels, curves=curves,
        metadata=dict(version=version, measurement_mode=mode, coefficients=coefficients,
                      integration_ms=integration, averages=averages, trailer_value=extra,
                      corrections='none; raw stored vectors retained'))], metadata=dict(layout='documented 60/70, exact byte length'))

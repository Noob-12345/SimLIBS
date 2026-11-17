"""Bounded SIF stream decoder; header sequence adapted from sif_parser
8362a4844d7521c8cbd889ff80694332281ed1d8 (_sif_open.py), based on Marcel
Leutenegger's MATLAB script. BSD-3-Clause notice from upstream:

Redistribution and use in source and binary forms, with or without modification,
are permitted provided that the following conditions are met:
1. Redistributions of source code must retain the above copyright notice,
this list of conditions and the following disclaimer.
2. Redistributions in binary form must reproduce the above copyright notice,
this list of conditions and the following disclaimer in the documentation
and/or other materials provided with the distribution.
3. Neither the name of the copyright holder nor the names of its contributors
may be used to endorse or promote products derived from this software without
specific prior written permission.
THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE
LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
POSSIBILITY OF SUCH DAMAGE.

No binary offset guessed from EOF; variable ROI/track sizes retained, no average.
"""
import io
import re
import numpy as np

MAGIC = b'Andor Technology Multi-Channel File\n'


def decode(data):
    if len(data) > 32_000_000 or not data.startswith(MAGIC):
        raise ValueError('不是Andor SIF签名，或文件超过32MB')
    fp = io.BytesIO(data)
    def line():
        value = fp.readline(65537)
        if not value or len(value) > 65536:
            raise ValueError('SIF头截断/行过长')
        return value
    def word():
        value = bytearray()
        while len(value) < 65536:
            c = fp.read(1)
            if not c:
                raise ValueError('SIF头截断')
            if c in (b' ', b'\n', b'\r'):
                if value: return bytes(value)
            else: value.extend(c)
        raise ValueError('SIF字段过长')
    def integer(): return int(word())
    def number(): return float(word())
    def string():
        count = integer()
        if not 0 <= count <= 1_000_000: raise ValueError('SIF字符串长度非法')
        value = fp.read(count)
        if len(value) != count: raise ValueError('SIF字符串截断')
        return value
    fp.seek(len(MAGIC)); line()
    version = integer()
    if not 65548 <= version <= 65567: raise ValueError(f'尚未验证的SIF版本 {version}')
    for _ in range(3): word()
    experiment, detector_temp = integer(), number(); fp.read(10); word()
    exposure, cycle, accumulated = number(), number(), number(); cycles = integer(); fp.read(2)
    stack_cycle, readout = number(), number(); word(); word(); gain = number(); word(); word(); gate = number()
    for _ in range(16): word()
    blaze = number(); line()
    detector = line().decode('utf-8','replace').strip(); dimensions = (integer(), integer()); original = string(); fp.read(2)
    word(); user = string(); fp.read(1); integer(); fp.read(8); number(); number()
    spectrograph = ''
    if version <= 65557:
        for _ in range(2): line()
    elif version == 65558:
        for _ in range(5): line()
    elif version in (65559, 65564):
        for _ in range(8): line()
        spectrograph = line().decode('utf-8','replace').strip()
    elif version == 65565:
        for _ in range(15): line()
    elif version > 65565:
        for _ in range(8): line()
        spectrograph = line().decode('utf-8','replace').strip(); line()
        for _ in range(8): number()
        for _ in range(8): line()
    else: raise ValueError(f'尚未验证的SIF头布局 {version}')
    calibration_version = integer()
    if calibration_version == 65540: line()
    calibration = line(); old_calibration = line(); line(); raman = line()
    for _ in range(3): line()
    axis_name, data_type, image_axis = string(), string(), string()
    for _ in range(5): word()
    frames, roi_count, total_length, image_length = integer(), integer(), integer(), integer()
    if not 1 <= frames <= 4096 or not 1 <= roi_count <= 64: raise ValueError('SIF帧/ROI数超限')
    rois = []
    for _ in range(roi_count):
        word(); values = line().split()
        x0,y1,x1,y0,ybin,xbin = map(int,values[:6])
        if min(xbin,ybin) <= 0 or (x1-x0+1)%xbin or (y1-y0+1)%ybin: raise ValueError('SIF ROI/binning不一致')
        w,h = (x1-x0+1)//xbin,(y1-y0+1)//ybin
        if w < 2 or h < 1: raise ValueError('SIF ROI尺寸非法')
        rois.append(dict(x0=x0,x1=x1,y0=y0,y1=y1,xbin=xbin,ybin=ybin,width=w,height=h))
    per_frame = sum(r['width']*r['height'] for r in rois)
    if frames*per_frame > 4_000_000 or frames*sum(r['height'] for r in rois) > 4096:
        raise ValueError('SIF全节点/轨道超限')
    if image_length != per_frame or total_length != frames*per_frame:
        raise ValueError('SIF图像长度与ROI不一致')
    while fp.read(1) in (b' ',b'\n',b'\r'): pass
    fp.seek(-1,1)
    timestamps = [int(line()) for _ in range(frames)]
    offset = fp.tell()
    flag = fp.readline(100)
    if flag.strip() == b'0': offset = fp.tell()
    elif flag.strip() == b'1' and version == 65567:
        for _ in range(frames): int(line())
        offset = fp.tell()
    if offset+frames*per_frame*4 > len(data): raise ValueError('SIF像素数据截断')
    values = np.frombuffer(data,dtype='<f4',count=frames*per_frame,offset=offset).reshape(frames,per_frame)
    if not np.isfinite(values).all(): raise ValueError('SIF强度含NaN/Inf')
    def coefficients(raw):
        try:
            result = [float(v) for v in raw.split()]
            return result if 2 <= len(result) <= 8 and np.isfinite(result).all() else None
        except ValueError: return None
    default_cal = coefficients(calibration) or coefficients(old_calibration)
    # Multi-dimensional Mechelle coefficients are not a wavelength polynomial.
    if 'Mechelle' in spectrograph: default_cal = None
    per_cal = {}
    if user.startswith(b'Calibration data for'):
        matches = list(re.finditer(rb'Calibration[ _]data[ _]for[ _]frame[ _]+(\d+)\s*[:=]?\s*', user))
        for i,match in enumerate(matches):
            frame = int(match[1])-1
            raw = user[match.end():matches[i+1].start() if i+1 < len(matches) else len(user)]
            per_cal[frame] = coefficients(raw.strip().replace(b',', b' '))
        if set(per_cal) != set(range(frames)) or not all(per_cal.values()):
            raise ValueError('SIF逐帧校准布局不完整/无法解释，不回退默认校准')
    unit_text = axis_name.decode('utf-8','replace')
    declared_nm = unit_text.strip().lower() in ('wavelength','wavelength (nm)','wavelength / nm','nm')
    streams = []
    for f in range(frames):
        base = 0
        for r,roi in enumerate(rois):
            pixels = roi['x0']+np.arange(roi['width'])*roi['xbin']+(roi['xbin']-1)/2
            cal = per_cal.get(f,default_cal)
            x = np.polynomial.polynomial.polyval(pixels,cal) if cal and declared_nm else pixels
            calibrated = bool(cal and declared_nm and (np.diff(x)>0).all() and x.min()>0 and cal != [0.,1.,0.,0.])
            for track in range(roi['height']):
                start=base+track*roi['width'];y=values[f,start:start+roi['width']].astype(float)
                streams.append(dict(id=f'{f}:{r}:{track}',label=f'帧 {f+1} · ROI {r+1} · 轨道 {track+1}',
                    x=x if calibrated else pixels,unit='nm' if calibrated else 'pixel',curves={'counts':y},
                    metadata=dict(frame=f,roi=r,track=track,timestamp=timestamps[f],region=roi,calibration=cal,
                                  original_axis=unit_text,original_image_axis=image_axis.decode('utf-8','replace'),
                                  calibration_applied=calibrated,calibration_note='ROI pixel-bin centres; polynomial coefficient order low to high' if calibrated else 'No proven nm calibration; pixel axis; nm references disabled')))
            base += roi['width']*roi['height']
    return dict(format='Andor SIF',frames=streams,metadata=dict(version=version,frames=frames,rois=rois,
        detector=detector,exposure_seconds=exposure,cycle_seconds=cycle,detector_temperature=detector_temp,
        original_filename=original.decode('utf-8','replace'),data_type=data_type.decode('utf-8','replace'),data_offset=offset))

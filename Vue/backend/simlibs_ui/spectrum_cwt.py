"""Four real continuous wavelets, NumPy integrated-kernel CWT.

Convolution/cropping compatible with PyWavelets 1.8.0, precision=10.
Copyright (c) 2006-2012 Filip Wasilewski <http://en.ig.ma/>
Copyright (c) 2012-2020 The PyWavelets Developers <https://github.com/PyWavelets/pywt>
Permission is hereby granted, free of charge, to any person obtaining a copy of
this software and associated documentation files (the "Software"), to deal in
the Software without restriction, including without limitation the rights to
use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies
of the Software, and to permit persons to whom the Software is furnished to do
so, subject to the following conditions:
The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.
THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""
import math
import numpy as np


def wavefun(name):
    if name not in ('mexh','morl','gaus1','gaus2'):
        raise ValueError('小波须为mexh/morl/gaus1/gaus2')
    bound=8. if name in ('mexh','morl') else 5.
    x=np.linspace(-bound,bound,1024)
    if name=='mexh':psi=2/(math.sqrt(3)*math.pi**.25)*(1-x*x)*np.exp(-x*x/2)
    elif name=='morl':psi=np.exp(-x*x/2)*np.cos(5*x)
    elif name=='gaus1':psi=-2*(2/math.pi)**.25*x*np.exp(-x*x)
    else:psi=2/math.sqrt(3)*(2/math.pi)**.25*(1-2*x*x)*np.exp(-x*x)
    return psi,x


def cwt(values,scales,name):
    data=np.asarray(values,dtype=float);psi,x=wavefun(name)
    integral=np.cumsum(psi)*(x[1]-x[0]);out=np.empty((len(scales),len(data)))
    for i,scale in enumerate(scales):
        indices=(np.arange(scale*(x[-1]-x[0])+1)/(scale*(x[1]-x[0]))).astype(int)
        indices=indices[indices<len(integral)]
        conv=np.convolve(data,integral[indices][::-1])
        coefficient=-np.sqrt(scale)*np.diff(conv)
        if not np.isfinite(conv).all() or not np.isfinite(coefficient).all():
            raise ValueError('CWT卷积溢出，请检查测量强度尺度；未返回0峰')
        delta=(len(coefficient)-len(data))/2
        if delta<0:raise ValueError('小波尺度过小')
        if delta>0:coefficient=coefficient[math.floor(delta):len(coefficient)-math.ceil(delta)]
        out[i]=coefficient
    return out

import datetime
import h5py
import numpy as np

import torch
from torch.utils import data
import torch.nn.functional as F
import soundfile as sf
import librosa
import tensorflow as tf 
import tensorflow.keras.layers as layers


sampleSize = 16000
sample_rate = 16000  # the length of audio for one second
# sample_rate = 8000 # parameter for piano
normalized = False # parameter for piano

quantization_channels=256 #discretize the value to 256 numbers

def mu_law_encode(signal, quantization_channels):
    # Manual mu-law companding and mu-bits quantization
    mu = (quantization_channels - 1).asType(np.float32)
    # signal should be in [-1, +1]
    # minimum operation to deal with rare large amplitudes caused by resampling
    signal = np.minimum(np.abs(signal), 1.0)
    # According to algorithm: https://en.wikipedia.org/wiki/%CE%9C-law_algorithm 
    magnitude = np.log1p(mu * signal) / np.log1p(mu)
    signal = np.sign(signal) * magnitude

    # Map signal from [-1, +1] to [0, mu-1]
    quantized_signal = ((signal + 1) / 2 * mu + 0.5).astype(np.int32)

    return quantized_signal
    
def mu_law_decode(signal, quantization_channels):
    # Calculate inverse mu-law companding and dequantization
    mu = quantization_channels - 1
    # Map signal from [0, mu-1] to [-1, +1]
    signal = 2 * (signal.astype(np.float32) / mu) - 1
    signal = np.sign(signal) * (1.0 / mu) * ((1.0 + mu)**abs(signal) - 1.0)
    return signal

def onehot(a, mu=quantization_channels):
    # TODO: not sure why need transpose here
    return tf.transpose(tf.one_hot(a,mu))

# TODO: copied directly from reader-pytorch.py, need to check
def cateToSignal(output, quantization_channels=256,stage=0):
    mu = quantization_channels - 1
    if stage == 0:
        # Map values back to [-1, 1].
        signal = 2 * ((output*1.0) / mu) - 1
        return signal
    else:
        magnitude = (1 / mu) * ((1 + mu)**np.abs(output) - 1)
        return np.sign(output) * magnitude


class Dataset(data.Dataset):
    def __init__(self, listx, rootx,pad, transform=None):
        self.rootx = rootx
        self.listx = listx
        self.pad=int(pad)
        #self.device=device
        self.transform = transform

    def __len__(self):
        'Denotes the total number of samples'
        return len(self.listx)

    def __getitem__(self, index):
        np.random.seed()
        namex = self.listx[index]

        h5f = h5py.File(self.rootx + str(namex) + '.h5', 'r')
        x = h5f['x'][:]

        # TODO: piano has these two lines
        # x, _ = sf.read('piano/piano{}.wav'.format(namex))
        # print('train piano{}.wav,train audio shape{},rate{}'.format(namex,x.shape,_))

        # TODO: y has these two lines commented out
        factor1 = np.random.uniform(low=0.83, high=1.0)
        x = x*factor1

        if normalized: # probably should be if !normalized
            xmean = x.mean()
            xstd = x.std()
            x = (x - xmean) / xstd

        x = mu_law_encode(x)

        # x = torch.from_numpy(x.reshape(-1)).type(torch.LongTensor)
        # x = F.pad(y, (self.pad, self.pad), mode='constant', value=127)

        x = tf.convert_to_tensor(x.reshape(-1), dtype=tf.int64)
        # not sure about padding
        
        return namex, x.type(torch.LongTensor)


# sample is of type dict： {'x': x, 'y': y}
def toTensor(sample):
    x, y = sample['x'], sample['y']
    x = x.reshape(1, -1)
    y = y.reshape(-1)
    x = tf.convert_to_tensor(x, dtype=tf.float32)
    y = tf.convert_to_tensor(y, dtype=tf.int64)
    return {'x': x, 'y': y}

# TODO: Not sure what random crop is doing, copied from reader-pytorch.py, needs review
def randomcrop(sample, pad=0, output_size=sample_rate):
    print('randomcrop', np.random.get_state()[1][0])
    np.random.seed()
    x, y = sample['x'], sample['y']

    shrink = 0
    low = pad + shrink * sampleSize # 16000
    high = x.shape[-1] - sampleSize - pad - shrink * sampleSize
    print(f'low: {low}, high: {high}')
    startx = np.random.randint(low = low, high = high)
    print(f'startx: {startx}')
    x = x[startx - pad : startx + sampleSize + pad]
    print(f'x shape: {x.shape}')
    print(f'x: {x}')
    y = y[startx : startx + sampleSize]
    print(f'y shape: {y.shape}')
    print(f'y: {y}')
    l = np.random.uniform(0.25, 0.5)
    sp = np.random.uniform(0, 1 - l)
    step = np.random.uniform(-0.5, 0.5)
    ux = int(sp * sample_rate)
    lx = int(l * sample_rate)
    x[ux:ux + lx] = librosa.effects.pitch_shift(x[ux:ux + lx], sample_rate, n_steps=step)

    return {'x': x, 'y': y}


class Testset(data.Dataset):
    def __init__(self, listx, rootx,pad,dilations1,device):
        self.rootx = rootx
        self.listx = listx
        self.pad = int(pad)
        self.device=device
        self.dilations1=dilations1
    def __len__(self):
        'Denotes the total number of samples'
        return len(self.listx)

    def __getitem__(self, index):
        'Generates one sample of data'
        namex = self.listx[index]

        h5f = h5py.File(self.rootx + str(namex) + '.h5', 'r')
        x = h5f['x'][:]

        queue = []
        for i in self.dilations1:
            queue.append(torch.normal(torch.zeros(64,i),std=1).to(self.device))
            #queue.append(torch.zeros((64,i), dtype=torch.float32).to(self.device))

        x = mu_law_encode(x)

        x = torch.from_numpy(x.reshape(-1)).type(torch.LongTensor)
        #y = (torch.randint(0, 255, (self.field)).long())

        return namex,x,queue


        # TODO: the following code is for piano
        y, _ = sf.read('piano/piano{}.wav'.format(namex))
        #factor1 = np.random.uniform(low=0.83, high=1.0)
        #y = y*factor1

        if normalized:
            ymean = y.mean()
            ystd = y.std()
            y = (y - ymean) / ystd

        y = mu_law_encode(y)

        #y = torch.from_numpy(y.reshape(-1)).type(torch.LongTensor)
        print('test piano{}.wav,train audio shape{},rate{}'.format(namex, y.shape, _))
        y = torch.from_numpy(y.reshape(-1)[int(16000*1):]).type(torch.LongTensor)
        print("first second as seed")
        #y = torch.randint(0, 256, (100000,)).type(torch.LongTensor)
        #print("random init")
        #y = F.pad(y, (self.pad, self.pad), mode='constant', value=127)

        return namex,y
import math

import matplotlib.pyplot as plt

from store import Store

import pandas as pd

pd.set_option('display.max_columns', 500)
pd.set_option('display.width', 1000)
pd.set_option('display.max_rows', 50000)

dat = Store.read_file_to_pandas(
    #'dl/jk-pak01-time,voltage,current,temp2,soc2,cell_min,cell_max-HeeBBHH.bin'
    'dl/jk-pak01-time,voltage,current,temp2,soc2,cell_min,cell_max,minmax_idx-HeeBBHHB.bin2'
    #'test-time,voltage,current,soc2,cell_min,cell_max-heeBHH.bin'
)

dat.voltage[dat.voltage < 8] = math.nan

dat['temp'] = (dat.temp2 / 2 - 40)
dat.drop('temp2', axis=1, inplace=True)
dat['temp'][dat.temp < -20] = math.nan
dat['temp'][dat.temp < dat.temp.rolling(20).mean() - 15] = math.nan

num_cells = dat.voltage / (dat.cell_min + dat.cell_max) * 2 * 1000
assert num_cells.std() < 0.02, num_cells.std()
num_cells = int(num_cells.median())

dat['max_idx'] = dat.minmax_idx // num_cells
dat['min_idx'] = dat.minmax_idx % num_cells

#dat.current[abs(dat.current) > 20] = math.nan

print(dat)

dat = dat.iloc[-300:]

plt.subplot(4, 1, 1)
dat.voltage.plot(label='U')
plt.legend()

plt.subplot(4, 1, 2)
dat.temp.plot(label='temp')
plt.legend()

plt.subplot(4, 1, 3)
(dat.soc2 / 2).plot(label='soc')
plt.legend()

plt.subplot(4, 1, 4)
dat.current.plot(label='current')
plt.legend()

plt.show()

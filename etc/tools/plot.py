import math
import os

import matplotlib.pyplot as plt
import pandas as pd

from mints import Store

pd.set_option('display.max_columns', 500)
pd.set_option('display.width', 1000)
pd.set_option('display.max_rows', 50000)

file_path = (
    # 'dl/jk-pak01-time,voltage,current,temp2,soc2,cell_min,cell_max-HeeBBHH.bin'
    # 'dl/jk-pak01-time,voltage,current,temp2,soc2,cell_min,cell_max,minmax_idx-HeeBBHHB.bin'
    # 'test-time,voltage,current,soc2,cell_min,cell_max-heeBHH.bin'
    '../dl/JKPferdestall-time,voltage,current,temp2,soc2,cell_min,cell_max,minmax_idx-HHhBBHHB.bin'
)
dat = Store.read_file_to_pandas(
    file_path
)

dat.index = pd.to_datetime(round(os.stat(file_path).st_mtime) + dat.index.values*10 - dat.index[-1]*10, unit='s')

dat.voltage = dat.voltage / 100
dat.current = dat.current / 100
dat["voltage"][dat.voltage < 8] = math.nan

dat['soc'] = (dat.soc2 / 2)
dat.drop('soc2', axis=1, inplace=True)

dat['temp'] = (dat.temp2 / 2 - 40)
dat.drop('temp2', axis=1, inplace=True)
dat['temp'][dat.temp < -20] = math.nan
dat['temp'][dat.temp < dat.temp.rolling(20).mean() - 15] = math.nan

num_cells = dat.voltage / (dat.cell_min + dat.cell_max) * 2 * 1000
assert num_cells.std() < 0.02, num_cells.std()
num_cells = int(num_cells.median())

dat['max_idx'] = dat.minmax_idx // num_cells
dat['min_idx'] = dat.minmax_idx % num_cells
dat.drop('minmax_idx', axis=1, inplace=True)

# dat.current[abs(dat.current) > 20] = math.nan

print(dat)
print('from file', file_path)

# dat = dat.iloc[-2000:]

plt.subplot(4, 1, 1)
dat.voltage.plot(label='U', marker='.')
plt.legend()

plt.subplot(4, 1, 2)
dat.temp.plot(label='temp')
plt.legend()

plt.subplot(4, 1, 3)
(dat.soc).plot(label='soc')
plt.legend()

plt.subplot(4, 1, 4)
dat.current.plot(label='current')
plt.legend()

plt.show()

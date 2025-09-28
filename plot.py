import math

import matplotlib.pyplot as plt

from store import Store

dat = Store.read_file_to_pandas(
    'dl/jk-pak01-time,voltage,current,temp2,soc2,cell_min,cell_max-HeeBBHH.bin'
    #'test-time,voltage,current,soc2,cell_min,cell_max-heeBHH.bin'
)
dat.temp = (dat.temp2 / 2 - 40)
dat.temp[dat.temp < -20] = math.nan
dat.temp[dat.temp < dat.temp.rolling(20).mean() - 15] = math.nan

dat.current[abs(dat.current) > 20] = math.nan

print(dat)

plt.subplot(4, 1, 1)
dat.voltage.plot(label='U')

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

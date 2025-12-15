import arcticdb as adb

from mints import Store

ac = adb.Arctic("lmdb://arcticdb.lmdb")

ac.create_library('test')

print(ac.list_libraries())

inp_file = '../dl/jk-pak01-time,voltage,current,temp2,soc2,cell_min,cell_max-HeeBBHH.bin'
df = Store.read_file_to_pandas(inp_file)

lib = ac['test']
lib.write("bms_data", df)
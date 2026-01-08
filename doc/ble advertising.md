victron products (e.g. smart shunt) publish sensor data through advertising packets (instant read-out).
it is like a broadcast, everyone can read it without connecting.

advertising data can contain standard types
https://academy.nordicsemi.com/courses/bluetooth-low-energy-fundamentals/lessons/lesson-2-bluetooth-le-advertising/topic/blefund-lesson-2-exercise-1/
https://docs.nordicsemi.com/bundle/zephyr-apis-latest/page/group_bt_gap_defines.html

"Manufacturer Specific Data (BT_DATA_MANUFACTURER_DATA). This is a popular type that enables companies to define their
own custom advertising data, as in the case of iBeacon. We will cover using this data type in the exercise of the next
lesson."

the full list is here: https://elixir.bootlin.com/zephyr/v4.3.0/source/include/zephyr/bluetooth/assigned_numbers.h#L650

victron appears to use 0x10, which is `#define BT_DATA_DEVICE_ID                0x10 /**< Device ID (Profile) */`

although there is `BT_DATA_MANUFACTURER_DATA`

[averisementContainer](https://github.com/keshavdv/victron-ble/blob/main/victron_ble/devices/base.py#L1013)

`10<1b ?><2b model id><1b record type><2b Nonce/Data counter in LSB order (initial value/iv)><first byte enc payload>`

* [detect_device_type](https://github.com/keshavdv/victron-ble/blob/ebb813b805539981012208024cf6ddd4ef02b40e/victron_ble/devices/__init__.py#L70) 
* [model ids](https://github.com/keshavdv/victron-ble/blob/main/victron_ble/devices/base.py#L220)
* [AES decryption](https://github.com/keshavdv/victron-ble/blob/main/victron_ble/devices/base.py#L1039) 

## docs

https://communityarchive.victronenergy.com/questions/187303/victron-bluetooth-advertising-protocol.html

## implementation (clients)

https://github.com/mp-se/victron-receiver
https://github.com/keshavdv/victron-ble
